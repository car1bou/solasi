"""Native microphone capture independent of the WebView, with durable PCM acknowledgements."""
import asyncio
import math
import queue
import struct
import threading
import time


class InputUnavailable(OSError):
    pass


class Packets:
    def __init__(self,rate,capacity=32):
        self.rate=rate;self.queue=queue.Queue(maxsize=capacity);self.lock=threading.Lock()
        self.origin=None;self.sequence=0;self.end=0;self.pending=0;self.fault='';self.last_input=time.monotonic()

    def push(self,data,frames,adc_time):
        with self.lock:
            self.last_input=time.monotonic()
            if not 0<frames<=self.rate or len(data)!=frames*2:
                self.fault='마이크 입력 프레임 형식이 바뀌었습니다';return
            if math.isfinite(adc_time) and adc_time>0:
                if self.origin is None:self.origin=adc_time
                first=round((adc_time-self.origin)*self.rate)
                if first<self.end-self.rate//100:self.fault='마이크 입력 시각이 바뀌었습니다'
                first=max(self.end,first)
            else:first=self.end
            packet=struct.pack('<QQI',self.sequence,first,frames)+data
            self.sequence+=1;self.end=first+frames
            try:self.queue.put_nowait(packet);self.pending+=frames
            except queue.Full:self.fault='마이크 저장 버퍼가 가득 찼습니다'

    def ack(self,frames):
        with self.lock:self.pending-=frames


