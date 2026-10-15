"""Actual local model integration on synthetic records, never private user files."""
import asyncio,json,platform,tempfile,time
from datetime import datetime,timezone
from pathlib import Path
import httpx
from lecture_study.db import open_db,create_session,new_id,now
from lecture_study.local_models import OwnedOllama,installed_models
from lecture_study.models import ProviderConfig,AIRequest,Scope
from lecture_study.providers import model_status
from lecture_study.materials import save_note,register_file,inspect_file,ingest_asset,list_materials
from lecture_study.retrieval import save_term,rebuild_embeddings,retrieve
from lecture_study.answers import freeze_request,run_ai_request,get_artifact
from lecture_study.jobs import submit_job
from lecture_study.outputs import public_artifact,submit_attempt,override_attempt,save_participants,export_markdown,edit_artifact
from lecture_study.audio import start_recording,append_pcm,stop_recording
from lecture_study.transcription import plan_chunks,accept_transcription
from tests.fixtures import pdf_fixture
ROOT=Path(__file__).resolve().parents[1];RUNTIME=ROOT/'.local-state/runtime'
OUTPUT=ROOT/'docs/verification/local-model-integration.json'
async def main():
 report={'tested_at_utc':datetime.now(timezone.utc).isoformat(),'platform':platform.platform(),'input_kind':'Synthetic educational/meeting fixtures; actual local models, no generation doubles','checks':{},'ready':False}
 def save():OUTPUT.write_text(json.dumps(report,ensure_ascii=False,indent=2))
 manager=OwnedOllama(RUNTIME)
 try:
  url=await manager.start();report['models']=await installed_models(url)
  config=ProviderConfig(provider='ollama',model='qwen3.5:4b',vision=True,context_limit=16384)
  report['capabilities']=await model_status(config,ollama_url=url);save()
  with tempfile.TemporaryDirectory(prefix='lecture-real-model-') as folder:
   folder=Path(folder);db=open_db(folder/'data')
   try:
    course=new_id()
    with db:db.execute('INSERT INTO courses VALUES (?,?,?,?)',(course,'운영체제','',now()))
    previous=create_session(db,'lecture','프로세스',course,1).id;current=create_session(db,'lecture','동기화',course,2).id
    unrelated=create_session(db,'lecture','다른 과목',None,None).id
    old=save_note(db,previous,'프로세스는 실행 중인 프로그램이다. 스레드는 같은 프로세스의 주소 공간을 공유한다. '+ '\n\n'.join('복습 '+str(n)+': 스레드는 코드와 힙을 공유하지만 각자 스택을 갖는다.' for n in range(35)))
    current_ref=save_note(db,current,'데드락은 서로 필요한 자원을 보유한 채 무한히 기다리는 교착 상태다. 발생에 필요한 네 조건은 상호 배제, 점유 대기, 비선점, 순환 대기이다. 예방은 이 중 하나가 성립하지 않게 한다. 마지막 주제는 세마포어이며 공유 자원 접근을 조절한다.')
    save_note(db,unrelated,'다른 과목은 교착 상태와 프로세스를 다룬다. 범위에 포함하면 안 된다.')
    save_term(db,current,'데드락',['교착 상태'],'자원 대기로 진행하지 못함',[current_ref])
    async with httpx.AsyncClient(base_url=url,timeout=120,trust_env=False) as client:
     report['checks']['keyword_before']={}
     for query in ('교착 상태','여러 실행 흐름이 메모리를 같이 쓰는 방식'):
      report['checks']['keyword_before'][query]=(await retrieve(db,query,Scope(session_id=current),None)).model_dump()
     began=time.perf_counter();report['checks']['embedding_index']=await rebuild_embeddings(db,'embeddinggemma',client);report['checks']['embedding_index']['elapsed_seconds']=time.perf_counter()-began
     searches={}
     for query,scope in [('별칭',Scope(session_id=current)),('의미',Scope(session_id=current)),('현재만',Scope(session_id=current,mode='current'))]:
      result=await retrieve(db,'교착 상태' if query=='별칭' else '여러 실행 흐름이 메모리를 같이 쓰는 방식',scope,None,client=client)
      assert result.mode=='hybrid' and result.evidence
      assert all(e.ref.session_id in ([current] if query=='현재만' else [previous,current]) for e in result.evidence)
      searches[query]=result.model_dump()
     report['checks']['retrieval']=searches;save()
     async def generate(kind,prompt,sid=current,image_id=None):
      request=AIRequest(session_id=sid,kind=kind,prompt=prompt,scope=Scope(session_id=sid),provider=config.model_copy(update={'context_limit':8192}) if kind=='summary' else config,image_id=image_id)
      frozen=await freeze_request(db,request,client);job=submit_job(db,sid,'ai',frozen);began=time.perf_counter()
      if kind=='summary':
       import lecture_study.outputs as outputs
       real_generate=outputs.generate;calls=0
       async def fail_before_third(*args,**kwargs):
        nonlocal calls
        calls+=1
        if calls==3:raise ValueError('검증용 중간 중단: 실제 호출 전')
        return await real_generate(*args,**kwargs)
       outputs.generate=fail_before_third
       try:
        try:await run_ai_request(db,frozen,job['id'],ollama_url=url,runtime_dir=RUNTIME)
        except ValueError as exc:assert str(exc)=='검증용 중간 중단: 실제 호출 전'
       finally:outputs.generate=real_generate
       completed=db.execute('SELECT count(*) FROM artifact_parts WHERE job_id=?',(job['id'],)).fetchone()[0]
       assert completed==2 and len(frozen['summary_parts'])>2
       report['checks']['summary_resume']={'injected_failure':'before third model call','actual_completed_parts_preserved':completed,'total_parts':len(frozen['summary_parts'])}
      result=await run_ai_request(db,frozen,job['id'],ollama_url=url,runtime_dir=RUNTIME)
      saved=get_artifact(db,result.id);assert saved['metadata']['digest']==report['capabilities']['digest']
      report['checks'][kind+(image_id or '')]={'elapsed_seconds':time.perf_counter()-began,'artifact':saved,'frozen_parts':len(frozen.get('summary_parts',[]))}
      assert (await run_ai_request(db,frozen,job['id'],ollama_url=url,runtime_dir=RUNTIME)).id==result.id
      save();print(json.dumps({'check':kind,'status':'passed','elapsed_seconds':report['checks'][kind+(image_id or '')]['elapsed_seconds']},ensure_ascii=False),flush=True)
      return result
     await generate('answer','이전 수업의 프로세스와 스레드를 비교하고 현재 교착 상태와 연결해 설명해 주세요.')
     summary=await generate('summary','전체 선택 범위를 요약하고 마지막의 세마포어 내용을 포함하세요.')
     assert old.id in summary.body['covered_source_ids'] and current_ref.id in summary.body['covered_source_ids']
     quiz=await generate('quiz','선택 범위로 객관식 3개와 서술형 2개, 총 5개를 만드세요.')
     public=public_artifact(db,quiz.id);assert len(public['body']['questions'])==5
     assert all('answer' not in q and 'explanation' not in q for q in public['body']['questions'])
     attempts=[]
     for q in quiz.body['questions']:
      attempt=await submit_attempt(db,quiz.id,q['id'],q['answer'],provider=config,ollama_url=url)
      assert attempt['status']=='done';attempts.append(attempt)
     revision=override_attempt(db,attempts[0]['id'],'partial','실제 검증용 사용자 수정')
     assert revision['original_grade']==attempts[0]['grade'] and revision['history']
     report['checks']['grading']={'attempts':attempts,'revision':revision};save()
     meeting=create_session(db,'meeting','실제 모델 회의 fixture',None,None).id
     save_participants(db,meeting,['김민수','이서연'])
     rid=start_recording(db,meeting,48000);append_pcm(db,rid,0,0,48000,b'\x00\x01'*48000);stop_recording(db,rid);chunk=plan_chunks(db,rid,True)[0]
     accept_transcription(db,rid,chunk['id'],chunk['revision'],True,[{'start_ms':0,'end_ms':1000,'text':'새 서버는 검토 제안입니다. 기존 서버를 사용하기로 결정했습니다. 김민수는 다음 주 금요일까지 자료를 정리합니다. 일정 조율 담당자는 아직 정하지 않았습니다.'}])
     minutes=await generate('minutes','명확한 결정과 제안, 담당 미정과 원래 날짜 표현을 구분해 회의록을 작성하세요.',meeting)
     report['checks']['minutes_export_before']=export_markdown(db,minutes.id)
     edit_artifact(db,minutes.id,minutes.body,True);assert '사용자 확인됨' in export_markdown(db,minutes.id)
     pdf=folder/'selected.pdf';pdf.write_bytes(pdf_fixture());asset=register_file(db,current,inspect_file(pdf));await ingest_asset(db,asset['id'],RUNTIME)
     parsed=next(a for a in list_materials(db,current)['assets'] if a['id']==asset['id'])['extraction']
     for image_id in (parsed['pages'][2]['ref']['id'],parsed['images'][0]['ref']['id']):
      await generate('vision','실제로 보이는 글자·색과 모양을 설명하고 추측은 구분하세요.',image_id=image_id)
     assert pdf.read_bytes()==pdf_fixture();report['checks']['external_original_untouched']=True
    report['ready']=True;save()
   finally:db.close()
 except Exception as exc:
  report['error']=str(exc);save();raise
 finally:await manager.stop()
 print(json.dumps({'ready':report['ready'],'report':str(OUTPUT)},ensure_ascii=False),flush=True)
if __name__=='__main__':asyncio.run(main())
