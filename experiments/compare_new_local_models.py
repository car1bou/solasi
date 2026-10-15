"""Sequential, local-only diagnostic on authored Korean evidence and cached human clips.

Run only after other inference fixtures have stopped:
.venv/bin/python -m experiments.compare_new_local_models
No model download, default setting change, or external API call.
"""
import argparse,asyncio,base64,json,platform,subprocess,tempfile,time
from datetime import datetime,timezone
from pathlib import Path
import httpx
from lecture_study.local_models import OwnedOllama,installed_models,CATALOG
from lecture_study.models import AIRequest,Scope,ProviderConfig
from lecture_study.db import open_db,create_session
from lecture_study.materials import save_note
from lecture_study.audio import start_recording,append_pcm
from lecture_study.transcription import plan_chunks,accept_transcription,list_transcripts,file_hash,register_audio,process_pending,MODEL_NAME,MODEL_SHA
from lecture_study.answers import freeze_request,run_ai_request,get_artifact
from lecture_study.jobs import submit_job
from lecture_study.merging import merge_generated
from lecture_study.retrieval import embed_parts
from tests.evaluate_human_audio import score,normalize
ROOT=Path(__file__).resolve().parents[1];RUNTIME=ROOT/'.local-state/runtime';OUTPUT=ROOT/'docs/verification/new-local-models.json'
DOCS=[('프로세스','실행 중인 프로그램이며 독립된 가상 주소 공간을 갖는다.'),('스레드','같은 프로세스의 코드와 힙을 공유하지만 스택과 레지스터는 각자 갖는다.'),('뮤텍스','상호 배제로 한 실행 흐름만 임계 구역에 들어간다. 락을 획득한 소유자가 해제한다.'),('세마포어','카운터를 사용해 여러 자원의 동시 접근 개수를 제한한다.'),('교착 상태','상호 배제, 점유 대기, 비선점, 순환 대기 네 조건이 모두 필요하다.'),('기아','우선순위가 낮아 자원을 무한히 기다린다. 에이징으로 완화한다.'),('가상 메모리','페이지 테이블로 가상 주소를 물리 주소에 대응한다. 없는 페이지 접근은 페이지 폴트를 일으킨다.'),('캐시','자주 쓰는 데이터를 가까이 둬 접근 시간을 줄이며 지역성을 활용한다.'),('데이터베이스 트랜잭션','원자성, 일관성, 고립성, 지속성 ACID를 따른다.'),('검색 증강 생성','자료를 먼저 검색한 다음 그 근거를 언어 모델에 제공해 답변한다.'),('녹음 복구','수집이 중단되면 받은 원음을 보존하고 새 녹음 구간으로 복구한다.'),('미결 일정','금요일 네 개는 제안이다. 월요일 세 개로 정정했지만 아직 확정하지 않았다.')]
QUERIES=[('메모리를 같이 쓰지만 호출 스택은 따로 갖는 실행 단위',1),('동시에 세 명까지만 자원에 접근하게 하는 카운터',3),('낮은 우선순위 작업이 계속 기다리는 현상과 완화 방법',5),('여러 작업이 자원을 붙잡고 서로 기다려 멈추는 네 조건',4),('임계 영역에는 하나만 들어가고 잡은 쪽이 풀어야 하는 잠금',2),('하던 작업의 가상 주소가 실제 메모리에 없으면?',6),('실행되는 프로그램마다 별도의 주소 영역',0),('데이터를 가까이 두어 읽는 속도를 높이는 원리',7),('작업을 전부 적용하거나 전부 취소하는 데이터 저장 단위',8),('답하기 전에 외부 지식을 찾아 근거를 제공하는 방법',9),('입력이 끊겼을 때 받은 소리를 지키는 동작',10),('정정된 일정이 결정까지 됐는지',11)]

def check_whisper_status(status):
 if any(status.get(key,0) for key in ('failed','interrupted','cancelled','queued','running')):raise ValueError('Whisper 처리 미완료: '+json.dumps(status))