class Capture:
    def __init__(self,ident,session,mode,engine,emit):
        self.id=ident;self.session=session;self.mode=mode;self.engine=engine;self.emit=emit
        self.stream=None;self.task=None;self.buffer=None;self.recording=None;self.stream_id=None
        self.stopping=False;self.recovered=False;self.error='';self.seconds=0;self.last_publish=0;self.phase='starting'
        self.starting=None;self.deferred=None

    def publish(self):
        buffer=self.buffer
        self.emit('solasi-recording-state',{'capture_id':self.id,'phase':self.phase,'seconds':self.seconds+(buffer.end/buffer.rate if buffer else 0),'pending':buffer.pending/buffer.rate if buffer else 0,'error':self.error,'recovered':self.recovered})
        self.last_publish=time.monotonic()

    async def start(self):
        self.starting=asyncio.current_task();self.publish()
        try:
            await self._open()
            if self.stopping:
                await self._finish_segment();self.phase='idle';self.publish();self.engine.captures.pop(self.id,None)
            else:self.phase='recording';self.publish();self.task=asyncio.create_task(self._consume())
        except BaseException:
            self.stopping=True
            await self._finish_segment(interrupted=True)
            self.phase='idle';self.publish();raise
        finally:self.starting=None

    async def _open(self,resume=None):
        import sounddevice as sd
        try:
            device=await asyncio.to_thread(sd.query_devices,kind='input')
            rate=int(device['default_samplerate'])
            if not 8000<=rate<=192000:raise ValueError('마이크 sample rate를 지원하지 않습니다')
            await asyncio.to_thread(sd.check_input_settings,samplerate=rate,channels=1,dtype='int16')
            self.buffer=Packets(rate)
            buffer=self.buffer
            def callback(data,frames,timing,status):
                if status:buffer.fault='마이크 입력이 끊겼습니다 · '+str(status)
                buffer.push(bytes(data),frames,float(timing.inputBufferAdcTime))
            self.stream=await asyncio.to_thread(sd.RawInputStream,samplerate=rate,channels=1,dtype='int16',blocksize=max(1,rate//5),callback=callback)
            if resume:
                await asyncio.to_thread(self.stream.start)
                started=time.monotonic()
                while self.buffer.queue.empty():
                    if self.stopping:return False
                    if time.monotonic()-started>5:raise ValueError('마이크 복귀를 기다리고 있습니다')
                    await asyncio.sleep(.05)
        except Exception as error:raise InputUnavailable(str(error)) from None
        body={'sample_rate':rate,'transcription_mode':self.mode}
        if resume:body['resume_from']=resume
        record=await self.engine.json('/api/sessions/'+self.session+'/audio/start',body)
        self.recording=record['recording_id']
        # audio_open's request identity is the stream identity used by subsequent packets.
        self.stream_id,result=await self._open_audio_stream(rate)
        if result.get('type')!='ready':raise ValueError('녹음 저장 연결을 준비하지 못했습니다')
        if not self.stopping and not resume:await asyncio.to_thread(self.stream.start)
        return True

    async def _open_audio_stream(self,rate):
        import uuid
        ident=uuid.uuid4().hex;result={}
        def receive(event,body,fields):
            if event=='error':raise ValueError(fields.get('message','녹음 연결 실패'))
            if event=='complete':result.update(fields.get('payload',{}))
        self.engine.worker.sinks[ident]=receive
        try:await self.engine.worker.audio_open({'id':ident,'session_id':self.session,'recording_id':self.recording,'sample_rate':rate},b'')
        finally:self.engine.worker.sinks.pop(ident,None)
        return ident,result

    async def _drain(self):
        if not self.buffer or not self.stream_id:return
        for _ in range(self.buffer.queue.qsize()):
            packet=self.buffer.queue.get_nowait();seq,first,count=struct.unpack_from('<QQI',packet)
            ack=await asyncio.wait_for(self.engine.audio_rpc('audio_packet',packet,stream_id=self.stream_id),10)
            if ack.get('type')!='ack' or ack.get('seq')!=seq or ack.get('frame_count')!=count:
                raise ValueError('원음 저장 확인 번호가 일치하지 않습니다')
            self.buffer.ack(count)
            if time.monotonic()-self.last_publish>=1:self.publish()

    async def _consume(self):
        try:
            while not self.stopping:
                await self._drain()
                fault=self.buffer.fault
                if time.monotonic()-self.buffer.last_input>5:fault='마이크 입력이 도착하지 않습니다'
                if fault:
                    self.error=fault;self.phase='recovering';self.publish()
                    old=self.recording
                    await self._finish_segment(interrupted=True,defer=self.mode=='after_stop' and not self.recovered and not self.stopping)
                    if self.recovered:raise ValueError(fault)
                    while not self.stopping:
                        try:
                            if not await self._open(resume=old):break
                            self.recovered=True;self.error='';self.phase='recording';self.publish();break
                        except InputUnavailable as error:
                            self.error=str(error)[:300]
                            await self._finish_segment(interrupted=True,defer=True)
                            self.publish();await asyncio.sleep(1)
                if time.monotonic()-self.last_publish>=1:self.publish()
                await asyncio.sleep(.025)
            await self._drain()
        except Exception as error:
            self.error=str(error)[:300];self.stopping=True
        finally:
            try:await self._finish_segment(interrupted=bool(self.error))
            except Exception as error:self.error=str(error)[:300]+' · 저장된 원음을 확인하세요'
            self.phase='idle';self.publish();self.engine.captures.pop(self.id,None)

    async def _finish_segment(self,interrupted=False,defer=False):
        if self.stream:
            stream,self.stream=self.stream,None
            try:await asyncio.to_thread(stream.stop)
            except Exception as error:self.error=str(error)[:300];interrupted=True
            try:await asyncio.to_thread(stream.close)
            except Exception as error:self.error=str(error)[:300];interrupted=True
        if self.buffer and self.stream_id:
            try:await self._drain()
            except Exception as error:self.error=str(error)[:300];interrupted=True
        if self.recording:
            await self.engine.json('/api/recordings/'+self.recording+'/stop',{'end_frame':self.buffer.end,'interrupted':interrupted,'reason':self.error[:300] or None,'defer_transcription':defer})
            if defer:self.deferred=(self.recording,self.buffer.end,self.error)
            self.recording=None
        if not defer and self.deferred:
            ident,end,reason=self.deferred
            await self.engine.json('/api/recordings/'+ident+'/stop',{'end_frame':end,'interrupted':True,'reason':reason[:300] or None,'defer_transcription':False})
            self.deferred=None
        if self.stream_id:
            ident,self.stream_id=self.stream_id,None
            await self.engine.audio_rpc('audio_close',stream_id=ident)
        if self.buffer:self.seconds+=self.buffer.end/self.buffer.rate;self.buffer=None

    async def stop(self,interrupted=False):
        self.stopping=True;self.phase='stopping'
        if interrupted:self.error=self.error or '앱 종료로 녹음을 마쳤습니다'
        self.publish()
        if self.starting and self.starting is not asyncio.current_task():await asyncio.wait_for(asyncio.shield(self.starting),15)
        if self.task:await asyncio.wait_for(asyncio.shield(self.task),15)
        else:
            await self._finish_segment(interrupted=interrupted)
            self.phase='idle';self.publish();self.engine.captures.pop(self.id,None)
