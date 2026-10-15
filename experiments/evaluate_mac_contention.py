"""Real local generation with fixed output, plus real-paced ASGI PCM; no microphone."""
import asyncio,json,statistics,struct,subprocess,tempfile,time,wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from lecture_study.config import AppConfig
from lecture_study.server import create_app
from lecture_study import transcription as tr
from lecture_study.local_models import CATALOG
from tests.evaluate_human_audio import score
ROOT=Path(__file__).resolve().parents[1];RUNTIME=ROOT/'.local-state/runtime'

def main():
 fixture=next(c for c in json.loads((RUNTIME/'human-audio-20261013/provenance.json').read_text())['clips'] if c['row_idx']==3)
 source=Path(fixture['path']);assert tr.file_hash(source)==fixture['sha256']
 answer='프로세스는 실행 중인 프로그램이며 독립된 주소 공간을 갖습니다. '+('스레드는 프로세스의 메모리를 공유하며 공유 자원에 접근할 때 동기화가 필요합니다. '*14)
 payload={'model':'qwen3.5:4b','messages':[{'role':'user','content':'프로세스와 스레드의 차이를 한국어로 설명하세요.'}],'think':False,'stream':False,'format':{'type':'object','properties':{'answer':{'type':'string','enum':[answer]}},'required':['answer'],'additionalProperties':False},'options':{'temperature':0,'seed':42,'num_ctx':8192,'num_predict':1024}}
 report={'ready':False,'asr_final_padding_ms':30,'input_sha256':fixture['sha256'],'model':payload['model'],'payload':payload,'route':'Real native ASR + actual owned Ollama /api/chat, fixed output for performance only; ASGI WebSocket 250ms paced PCM, no browser/TCP/microphone','baseline':'Full beam/fallback previews and no stop preemption; same final decoder as optimized','optimized':'Greedy previews and cancel obsolete preview on stop','limitations':['One 12.54s read-speech input, two runs per mode; no population ranking.','Generation grammar fixes output for equal work, not a test of answer quality.','Whole-machine swap; background apps and OS scheduling remain uncontrolled.'],'runs':[]}
 output=ROOT/'docs/verification/mac-contention.json'
 def save():output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
 with tempfile.TemporaryDirectory(prefix='lecture-contention-') as temp:
  root=Path(temp);pcm=root/'pcm.wav';asyncio.run(tr.command([RUNTIME/'ffmpeg/bin/ffmpeg','-v','error','-y','-i',source,'-ac','1','-ar','48000','-c:a','pcm_s16le',pcm]))
  app=create_app(AppConfig(root/'data',RUNTIME,port=8765));base='http://127.0.0.1:8765'
  with TestClient(app,base_url=base) as client,ThreadPoolExecutor(max_workers=1) as pool:
   def request(method,path,**kwargs):
    r=client.request(method,path,**kwargs);assert r.is_success,r.text;return r.json()
   login=request('POST','/api/bootstrap',json={'token':app.state.bootstrap_token},headers={'Origin':base});headers={'Origin':base,'X-Session-Token':login['csrf_token']}
   request('POST','/api/local/connect',json={'mode':'managed'},headers=headers)
   with httpx.Client(timeout=10,trust_env=False) as transport:
    tags=transport.get(app.state.ollama_url+'/api/tags');tags.raise_for_status();model=next(m for m in tags.json()['models'] if m['name']==payload['model'])
    assert model['digest']==CATALOG[payload['model']]['runners']['mlx']['digest'] and not model.get('remote_model') and not model.get('remote_host');report['model_digest']=model['digest']
   def generate():
    began=time.perf_counter()
    with httpx.Client(timeout=180,trust_env=False) as transport:
     r=transport.post(app.state.ollama_url+'/api/chat',json=payload);r.raise_for_status();body=r.json()
    assert body['done_reason']=='stop' and json.loads(body['message']['content'])=={'answer':answer}
    return {'elapsed_seconds':time.perf_counter()-began,**{k:body[k] for k in ('prompt_eval_count','eval_count','load_duration','prompt_eval_duration','eval_duration')}}
   generate() # Warm weights and this exact grammar before either measured mode.
   original=tr.transcribe_range
   for mode in ('baseline','optimized','optimized','baseline'):
    calls=[]
    async def decode(clip,start,prompt,runtime,*,preview=False):
     began=time.perf_counter()
     with wave.open(str(clip)) as w:seconds=w.getnframes()/w.getframerate()
     row={'preview':preview,'audio_seconds':seconds};calls.append(row)
     try:return await original(clip,start,prompt,runtime,preview=preview and mode=='optimized')
     except asyncio.CancelledError:row['cancelled']=True;raise
     finally:row['elapsed_seconds']=time.perf_counter()-began
    sid=request('POST','/api/sessions',json={'kind':'lecture','title':'동시 실행 '+mode},headers=headers)['id']
    rid=request('POST','/api/sessions/'+sid+'/audio/start',json={'sample_rate':48000,'transcription_mode':'realtime'},headers=headers)['recording_id']
    with patch.object(tr,'transcribe_range',new=decode):
     generation=pool.submit(generate);swap_before=subprocess.check_output(['sysctl','vm.swapusage'],text=True).strip();max_ack=0
     with client.websocket_connect('ws://127.0.0.1:8765/api/sessions/'+sid+'/audio',headers={'Origin':base}) as ws,wave.open(str(pcm)) as w:
      ws.send_json({'recording_id':rid,'sample_rate':48000,'channels':1,'format':'pcm_s16le','csrf_token':login['csrf_token']});assert ws.receive_json()['type']=='ready';clock=time.perf_counter();cursor=seq=0
      while data:=w.readframes(12000):
       count=len(data)//2;time.sleep(max(0,clock+(cursor+count)/48000-time.perf_counter()));t=time.perf_counter();ws.send_bytes(struct.pack('<QQI',seq,cursor,count)+data);assert ws.receive_json()['type']=='ack';max_ack=max(max_ack,time.perf_counter()-t);cursor+=count;seq+=1
      if mode=='baseline':client.portal.call(lambda:setattr(app.state,'active_asr',None))
      stopped=time.perf_counter();jid=request('POST','/api/recordings/'+rid+'/stop',json={'end_frame':cursor},headers=headers)['id']
      deadline=time.monotonic()+120
      while (job:=request('GET','/api/jobs/'+jid))['status'] in ('queued','running'):
       assert time.monotonic()<deadline;time.sleep(.03)
      assert job['status']=='done',job;post_stop=time.perf_counter()-stopped
     gen=generation.result(timeout=120)
    event=request('GET','/api/sessions/'+sid+'/events');record=event['recordings'][0];assert record['stored_frames']==cursor and not record['gaps'];segments=event['transcripts'];assert segments and all(s['final'] and 0<=s['start_ms']<s['end_ms']<=12540 for s in segments)
    recognized=' '.join(s['text'] for s in segments);row={'mode':mode,'post_stop_seconds':post_stop,'max_ack_seconds':max_ack,'ack_packets':seq,'frames':cursor,'gaps':record['gaps'],'generation':gen,'asr_calls':calls,'recognized':recognized,'swap_before':swap_before,'swap_after':subprocess.check_output(['sysctl','vm.swapusage'],text=True).strip(),**score(fixture['reference_raw_transcription'],recognized)};report['runs'].append(row);save();print(json.dumps({k:row[k] for k in ('mode','post_stop_seconds','generation','cer')},ensure_ascii=False),flush=True)
 assert tr.file_hash(source)==fixture['sha256'];assert len({(r['generation']['prompt_eval_count'],r['generation']['eval_count']) for r in report['runs']})==1
 report['summary']={mode:{'post_stop_median_seconds':statistics.median(r['post_stop_seconds'] for r in report['runs'] if r['mode']==mode),'generation_median_seconds':statistics.median(r['generation']['elapsed_seconds'] for r in report['runs'] if r['mode']==mode)} for mode in ('baseline','optimized')};report['ready']=True;save()
if __name__=='__main__':main()
