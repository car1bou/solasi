"""Compare post-recording assistance on the same frozen real transcript, in a disposable DB copy."""
import argparse,asyncio,json,sqlite3,tempfile,time
from pathlib import Path
from unittest.mock import patch
from lecture_study import outputs
import httpx
from lecture_study.local_models import OwnedOllama
from lecture_study.db import open_db
from lecture_study.materials import save_note
from lecture_study.models import AIRequest,Scope,ProviderConfig
from lecture_study.answers import capture_request,freeze_request,run_ai_request,get_artifact
from lecture_study.retrieval import capture_search
from lecture_study.jobs import submit_job
from lecture_study.assistance import apply_note
ROOT=Path(__file__).resolve().parents[1];RUNTIME=ROOT/'.local-state/runtime'
def assert_same_summary_request(old,frozen):
 for key in ('request','evidence','summary_parts','summary_instruction','summary_grounding','summary_mode','summary_subject','summary_output_limit','summary_tokenizer','source_sampling','cutoff_ms'):assert old['frozen_request'].get(key)==frozen.get(key),key

def completed_grounded_parts(old,frozen):
 from lecture_study.models import Evidence
 from lecture_study.summary_grounding import grounded_units,ground_sections
 from lecture_study.merging import remap_ids
 assert old['validated'] and frozen['summary_grounding']=='quotes-v1'
 assert_same_summary_request(old,frozen)
 aliases={e['ref']['id']:'s'+str(n+1)for n,e in enumerate(frozen['evidence'])};cached=[]
 for n,provided in enumerate(frozen['summary_parts']):
  part=[Evidence.model_validate(e)for e in provided];compact,restore=grounded_units(part,aliases);info=old['artifact']['metadata']['part_metadata'][n]
  assert info['source_aliases']==restore
  body=remap_ids(ground_sections(info['unreviewed_body'],compact,frozen['summary_mode'],copy_subject=frozen.get('summary_subject')=='quote-v1'),restore)
  for section in body['sections']:section['evidence_ids']=list(dict.fromkeys(section['evidence_ids']))
  body=outputs.clean_summary_citations(body,part);cached.append({'part_no':n,'body':body,'metadata':info})
 assert [section for p in cached for section in p['body']['sections']]==old['artifact']['body']['part_sections'],'Map postprocessing changed; a fresh map run is required'
 return cached