def host_memory():return {'swapusage':subprocess.check_output(['sysctl','vm.swapusage'],text=True).strip(),'vm_stat':subprocess.check_output(['vm_stat'],text=True)}
async def main(models=('qwen3.5:4b','gemma4:e2b'),output=OUTPUT,embeddings=True,repeats=1,prepared=None,audio_manifest=None,audio_only=False):
 report={'completed':False,'tested_at_utc':datetime.now(timezone.utc).isoformat(),'platform':platform.platform(),'conditions':'Sequential models, no other task inference; authored Korean mini-set, cached public human read speech; native audio API, 8192 context, temperature0/seed42; not representative benchmark','audio_repeats':repeats,'generation_included':not audio_only,'audio_manifest':json.loads(audio_manifest.read_text()) if audio_manifest else None,'embeddings':[],'generation':[],'audio':[],'memory_before':host_memory()}
 if audio_only:
  assert all('gemma4' in name for name in models)
  report['conditions']='Sequential local Gemma native audio and product Whisper, fixed supplied human speech/noise manifest, no other task inference; 8192 context, temperature0/seed42; small diagnostic, not representative benchmark'
 def save():output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
 manager=OwnedOllama(RUNTIME)
 try:
  url=await manager.start();report['installed']=await installed_models(url)
  for name in (*models,*(('embeddinggemma','embeddinggemma-2:270m-mxfp8-text') if embeddings else ())):
   digests=[r['digest'] for r in CATALOG[name]['runners'].values()] if name in CATALOG else [prepared['digest']] if prepared and prepared['model']==name else []
   assert any(m['name'] in (name,name+':latest') and m['digest'] in digests for m in report['installed']['models']),name
  async with httpx.AsyncClient(base_url=url,timeout=300,trust_env=False) as client:
   async def unload(name):
    endpoint='/api/embed' if name.startswith('embedding') else '/api/generate'
    payload={'model':name,'keep_alive':0}
    if name.startswith('embedding'):payload['input']=[]
    response=await client.post(endpoint,json=payload);response.raise_for_status()
    for _ in range(50):
     state=await client.get('/api/ps');state.raise_for_status()
     if not state.json().get('models'):return
     await asyncio.sleep(.1)
    raise ValueError('비교 모델이 메모리에서 해제되지 않았습니다')
   for name in (('embeddinggemma','embeddinggemma-2:270m-mxfp8-text') if embeddings else ()):
    row={'model':name,'documents':DOCS,'queries':[],'memory_before':host_memory()};report['embeddings'].append(row)
    began=time.perf_counter();vectors=[(await embed_parts(client,name,text,title))[0] for title,text in DOCS];row['document_seconds']=time.perf_counter()-began;row['dimension']=len(vectors[0])
    for query,target in QUERIES:
     began=time.perf_counter();vec=(await embed_parts(client,name,query,query=True))[0];ranking=sorted(range(len(DOCS)),key=lambda i:-sum(a*b for a,b in zip(vec,vectors[i])));rank=ranking.index(target)+1
     row['queries'].append({'query':query,'gold_document':target,'ranking':ranking,'rank':rank,'seconds':time.perf_counter()-began})
    row['recall_at_1']=sum(q['rank']==1 for q in row['queries'])/len(QUERIES);row['recall_at_3']=sum(q['rank']<=3 for q in row['queries'])/len(QUERIES);row['mrr']=sum(1/q['rank'] for q in row['queries'])/len(QUERIES);row['memory_after']=host_memory();await unload(name);save();print('embedding done '+name,flush=True)
   with tempfile.TemporaryDirectory(prefix='lecture-new-models-') as folder:
    db=open_db(Path(folder)/'data')
    try:
     sid=create_session(db,'lecture','운영체제와 일정 정정',None,None).id;rid=start_recording(db,sid,48000);append_pcm(db,rid,0,0,48000,b'\0\1'*48000);chunk=plan_chunks(db,rid,True)[0]
     text='뮤텍스와 세마포어는 어떻게 다른가요? 뮤텍스는 하나만 임계 구역에 들어가게 하고 세마포어는 카운터로 접근 개수를 제한합니다. 금요일 네 개는 제안입니다. 월요일 세 개로 정정했지만 아직 확정하지 않았습니다.'
     accept_transcription(db,rid,chunk['id'],chunk['revision'],True,[{'start_ms':0,'end_ms':1000,'text':text}]);tid=list_transcripts(db,sid)[0]['id']+':v1';note=save_note(db,sid,'뮤텍스와 세마포어 차이, 일정 다시 확인',anchor_ms=500)
     for name in (() if audio_only else models):
      config=ProviderConfig(provider='ollama',model=name,context_limit=16384)
      for kind in ('note','candidates','summary'):
       row={'model':name,'kind':kind,'memory_before':host_memory()};report['generation'].append(row);began=time.perf_counter();job=None
       try:
        request=AIRequest(session_id=sid,kind=kind,prompt='확정 전사에 근거해 작성하고 정정·제안·미확정을 보존하세요.',scope=Scope(session_id=sid,mode='current'),provider=config,note_source_id=note.id if kind=='note' else None)
        frozen=await freeze_request(db,request);job=submit_job(db,sid,'ai',frozen)
        if kind=='summary':
         pieces=[{'sections':[{'title':'초기 제안','text':'금요일 네 개를 제안했다.','evidence_ids':[tid]}]},{'sections':[{'title':'후반 정정','text':'월요일 세 개로 정정했다. 아직 확정하지 않았다.','evidence_ids':[tid]}]}]
         body,infos=await merge_generated(db,frozen,job['id'],pieces,'summary',ollama_url=url);row.update(body=body,metadata=infos)
        else:
         result=await run_ai_request(db,frozen,job['id'],ollama_url=url);saved=get_artifact(db,result.id);row.update(body=saved['body'],metadata=saved['metadata'])
        row['validated']=True
       except Exception as exc:row['validated']=False;row['error']=str(exc)
       finally:
        row['seconds']=time.perf_counter()-began;row['memory_after']=host_memory()
        if job:
         with db:db.execute("UPDATE jobs SET status=? WHERE id=?",('done' if row['validated'] else 'failed',job['id']))
        save();print(json.dumps({'model':name,'kind':kind,'validated':row['validated'],'seconds':row['seconds']}),flush=True)
      await unload(name)
     if audio_manifest:
      source_manifest=json.loads(audio_manifest.read_text());assert source_manifest['ready'];rows=source_manifest['clips']
     else:
      rows=[]
      for manifest in ('human-audio-20261013/provenance.json','asr-comparison-20261013/manifest.json'):
       rows += [r for r in json.loads((RUNTIME/manifest).read_text())['clips'] if r['row_idx'] in (3,8,12,19,26,9,10,11,13,14)]
      assert len(rows)==10
     assert rows and all(0<c['duration_seconds']<=30 and normalize(c['reference_raw_transcription']) for c in rows)
     for name in (*[m for m in models if 'gemma4' in m],'whisper-large-v3-turbo'):
      for trial,clip in ((trial,clip) for trial in range(1,repeats+1) for clip in rows):
       source=Path(clip['path']);assert file_hash(source)==clip['sha256'];row={'model':name,'trial':trial,'row_idx':clip['row_idx'],'group':clip.get('group','fleurs-names-controls'),'sha256':clip['sha256'],'reference':clip['reference_raw_transcription'],'audio_seconds':clip['duration_seconds'],'hints':False};report['audio'].append(row);began=time.perf_counter()
       try:
        if 'gemma4' in name:
         wav=Path(folder)/'clip.wav';subprocess.run([str(RUNTIME/'ffmpeg/bin/ffmpeg'),'-v','error','-nostdin','-y','-i',str(source),'-ar','16000','-ac','1',str(wav)],check=True)
         payload={'model':name,'messages':[{'role':'user','content':'오디오를 한국어로 정확히 전사하세요. 들린 내용만 출력하세요.','images':[base64.b64encode(wav.read_bytes()).decode()]}],'think':False,'options':{'temperature':0,'seed':42,'num_ctx':8192,'num_predict':1024},'stream':False}
         response=await client.post('/api/chat',json=payload,timeout=180);row['http_status']=response.status_code
         if response.is_error:row['engine_error']=response.text[:500]
         response.raise_for_status();body=response.json();recognized=body.get('message',{}).get('content');row['usage']={k:body.get(k) for k in ('prompt_eval_count','eval_count','load_duration','prompt_eval_duration','eval_duration')};row['finish_reason']=body.get('done_reason')
         if not body.get('done') or row['finish_reason'] in ('length','error') or not isinstance(recognized,str) or not recognized.strip():
          row['partial_response']=recognized;raise ValueError('음성 응답이 완결되지 않았습니다')
        else:
         test_sid=create_session(db,'lecture','동일 음성 ASR 진단',None,None).id;test_rid=await register_audio(db,test_sid,source,RUNTIME);row['status']=await process_pending(db,test_rid,RUNTIME);check_whisper_status(row['status']);recognized=' '.join(t['text'] for t in list_transcripts(db,test_sid));row['digest']=MODEL_SHA
        row.update(recognized=recognized,**score(row['reference'],recognized));row['expected_terms']=[t for t in ('세풀베다','깁슨','내셔널 트레저','북발트해','카탈로니아어','TMZ') if normalize(t) in normalize(row['reference'])];row['correct_terms']=[t for t in row['expected_terms'] if normalize(t) in normalize(recognized)]
       except Exception as exc:row['error']=str(exc)
       row['seconds']=time.perf_counter()-began;save();print(json.dumps({'model':name,'row':row['row_idx'],'seconds':row['seconds'],'cer':row.get('cer'),'error':row.get('error')},ensure_ascii=False),flush=True)
      if 'gemma4' in name:await unload(name)
    finally:db.close()
  report['completed']=True;report['memory_after']=host_memory();save()
 finally:await manager.stop()
if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--models',nargs='+',default=['qwen3.5:4b','gemma4:e2b']);parser.add_argument('--output',type=Path,default=OUTPUT);parser.add_argument('--no-embeddings',action='store_true');parser.add_argument('--repeats',type=int,choices=[1,2],default=1);parser.add_argument('--prepared',type=Path);parser.add_argument('--audio-manifest',type=Path);parser.add_argument('--audio-only',action='store_true');args=parser.parse_args()
 asyncio.run(main(args.models,args.output,not (args.no_embeddings or args.audio_only),args.repeats,json.loads(args.prepared.read_text()) if args.prepared else None,args.audio_manifest,args.audio_only))
