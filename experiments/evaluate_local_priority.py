"""Compare ASR-first admission using real models and identical constrained answer tokens."""
import asyncio,json,statistics,struct,subprocess,tempfile,time,wave
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from lecture_study.config import AppConfig
from lecture_study.server import create_app
from lecture_study import answers,server,transcription as tr
from lecture_study.local_models import CATALOG
from tests.evaluate_human_audio import score

ROOT=Path(__file__).resolve().parents[1];RUNTIME=ROOT/'.local-state/runtime'

def main():
    fixture=next(c for c in json.loads((RUNTIME/'human-audio-20261013/provenance.json').read_text())['clips'] if c['row_idx']==3)
    source=Path(fixture['path']);assert tr.file_hash(source)==fixture['sha256']
    answer='프로세스는 실행 중인 프로그램이며 독립된 주소 공간을 갖습니다. '+('스레드는 프로세스의 메모리를 공유하며 공유 자원에 접근할 때 동기화가 필요합니다. '*4)
    report={'ready':False,'input_sha256':fixture['sha256'],'audio_seconds':12.54,'model':'qwen3.5:4b','route':'Actual app AI job + native ASR, realtime ASGI WebSocket PCM. New generation requested immediately after recording stop, with final ASR pending.','limitations':['Fixed answer grammar controls output work, not answer quality.','Two runs per mode, ABBA order; background apps and whole-machine swap are uncontrolled.','No browser, TCP, microphone or first-token measurement.','Already running generation is preserved; this benchmark measures only newly requested generation during final ASR backlog.'],'runs':[]}
    output=ROOT/'docs/verification/local-priority.json'
    def save():output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    save()
    with tempfile.TemporaryDirectory(prefix='lecture-priority-') as temp:
        root=Path(temp);pcm=root/'pcm.wav';asyncio.run(tr.command([RUNTIME/'ffmpeg/bin/ffmpeg','-nostdin','-v','error','-y','-i',source,'-ac','1','-ar','48000','-c:a','pcm_s16le',pcm]))
        app=create_app(AppConfig(root/'data',RUNTIME,port=8765));base='http://127.0.0.1:8765'
        with TestClient(app,base_url=base) as client:
            def request(method,path,**kwargs):
                r=client.request(method,path,**kwargs);assert r.is_success,r.text;return r.json()
            login=request('POST','/api/bootstrap',json={'token':app.state.bootstrap_token},headers={'Origin':base});headers={'Origin':base,'X-Session-Token':login['csrf_token']}
            request('POST','/api/local/connect',json={'mode':'managed'},headers=headers)
            request('PUT','/api/settings',json={'provider':'ollama','model':'qwen3.5:4b','context_limit':8192},headers=headers)
            report['context_limit']=8192;report['generation_options']={'seed':42,'temperature':0}
            sid=request('POST','/api/sessions',json={'kind':'lecture','title':'동일 질문 전사 우선 비교'},headers=headers)['id']
            note=request('PUT','/api/sessions/'+sid+'/note',json={'text':'프로세스는 실행 중인 프로그램이며 스레드는 프로세스의 메모리를 공유합니다.'},headers=headers)
            schema=deepcopy(answers.ANSWER_SCHEMA);schema['properties']['answer']['enum']=[answer];schema['properties']['uncertainty']['enum']=['']
            citation=deepcopy(answers.CITATION_SCHEMA)
            for key in ('page','start_ms','end_ms'):citation['properties'][key]={'type':'null'}
            schema['properties']['citations']={'type':'array','minItems':1,'maxItems':1,'items':citation}
            report['schema']=schema
            payload={'session_id':sid,'prompt':'프로세스와 스레드의 차이를 한국어로 설명하세요.','scope':{'session_id':sid,'mode':'current'}}
            def ask():return request('POST','/api/ai/jobs',json=payload,headers=headers)
            def done(ident):
                deadline=time.monotonic()+240
                while (job:=request('GET','/api/jobs/'+ident))['status'] in ('queued','running'):
                    assert time.monotonic()<deadline;time.sleep(.03)
                assert job['status']=='done',job
                return request('GET','/api/artifacts/'+job['result']['id'])
            original_generate=answers.generate
            async def deterministic(*args,**kwargs):
                async def forward(req):
                    async with httpx.AsyncClient(timeout=180,trust_env=False) as network:
                        if req.url.path=='/api/chat':
                            body=json.loads(req.content);body['options'].update(seed=42,temperature=0)
                            return await network.post(str(req.url),json=body)
                        return await network.request(req.method,str(req.url),content=req.content,headers=req.headers)
                async with httpx.AsyncClient(transport=httpx.MockTransport(forward)) as transport:
                    return await original_generate(*args,client=transport,**kwargs)
            with patch.object(answers,'ANSWER_SCHEMA',schema),patch.object(answers,'generate',new=deterministic):
                warm=done(ask()['id']);assert warm['body']['answer']==answer
                assert warm['metadata']['digest']==CATALOG['qwen3.5:4b']['runners']['mlx']['digest']
                report['model_digest']=warm['metadata']['digest'];save();print('Warm generation complete',flush=True)
                original=server.wait_for_transcription
                for mode in ('baseline','optimized','optimized','baseline'):
                    waits=[]
                    async def admission(db,jid):
                        began=time.perf_counter();pending=bool(db.execute("SELECT 1 FROM transcript_ranges WHERE final=1 AND status IN ('queued','running') LIMIT 1").fetchone())
                        if mode=='optimized':await original(db,jid)
                        waits.append({'pending_at_admission':pending,'wait_seconds':time.perf_counter()-began})
                    with patch.object(server,'wait_for_transcription',new=admission):
                        rid=request('POST','/api/sessions/'+sid+'/audio/start',json={'sample_rate':48000,'transcription_mode':'realtime'},headers=headers)['recording_id']
                        with client.websocket_connect('ws://127.0.0.1:8765/api/sessions/'+sid+'/audio',headers={'Origin':base}) as ws,wave.open(str(pcm)) as w:
                            ws.send_json({'recording_id':rid,'sample_rate':48000,'channels':1,'format':'pcm_s16le','csrf_token':login['csrf_token']});assert ws.receive_json()['type']=='ready'
                            clock=time.perf_counter();cursor=seq=0
                            while data:=w.readframes(12000):
                                count=len(data)//2;time.sleep(max(0,clock+(cursor+count)/48000-time.perf_counter()));ws.send_bytes(struct.pack('<QQI',seq,cursor,count)+data);assert ws.receive_json()['type']=='ack';cursor+=count;seq+=1
                            stopped=time.perf_counter();asr=request('POST','/api/recordings/'+rid+'/stop',json={'end_frame':cursor},headers=headers)
                            submitted=time.perf_counter();job=ask();paused=False;deadline=time.monotonic()+240
                            while request('GET','/api/jobs/'+asr['id'])['status'] in ('queued','running'):
                                current=request('GET','/api/jobs/'+job['id']);paused|=bool((current['result'] or {}).get('paused_reason'))
                                assert time.monotonic()<deadline;time.sleep(.03)
                            asr_state=request('GET','/api/jobs/'+asr['id'])
                            if asr_state['status']!='done':
                                report['failure']={'asr_job':asr_state,'generation_job':request('GET','/api/jobs/'+job['id']),'events':request('GET','/api/sessions/'+sid+'/events'),'swap':subprocess.check_output(['sysctl','vm.swapusage'],text=True).strip()};save()
                            assert asr_state['status']=='done',asr_state
                            post_stop=time.perf_counter()-stopped;artifact=done(job['id']);generation_total=time.perf_counter()-submitted
                        assert artifact['body']['answer']==answer and artifact['metadata']['digest']==report['model_digest']
                        event=request('GET','/api/sessions/'+sid+'/events');record=next(r for r in event['recordings'] if r['id']==rid)
                        segments=[s for s in event['transcripts'] if s['recording_id']==rid]
                        assert record['stored_frames']==cursor and cursor==601920 and seq==51 and not record['gaps'] and all(s['final'] for s in segments)
                        text=' '.join(s['text'] for s in segments)
                        row={'mode':mode,'post_stop_seconds':post_stop,'generation_total_seconds':generation_total,'generation_provider_elapsed_ms':artifact['metadata']['elapsed_ms'],'usage':artifact['metadata']['usage'],'observed_waiting_status':paused,'admissions':waits,'ack_packets':seq,'frames':cursor,'gaps':record['gaps'],'recognized':text,'swap_after':subprocess.check_output(['sysctl','vm.swapusage'],text=True).strip(),**score(fixture['reference_raw_transcription'],text)}
                        assert any(w['pending_at_admission'] for w in waits)
                        report['runs'].append(row);save();print(json.dumps(row,ensure_ascii=False),flush=True)
    assert tr.file_hash(source)==fixture['sha256']
    assert len({(r['usage']['prompt_eval_count'],r['usage']['eval_count']) for r in report['runs']})==1
    report['summary']={mode:{key:statistics.median(r[key] for r in report['runs'] if r['mode']==mode) for key in ('post_stop_seconds','generation_total_seconds','generation_provider_elapsed_ms')} for mode in ('baseline','optimized')}
    report['ready']=True;save()

if __name__=='__main__':main()
