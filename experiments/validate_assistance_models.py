"""Real local memo/cards/full summary with duplicate facts, late correction and resume.

Authored records only; sequential models, no API or ASR quality claim.
Run: .venv/bin/python -m experiments.validate_assistance_models
"""
import argparse,asyncio,json,tempfile,time
from pathlib import Path
from unittest.mock import patch
import httpx
from lecture_study import outputs
from lecture_study.local_models import OwnedOllama
from lecture_study.db import open_db,create_session
from lecture_study.audio import start_recording,append_pcm
from lecture_study.transcription import plan_chunks,accept_transcription
from lecture_study.materials import save_note,list_materials
from lecture_study.models import AIRequest,Scope,ProviderConfig
from lecture_study.answers import freeze_request,run_ai_request,get_artifact
from lecture_study.jobs import submit_job
from lecture_study.assistance import apply_note
ROOT=Path(__file__).resolve().parents[1];RUNTIME=ROOT/'.local-state/runtime';OUTPUT=ROOT/'docs/verification/assistance-local-models.json'
TEXTS=['금요일 장비 네 대를 설치하자는 제안입니다. 아직 확정하지 않았습니다.','다시 말씀드리면 금요일 네 대 설치안은 제안이며 최종 결정이 아닙니다.','뮤텍스와 세마포어는 어떻게 다른가요? 뮤텍스는 한 실행 흐름만 임계 구역에 들어가게 하고 세마포어는 카운터로 동시 접근 개수를 제한합니다.','정정합니다. 장비 일정은 월요일 세 대로 바꿔 검토합니다. 아직 확정하지 않았으며 담당자도 정하지 않았습니다.']
async def main(models=('qwen3.5:4b','gemma4:e2b'),output=OUTPUT,kinds=('note','candidates','summary')):
 report={'completed':False,'conditions':'Authored text in production DB and jobs, actual local models, identical text per model, no other task inference; one trial, not semantic quality benchmark','transcript_inputs':TEXTS,'models':[]}
 def save():output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
 manager=OwnedOllama(RUNTIME)
 try:
  url=await manager.start()
  for name in models:
   with tempfile.TemporaryDirectory(prefix='assistance-real-') as folder:
    db=open_db(Path(folder)/'data');row={'model':name,'checks':[]};report['models'].append(row)
    try:
     sid=create_session(db,'lecture','동기화와 장비 일정',None,None).id;rid=start_recording(db,sid,48000)
     for n in range(20):append_pcm(db,rid,n,n*48000,48000,b'\0\1'*48000)
     chunk=plan_chunks(db,rid,True)[0];accept_transcription(db,rid,chunk['id'],chunk['revision'],True,[{'start_ms':i*5000,'end_ms':(i+1)*5000,'text':text} for i,text in enumerate(TEXTS)])
     note=save_note(db,sid,'뮤텍스·세마포어 차이와 장비 일정 다시 확인',anchor_ms=10000);proposal=None
     for kind in kinds:
      check={'kind':kind};row['checks'].append(check);began=time.perf_counter();job=None
      try:
       request=AIRequest(session_id=sid,kind=kind,prompt='확정 전사로 작성하고 반복을 줄이되 후반 정정·제안·미확정·담당 미정을 보존하세요.',scope=Scope(session_id=sid,mode='current'),provider=ProviderConfig(provider='ollama',model=name,context_limit=16384),note_source_id=note.id if kind=='note' else None)
       frozen=await freeze_request(db,request)
       job=submit_job(db,sid,'ai',frozen)
       if kind=='summary':
        original=outputs.generate;calls=0
        async def fail_once(*args,**kwargs):
         nonlocal calls
         calls+=1
         if calls==3:raise ValueError('fixture failure before third provider request')
         return await original(*args,**kwargs)
        with patch('lecture_study.outputs.generate',new=fail_once):
         try:await run_ai_request(db,frozen,job['id'],ollama_url=url)
         except ValueError as exc:assert str(exc)=='fixture failure before third provider request',str(exc)
        completed=db.execute('SELECT count(*) FROM artifact_parts WHERE job_id=? AND part_no>=0',(job['id'],)).fetchone()[0];assert completed==2
        check['cached_before_retry']=completed;check['source_parts']=len(frozen['summary_parts'])
       result=await run_ai_request(db,frozen,job['id'],ollama_url=url);saved=get_artifact(db,result.id);check.update(validated=True,artifact=saved)
       if kind=='note':proposal=result.id
       if kind=='summary':assert saved['body']['merged'] and saved['body']['completed_parts']==5
      except Exception as exc:check.update(validated=False,error=str(exc))
      finally:
       check['seconds']=time.perf_counter()-began
       if job:
        with db:db.execute('UPDATE jobs SET status=? WHERE id=?',('done' if check['validated'] else 'failed',job['id']))
       save();print(json.dumps({'model':name,'kind':kind,'validated':check['validated'],'seconds':check['seconds'],'error':check.get('error')},ensure_ascii=False),flush=True)
     if proposal:
      accepted=get_artifact(db,proposal)['body']['addition'];applied=apply_note(db,proposal,accepted)
      assert applied['version']==2 and db.execute('SELECT text FROM notes WHERE version=1').fetchone()[0]=='뮤텍스·세마포어 차이와 장비 일정 다시 확인'
      row['actual_proposal_apply']={'original_version_preserved':True,'note':applied}
    finally:db.close()
   async with httpx.AsyncClient(base_url=url,timeout=30,trust_env=False) as client:
    response=await client.post('/api/generate',json={'model':name,'keep_alive':0});response.raise_for_status()
    for _ in range(50):
     state=await client.get('/api/ps');state.raise_for_status()
     if not state.json()['models']:break
     await asyncio.sleep(.1)
    else:raise ValueError('model did not unload')
  report['completed']=True;save()
 finally:await manager.stop()
if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--models',nargs='+',default=['qwen3.5:4b','gemma4:e2b']);parser.add_argument('--output',type=Path,default=OUTPUT);parser.add_argument('--kinds',nargs='+',choices=['note','candidates','summary'],default=['note','candidates','summary']);args=parser.parse_args();asyncio.run(main(args.models,args.output,args.kinds))
