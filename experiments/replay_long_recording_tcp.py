"""Paced real TCP PCM replay; no browser/worklet/microphone capture claim."""
import argparse,asyncio,hashlib,json,struct,time,wave
from pathlib import Path
from urllib.parse import urlsplit
import httpx,websockets

async def main(folder):
    info=json.loads((folder/'info.json').read_text());url=urlsplit(info['url']);base=url.scheme+'://'+url.netloc;sid=info['session_id'];path=folder/'input.wav'
    with wave.open(str(path))as source:rate=source.getframerate();frames=source.getnframes();assert source.getsampwidth()==2 and source.getnchannels()==1
    duration=frames/rate;assert duration>600
    runs=[];samples=[];capture_route='Paced PCM file replay over real WebSocket/TCP -> production SQLite/WAV/Whisper and actual Qwen; no browser capture/worklet/microphone'
    async with httpx.AsyncClient(base_url=base,timeout=30,trust_env=False)as client:
        bootstrap=await client.post('/api/bootstrap',headers={'Origin':base},json={'token':url.fragment.split('bootstrap=',1)[1]});bootstrap.raise_for_status();token=bootstrap.json()['csrf_token'];headers={'Origin':base,'X-Session-Token':token}
        async def post(endpoint,body):
            response=await client.post('/api'+endpoint,headers=headers,json=body);response.raise_for_status();return response.json()
        async def get(endpoint):
            response=await client.get('/api'+endpoint);response.raise_for_status();return response.json()
        async def ask():return await post('/ai/jobs',{'session_id':sid,'kind':'answer','prompt':'프로세스와 스레드의 차이와 동기화가 필요한 이유를 근거로 세 문장으로 설명하세요.','scope':{'session_id':sid,'mode':'current'},'web':False})
        await post('/local/connect',{'mode':'managed'})
        response=await client.put('/api/settings',headers=headers,json={'provider':'ollama','model':'qwen3.5:4b','context_limit':8192});response.raise_for_status()
        warm=await ask()
        while (warm:=await get('/jobs/'+warm['id']))['status']in ('queued','running'):await asyncio.sleep(.5)
        assert warm['status']=='done',warm.get('error')
        for concurrent in (True,False):
            run={'mode':'concurrent'if concurrent else'asr_only','capture_route':capture_route,'started':round(time.time()*1000),'generations':[],'acks':[]};runs.append(run)
            record=await post('/sessions/'+sid+'/audio/start',{'sample_rate':rate,'transcription_mode':'realtime'});rid=record['recording_id'];sent={};last_ack=-1;stop=asyncio.Event();started=time.perf_counter();run['play_started']=round(time.time()*1000)
            async def telemetry():
                while not stop.is_set():
                    event=await get('/sessions/'+sid+'/events');jobs=await get('/sessions/'+sid+'/jobs');current=next(r for r in event['recordings']if r['id']==rid)
                    samples.append({'at':round(time.time()*1000),'audio_seconds':min(duration,time.perf_counter()-started),'recordings':[current],'final_end_ms':max([0]+[t['end_ms']for t in event['transcripts']if t['final']and t['recording_id']==rid]),'jobs':[{'id':j['id'],'status':j['status'],'result':j['result']}for j in jobs if j['status']in ('queued','running')]})
                    await post('/fixture/telemetry',{'runs':runs,'samples':samples,'ready':False,'capture_route':capture_route})
                    await asyncio.sleep(1)
            async def generations():
                at=25
                while at<duration:
                    await asyncio.sleep(max(0,started+at-time.perf_counter()))
                    if stop.is_set():return
                    job=await ask();run['generations'].append({'id':job['id'],'submitted':round(time.time()*1000),'audio_seconds':time.perf_counter()-started});at+=60
            cookie='; '.join(k+'='+v for k,v in client.cookies.items());tasks=[]
            async with websockets.connect('ws://'+url.netloc+'/api/sessions/'+sid+'/audio',additional_headers={'Origin':base,'Cookie':cookie},max_size=1024**2)as socket:
                await socket.send(json.dumps({'recording_id':rid,'sample_rate':rate,'channels':1,'format':'pcm_s16le','csrf_token':token}));hello=json.loads(await socket.recv());assert hello['type']=='ready',hello
                async def acknowledgements():
                    nonlocal last_ack
                    try:
                        async for message in socket:
                            body=json.loads(message)
                            if body['type']=='ack':
                                seq=body['seq'];assert seq in sent;last_ack=seq;run['acks'].append({'recording_id':rid,'seq':seq,'frames':body['frame_count'],'ms':(time.perf_counter()-sent.pop(seq))*1000})
                            elif body['type']=='error':raise ValueError(body.get('error')or body.get('message')or str(body))
                    except websockets.ConnectionClosedOK:pass
                receiver=asyncio.create_task(acknowledgements());tasks=[asyncio.create_task(telemetry())]
                if concurrent:tasks.append(asyncio.create_task(generations()))
                try:
                    cursor=seq=0;source_hash=hashlib.sha256()
                    with wave.open(str(path))as source:
                        while payload:=source.readframes(round(rate*.25)):
                            await asyncio.sleep(max(0,started+cursor/rate-time.perf_counter()));sent[seq]=time.perf_counter();source_hash.update(payload)
                            await socket.send(struct.pack('<QQI',seq,cursor,len(payload)//2)+payload);cursor+=len(payload)//2;seq+=1
                            if receiver.done():await receiver;raise ValueError('PCM connection ended before input completion')
                    await asyncio.sleep(max(0,started+duration-time.perf_counter()))
                    deadline=time.perf_counter()+10
                    while last_ack!=seq-1 and time.perf_counter()<deadline:
                        if receiver.done():await receiver;raise ValueError('PCM acknowledgements stopped')
                        await asyncio.sleep(.02)
                    assert cursor==frames and last_ack==seq-1 and not sent,(cursor,frames,last_ack,seq,len(sent))
                    run['stopped']=round(time.time()*1000);await post('/recordings/'+rid+'/stop',{'end_frame':cursor});run['last_state']={'phase':'idle','seconds':duration,'pending':0,'error':'','recovered':False}
                    run['input_pcm_sha256']=source_hash.hexdigest()
                finally:
                    stop.set()
                    for task in tasks:task.cancel()
                    await asyncio.gather(*tasks,return_exceptions=True);receiver.cancel();await asyncio.gather(receiver,return_exceptions=True)
            deadline=time.perf_counter()+600
            while True:
                jobs=await get('/sessions/'+sid+'/jobs');active=[j for j in jobs if j['status']in ('queued','running')]
                if not active:break
                assert time.perf_counter()<deadline,'Post-recording completion timeout'
                await asyncio.sleep(1)
            run['done']=round(time.time()*1000);run['jobs']=jobs;run['events']=await get('/sessions/'+sid+'/events')
            with wave.open(str(folder/'data/audio'/rid/'raw.wav'))as captured:
                assert captured.getnframes()==frames and captured.getframerate()==rate
                digest=hashlib.sha256()
                while data:=captured.readframes(rate):digest.update(data)
            run['captured_pcm_sha256']=digest.hexdigest();assert run['captured_pcm_sha256']==run['input_pcm_sha256']
            saved=next(r for r in run['events']['recordings']if r['id']==rid);assert saved['status']=='stopped'and not saved['gaps']and not saved['error'],saved
            assert all(j['status']=='done'or j['kind']=='asr_review'and j['status']in ('cancelled','failed','interrupted')for j in jobs),[(j['kind'],j['status'],j['error'])for j in jobs]
            await post('/fixture/telemetry',{'runs':runs,'samples':samples,'ready':len(runs)==2,'capture_route':capture_route})
            print(json.dumps({'run':run['mode'],'seconds':duration,'acks':len(run['acks']),'generation_jobs':len(run['generations']),'pcm_identical':True,'post_stop_seconds':(run['done']-run['stopped'])/1000}),flush=True)
        (folder/'tcp-client-result.json').write_text(json.dumps({'ready':True,'capture_route':capture_route,'runs':runs},ensure_ascii=False,indent=2))
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('folder',type=Path);args=parser.parse_args();assert not (args.folder/'tcp-client-result.json').exists();asyncio.run(main(args.folder))