async def main(folder,model,output,cutoff,kinds,reuse_parts=None,context_limit=16384):
 trace=json.loads((folder/'trace.json').read_text());assert trace['ready'],'Recording fixture must finish before assistance comparison'
 sid=json.loads((folder/'info.json').read_text())['session_id']
 report={'completed':False,'model':model,'context_limit':context_limit,'input':trace['input'],'source_folder':str(folder),'requested_cutoff_ms':cutoff,'conditions':'Same frozen actual Whisper transcript plus the identical authored procedural memo in cloned DB, recording ended, no concurrent ASR; '+('summary through '+str(cutoff)+'ms' if cutoff else 'summary of entire recording')+'; memo uses production anchor neighborhood; input type: '+trace['input']['input_type'],'checks':[]}
 def save():output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
 manager=OwnedOllama(RUNTIME)
 try:
  url=await manager.start()
  with tempfile.TemporaryDirectory(prefix='post-recording-quality-') as temp:
   target=Path(temp)/'app.sqlite3'
   with sqlite3.connect(folder/'data/app.sqlite3') as source,sqlite3.connect(target) as copied:source.backup(copied)
   db=open_db(Path(temp))
   try:
    assert not db.execute("SELECT 1 FROM transcript_ranges WHERE final=1 AND status IN ('queued','running')").fetchone()
    note_text='인터뷰 답변의 핵심 설명과 정정 내용을 정리하고 원문과 대조한다.' if 'conversation' in trace['input']['input_type'] else '도입부의 인물과 상황을 정리하고 원문과 대조한다.'
    note=save_note(db,sid,note_text,anchor_ms=60000)
    for kind in kinds:
     row={'kind':kind};report['checks'].append(row);began=time.perf_counter();job=None
     try:
      request=AIRequest(session_id=sid,kind=kind,prompt='제공한 원문의 핵심 내용을 한국어로 정리하세요. 인물·사건·숫자를 보존하고 근거에 없는 사실을 추가하지 마세요.',scope=Scope(session_id=sid,mode='current'),provider=ProviderConfig(provider='ollama',model=model,context_limit=context_limit),note_source_id=note.id if kind=='note' else None)
      snapshot=capture_request(db,request)
      if cutoff:snapshot.update(cutoff_ms=cutoff,search=capture_search(db,request.scope,cutoff))
      frozen=await freeze_request(db,request,snapshot=snapshot,runtime_dir=RUNTIME);job=submit_job(db,sid,'ai',frozen)
      row['frozen_evidence']=frozen['evidence'];row['cutoff_ms']=frozen['cutoff_ms'];row['frozen_request']=frozen
      if reuse_parts:
       prior=json.loads(reuse_parts.read_text());assert kinds==['summary'] and prior['model']==model and prior['source_folder']==str(folder)
       old=next(c for c in prior['checks'] if c['kind']=='summary');assert old['frozen_evidence']==frozen['evidence'] and old['cutoff_ms']==frozen['cutoff_ms']
       cached=completed_grounded_parts(old,frozen);assert len(cached)==len(frozen['summary_parts'])
       with db:
        for part in cached:db.execute('INSERT INTO artifact_parts VALUES (?,?,?,?)',(job['id'],part['part_no'],json.dumps(part['body'],ensure_ascii=False),json.dumps(part['metadata'],ensure_ascii=False)))
       row.update(reused_part_count=len(cached),reuse_parts_from=str(reuse_parts),reuse_limit='Replayed exact real native map outputs after matching the frozen request/evidence/parts/instruction/tokenizer/sampling/mode/cutoff and recomputing identical current map postprocessing; only final reduction is rerun, not fresh ASR or full-pipeline wall-time')
      if cutoff:assert all(e['ref']['kind']!='transcript' or e['ref']['end_ms']<=cutoff for e in frozen['evidence'])
      original_generate=outputs.generate
      async def traced_generate(*args,**kwargs):
       result=await original_generate(*args,**kwargs);data=next(json.loads(m['content'])for m in args[1]if m['role']=='user' and m['content'].startswith('{'))
       row.setdefault('provider_calls',[]).append({'phase':'select' if 'candidates'in data else 'merge' if 'chronological_parts' in data else kind,'input_source_ids':[e['source_id'] for e in data.get('evidence',[])],'response':result.model_dump()});save();return result
      with patch('lecture_study.outputs.generate',new=traced_generate),patch('lecture_study.assistance.generate',new=traced_generate):result=await run_ai_request(db,frozen,job['id'],ollama_url=url)
      row.update(validated=True,artifact=get_artifact(db,result.id))
      if kind=='note':row['applied_version']=apply_note(db,result.id,row['artifact']['body']['addition'])['version'];assert row['applied_version']==note.version+1
     except Exception as exc:
      row.update(validated=False,error=str(exc));row['saved_parts_on_failure']=[{'part_no':r['part_no'],'body':json.loads(r['body']),'metadata':json.loads(r['metadata'])} for r in db.execute('SELECT * FROM artifact_parts WHERE job_id=? ORDER BY part_no',(job['id'],))] if job is not None else []
     finally:row['seconds']=time.perf_counter()-began;save();print(json.dumps({'model':model,**{k:v for k,v in row.items() if k in ('kind','validated','error','seconds')}},ensure_ascii=False),flush=True)
   finally:db.close()
  async with httpx.AsyncClient(base_url=url,timeout=30,trust_env=False) as client:
   r=await client.post('/api/generate',json={'model':model,'keep_alive':0});r.raise_for_status()
   for _ in range(50):
    r=await client.get('/api/ps');r.raise_for_status()
    if not r.json()['models']:break
    await asyncio.sleep(.1)
   else:raise ValueError('Model did not unload')
  report['completed']=True;save()
 finally:await manager.stop()
if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('folder',type=Path);parser.add_argument('model');parser.add_argument('--output',type=Path,required=True);parser.add_argument('--cutoff-ms',type=int,default=120000);parser.add_argument('--kinds',nargs='+',choices=['summary','note'],default=['summary','note']);parser.add_argument('--reuse-parts',type=Path);parser.add_argument('--context-limit',type=int,default=16384);args=parser.parse_args();assert not args.output.exists();assert args.cutoff_ms>=0;asyncio.run(main(args.folder,args.model,args.output,args.cutoff_ms,args.kinds,args.reuse_parts,args.context_limit))
