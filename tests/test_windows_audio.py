import asyncio
import json
from pathlib import Path
import struct
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from lecture_study.config import AppConfig
from lecture_study.windows_bridge import Engine
from lecture_study import windows_audio as audio


class PacketTests(unittest.TestCase):
    def test_bounded_packets_preserve_adc_gap_and_count_dropped_tail(self):
        buffer=audio.Packets(8000,capacity=1)
        buffer.push(b'\0\0'*100,100,10.0)
        buffer.push(b'\0\0'*100,100,10.1)
        self.assertIn('버퍼',buffer.fault)
        packet=buffer.queue.get_nowait()
        self.assertEqual(struct.unpack_from('<QQI',packet),(0,0,100))
        self.assertEqual(buffer.end,900)
        self.assertEqual(buffer.pending,100)
        buffer.ack(100);self.assertEqual(buffer.pending,0)


class CaptureTests(unittest.TestCase):
    def test_microphone_absence_does_not_spend_recovery_before_fresh_input(self):
        directory=self.enterContext(tempfile.TemporaryDirectory())
        root=Path(directory);engine=Engine(AppConfig(root/'data',root/'runtime',embedded=True));engine.start();self.addCleanup(engine.close)
        async def create():return await engine.json('/api/sessions',{'title':'reconnect','kind':'meeting'})
        sid=engine.submit(create()).result(5)['id'];queries=[]
        class PortAudioError(Exception):pass
        def query(**_):
            queries.append(True)
            if len(queries)==2:raise PortAudioError('microphone absent')
            return {'default_samplerate':8000}
        class Input:
            def __init__(self,**kwargs):self.callback=kwargs['callback']
            def start(self):self.callback(b'\0\0'*800,800,SimpleNamespace(inputBufferAdcTime=1.0),False)
            def stop(self):pass
            def close(self):pass
        device=SimpleNamespace(query_devices=query,RawInputStream=Input,check_input_settings=lambda **_:None,PortAudioError=PortAudioError)
        with patch.dict(sys.modules,{'sounddevice':device}):
            async def record():
                capture=audio.Capture('id',sid,'after_stop',engine,lambda *_:None);engine.captures['id']=capture
                await capture.start();capture.buffer.fault='input removed'
                async def wait():
                    while not capture.task.done() and not(capture.recovered and capture.phase=='recording'):await asyncio.sleep(.02)
                await asyncio.wait_for(wait(),5);await capture.stop()
            engine.submit(record()).result(10)
        with engine.submit(engine.http('/api/sessions/'+sid+'/recordings')).result(5) as response:records=json.load(response.body)
        self.assertEqual(len(records),2)
        self.assertTrue(all(record['stored_frames']==800 and record['transcription_released']==1 for record in records))

    def test_stop_while_device_is_opening_cannot_start_late_recording(self):
        directory=self.enterContext(tempfile.TemporaryDirectory())
        root=Path(directory);engine=Engine(AppConfig(root/'data',root/'runtime',embedded=True));engine.start();self.addCleanup(engine.close)
        async def create():return await engine.json('/api/sessions',{'title':'late permission','kind':'meeting'})
        sid=engine.submit(create()).result(5)['id'];opening=threading.Event();release=threading.Event();events=[]
        def query(**_):opening.set();release.wait(3);return {'default_samplerate':8000}
        class Input:
            def __init__(self,**kwargs):pass
            def start(self):raise AssertionError('recording started after stop')
            def stop(self):pass
            def close(self):pass
        device=SimpleNamespace(query_devices=query,RawInputStream=Input,check_input_settings=lambda **_:None)
        with patch.dict(sys.modules,{'sounddevice':device}):
            capture=audio.Capture('id',sid,'after_stop',engine,lambda name,state:events.append(state))
            engine.captures['id']=capture
            starting=engine.submit(capture.start());self.assertTrue(opening.wait(3))
            stopping=engine.submit(capture.stop());release.set();starting.result(5);stopping.result(5)
        with engine.submit(engine.http('/api/sessions/'+sid+'/recordings')).result(5) as response:records=json.load(response.body)
        self.assertTrue(all(record['status']!='recording' for record in records));self.assertEqual(events[-1]['phase'],'idle')

    def test_native_capture_sends_saved_ack_then_stop_keeps_pcm_without_webview(self):
        directory=self.enterContext(tempfile.TemporaryDirectory())
        root=Path(directory);engine=Engine(AppConfig(root/'data',root/'runtime',embedded=True));engine.start()
        self.addCleanup(engine.close)
        async def session():
            course=await engine.json('/api/courses',{'title':'Windows'})
            return await engine.json('/api/sessions',{'course_id':course['id'],'title':'마이크','kind':'lecture'})
        sid=engine.submit(session()).result(5)['id'];events=[];streams=[]
        class Input:
            def __init__(self,**kwargs):self.callback=kwargs['callback'];streams.append(self)
            def start(self):
                self.callback(b'\x01\x00'*1600,1600,SimpleNamespace(inputBufferAdcTime=1.0),False)
            def stop(self):pass
            def close(self):pass
        device=SimpleNamespace(query_devices=lambda **_: {'default_samplerate':8000},RawInputStream=Input,check_input_settings=lambda **_:None)
        with patch.dict(sys.modules,{'sounddevice':device}):
            async def record():
                capture=audio.Capture('id',sid,'after_stop',engine,lambda name,value:events.append((name,value)))
                engine.captures['id']=capture
                await capture.start();await capture.stop()
            engine.submit(record()).result(10)
        self.assertEqual(events[-1][1]['phase'],'idle')
        with engine.submit(engine.http('/api/sessions/'+sid+'/recordings')).result(5) as response:
            record=json.load(response.body)[0]
        self.assertEqual(record['stored_frames'],1600);self.assertEqual(record['source_frames'],1600)
        self.assertEqual((root/'data'/'audio'/record['id']/'raw.wav').stat().st_size,44+3200)

    def test_device_stop_error_still_saves_received_frames_and_finishes_recording(self):
        directory=self.enterContext(tempfile.TemporaryDirectory())
        root=Path(directory);engine=Engine(AppConfig(root/'data',root/'runtime',embedded=True));engine.start();self.addCleanup(engine.close)
        async def create():return await engine.json('/api/sessions',{'title':'device failure','kind':'meeting'})
        sid=engine.submit(create()).result(5)['id']
        class Input:
            def __init__(self,**kwargs):self.callback=kwargs['callback']
            def start(self):self.callback(b'\0\0'*800,800,SimpleNamespace(inputBufferAdcTime=1.0),False)
            def stop(self):raise OSError('device removed')
            def close(self):raise OSError('device handle already removed')
        device=SimpleNamespace(query_devices=lambda **_: {'default_samplerate':8000},RawInputStream=Input,check_input_settings=lambda **_:None)
        with patch.dict(sys.modules,{'sounddevice':device}):
            async def record():
                capture=audio.Capture('id',sid,'after_stop',engine,lambda *_:None);engine.captures['id']=capture
                await capture.start();await capture.stop()
            engine.submit(record()).result(10)
        with engine.submit(engine.http('/api/sessions/'+sid+'/recordings')).result(5) as response:record=json.load(response.body)[0]
        self.assertEqual(record['stored_frames'],800);self.assertEqual(record['status'],'interrupted')
        self.assertEqual(record['transcription_released'],1)


if __name__=='__main__':unittest.main()
