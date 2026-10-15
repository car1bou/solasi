"""Actual local LLM plus real-paced human PCM; ASGI, no browser or microphone."""
import asyncio,json,struct,subprocess,tempfile,time,wave
from pathlib import Path
from fastapi.testclient import TestClient
from lecture_study.config import AppConfig
from lecture_study.server import create_app
from lecture_study.transcription import command,file_hash
from tests.evaluate_human_audio import score
ROOT=Path(__file__).resolve().parents[1];RUNTIME=ROOT/'.local-state/runtime'
def memory():
 return {'vm_stat':subprocess.check_output(['vm_stat'],text=True),'swapusage':subprocess.check_output(['sysctl','vm.swapusage'],text=True).strip()}
def main():
 fixtures=json.loads((RUNTIME/'human-audio-20261013/provenance.json').read_text());fixture=next(c for c in fixtures['clips'] if c['row_idx']==3);source=Path(fixture['path']);assert file_hash(source)==fixture['sha256']
 report={'input_sha256':fixture['sha256'],'audio_seconds':fixture['duration_seconds'],'route':'ASGI TestClient authenticated WebSocket, 250ms real-time PCM pacing, real native ASR and Ollama Qwen; not browser/TCP/microphone','memory_scope':'Whole-machine vm_stat/swap samples; background apps can affect values, not isolated model RAM','runs':[],'ready':False}
 output=ROOT/'docs/verification/local-concurrent.json'
 def save():output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
 with tempfile.TemporaryDirectory(prefix='lecture-local-concurrent-') as temp:
  root=Path(temp);pcm=root/'pcm.wav';asyncio.run(command([RUNTIME/'ffmpeg/bin/ffmpeg','-v','error','-nostdin','-y','-i',source,'-ac','1','-ar','48000','-c:a','pcm_s16le',pcm]))
  app=create_app(AppConfig(root/'data',RUNTIME,port=8765));base='http://127.0.0.1:8765'
  with TestClient(app,base_url=base) as client:
   def request(method,path,**kwargs):
    r=client.request(method,path,**kwargs);assert r.is_success,r.text;return r.json()
   login=request('POST','/api/bootstrap',json={'token':app.state.bootstrap_token},headers={'Origin':base});headers={'Origin':base,'X-Session-Token':login['csrf_token']}
   request('POST','/api/local/connect',json={'mode':'managed'},headers=headers)
   request('PUT','/api/settings',json={'provider':'ollama','model':'qwen3.5:4b','context_limit':8192},headers=headers)
   request('POST','/api/models/check',headers=headers)
   for mode in ('standalone','concurrent'):
    sid=request('POST','/api/sessions',json={'kind':'lecture','title':'실제 동시 검증 '+mode},headers=headers)['id']
    request('PUT','/api/sessions/'+sid+'/note',json={'text':'프로세스는 실행 중인 프로그램입니다. 각 프로세스는 독립된 주소 공간을 갖고 스레드는 메모리를 공유합니다.'},headers=headers)
    generation=None;generation_started=None;states=[]
    def generate():return request('POST','/api/ai/jobs',json={'session_id':sid,'kind':'answer','prompt':'프로세스와 스레드의 차이를 근거와 함께 설명하세요.','scope':{'session_id':sid,'mode':'current'}},headers=headers)['id']
    if mode=='standalone':
     generation_started=time.perf_counter();generation=generate()
     while (job:=request('GET','/api/jobs/'+generation))['status'] in ('queued','running'):time.sleep(.05)
     assert job['status']=='done',job
     standalone_generation_seconds=time.perf_counter()-generation_started
    rid=request('POST','/api/sessions/'+sid+'/audio/start',json={'sample_rate':48000,'transcription_mode':'realtime'},headers=headers)['recording_id']
    if mode=='concurrent':generation_started=time.perf_counter();generation=generate()
    samples=[memory()];previews=[];peak_queue=0
    with client.websocket_connect('ws://127.0.0.1:8765/api/sessions/'+sid+'/audio',headers={'Origin':base}) as ws,wave.open(str(pcm)) as original:
     ws.send_json({'recording_id':rid,'sample_rate':48000,'channels':1,'format':'pcm_s16le','csrf_token':login['csrf_token']});assert ws.receive_json()['type']=='ready';clock=time.perf_counter();cursor=seq=0;generation_done=None
     while payload:=original.readframes(12000):
      count=len(payload)//2;time.sleep(max(0,clock+(cursor+count)/48000-time.perf_counter()));ws.send_bytes(struct.pack('<QQI',seq,cursor,count)+payload);ack=ws.receive_json();assert ack['type']=='ack';cursor+=count;seq+=1
      if seq%4==0:
       event=request('GET','/api/sessions/'+sid+'/events');previews.append(sum(not t['final'] for t in event['transcripts']));peak_queue=max(peak_queue,sum(r['transcription']['queued']+r['transcription']['running'] for r in event['recordings']));samples.append(memory())
       job=request('GET','/api/jobs/'+generation);states.append(job['status'])
       if job['status']=='done' and generation_done is None:generation_done=time.perf_counter()-generation_started
     stopped=time.perf_counter();jid=request('POST','/api/recordings/'+rid+'/stop',json={'end_frame':cursor},headers=headers)['id']
     for _ in range(1200):
      job=request('GET','/api/jobs/'+jid)
      if job['status'] not in ('queued','running'):break
      time.sleep(.05)
     assert job['status']=='done',job;post_stop=time.perf_counter()-stopped
    while (job:=request('GET','/api/jobs/'+generation))['status'] in ('queued','running'):time.sleep(.05)
    assert job['status']=='done',job;generation_done=generation_done if mode=='concurrent' and generation_done is not None else time.perf_counter()-generation_started if mode=='concurrent' else standalone_generation_seconds
    artifact=request('GET','/api/artifacts/'+job['result']['id']);assert artifact['metadata']['digest'] and artifact['body']['citations']
    event=request('GET','/api/sessions/'+sid+'/events');record=event['recordings'][0];segments=event['transcripts'];assert record['stored_frames']==cursor and not record['gaps'];assert all(t['final'] and 0<=t['start_ms']<t['end_ms']<=round(fixture['duration_seconds']*1000) for t in segments)
    recognized=' '.join(t['text'] for t in segments);report['runs'].append({'mode':mode,'ack_packets':seq,'frames':cursor,'gaps':record['gaps'],'post_stop_seconds':post_stop,'max_observed_pending_ranges':peak_queue,'provisional_counts':previews,'generation_states':states,'generation_complete_observed_seconds':generation_done,'generation':artifact['metadata'],'answer':artifact['body'],'recognized':recognized,'memory_samples':samples,**score(fixture['reference_raw_transcription'],recognized)});save();print(json.dumps({'mode':mode,'post_stop_seconds':post_stop,'generation_seconds':generation_done}),flush=True)
  app.state.db.close()
 assert file_hash(source)==fixture['sha256'];report['ready']=True;save()
if __name__=='__main__':main()
