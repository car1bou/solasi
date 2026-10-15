"""Authored content controls, separate from acoustic benchmark and natural-conversation claims."""
import argparse,asyncio,json,tempfile,time,re
from unittest.mock import patch
from lecture_study import outputs
from pathlib import Path
from lecture_study import audio,transcription as tr
from lecture_study.db import open_db,create_session
from lecture_study.models import AIRequest,Scope,ProviderConfig
from lecture_study.answers import freeze_request,run_ai_request,get_artifact
from lecture_study.jobs import submit_job
from lecture_study.local_models import OwnedOllama
from lecture_study.outputs import save_participants
import httpx
ROOT=Path(__file__).resolve().parents[1]
TEXTS=['예산 120만원은 제안이며 승인하지 않았습니다.','김민수는 담당자 후보이나 담당을 확정하지 않았습니다.','금요일 4대 배치안을 검토했습니다.','금요일 4대 배치안은 취소했습니다. 월요일 3대 배치안으로 정정했으나 이 역시 미확정입니다.','외부로 자료를 전송하지 않습니다. 로컬 처리 조건을 충족할 때만 진행합니다.','장비 계약과 담당자는 미결입니다. 계약하지 않았습니다.','이서연이 검증 자료를 정리하기로 확정했습니다. 이서연은 2026-10-19까지 검증 자료를 정리합니다.']
LECTURE_TEXTS=['마찰이 없다고 가정하면 이 모형에서 역학적 에너지가 보존됩니다. 실제 장치에 마찰이 없다고 단정하는 뜻은 아닙니다.','입력이 0일 때만 예외 처리를 실행합니다. 입력이 1일 때에는 이 규칙을 적용하지 않습니다.','행렬 A에 2를 대입해 계산해 봅시다. 이는 계산 과정을 설명하기 위한 예시입니다.']
async def main(model,output):
    manager=OwnedOllama(ROOT/'.local-state/runtime');report={'completed':False,'model':model,'condition':'Authored grounded transcript content controls, no acoustic accuracy claim; same input for general summary and minutes; authored clauses placed across two chronological parts to test late correction merging, no concurrent ASR','input':TEXTS,'additional_lecture_controls':LECTURE_TEXTS,'results':[]}
    try:
        url=await manager.start()
        with tempfile.TemporaryDirectory(prefix='summary-content-')as temp:
            db=open_db(Path(temp))
            try:
                for kind in ('summary','minutes'):
                    texts=TEXTS+LECTURE_TEXTS if kind=='summary' else TEXTS
                    sid=create_session(db,'lecture'if kind=='summary'else'meeting','내용 보존 대조',None,None).id
                    rid=audio.start_recording(db,sid,16000)
                    for seq in range((len(texts)+1)*30):audio.append_pcm(db,rid,seq,seq*16000,16000,b'\0\1'*16000)
                    audio.stop_recording(db,rid);chunks=tr.plan_chunks(db,rid,True);assert len(chunks)==len(texts)+1
                    for index,chunk in enumerate(chunks):
                        n=index if index<3 else index-1
                        segments=[] if index==3 else [{'start_ms':0,'end_ms':4000,'text':texts[n]}]
                        assert tr.accept_transcription(db,rid,chunk['id'],chunk['revision'],True,segments)
                    if kind=='minutes':save_participants(db,sid,['김민수','이서연'])
                    request=AIRequest(session_id=sid,kind=kind,prompt='숫자·후반 정정·취소·부정·조건·미결을 보존하며 간결하게 정리하세요.',scope=Scope(session_id=sid,mode='current'),provider=ProviderConfig(model=model,context_limit=16384))
                    frozen=await freeze_request(db,request,runtime_dir=ROOT/'.local-state/runtime');job=submit_job(db,sid,'ai',frozen);row={'kind':kind,'input':texts,'parts':len(frozen['summary_parts'])};assert row['parts']>=2;report['results'].append(row);began=time.perf_counter()
                    try:
                        original_generate=outputs.generate
                        async def traced_generate(*args,**kwargs):
                            result=await original_generate(*args,**kwargs);row.setdefault('provider_calls',[]).append(result.model_dump());return result
                        with patch('lecture_study.outputs.generate',new=traced_generate):artifact=await run_ai_request(db,frozen,job['id'],ollama_url=url)
                        saved=get_artifact(db,artifact.id);serialized=' '.join(item['text'] for key in (('sections',) if kind=='summary' else ('topics','decisions','unresolved','actions')) for item in saved['body'][key])
                        checks={'budget120':bool(re.search(r'120\s*만',serialized)),'correction3_vs4':bool(re.search(r'(?:3|세)\s*대',serialized) and re.search(r'(?:4|네)\s*대',serialized)) and all(x in serialized for x in ('월요일','금요일','취소')),'not_confirmed':any(x in serialized for x in ('미확정','확정되지','미정','아직')),'no_contract':('계약' in serialized and any(x in serialized for x in ('않','미결','미체결'))),'local_condition':all(x in serialized for x in ('로컬','조건','외부'))}
                        if kind=='summary':checks.update(clear_lecture_assumption=any(s.get('event_type')in ('condition','hypothesis') and not s.get('review_required') and '마찰'in s['text']for s in saved['body']['sections']),clear_lecture_example=any(s.get('event_type')=='example' and not s.get('review_required') and '행렬'in s['text']for s in saved['body']['sections']))
                        if kind=='minutes':checks.update(owner_is_seoyeon=any(a['participant_name']=='이서연'and a['due_date']=='2026-10-19'for a in saved['body']['actions']),minsu_not_assigned=not any(a['participant_name']=='김민수'for a in saved['body']['actions']))
                        row.update(validated=True,artifact=saved,content_checks=checks,all_checks=all(checks.values()),check_limit='Lexical guards plus explicit structured owner/due checks; inspect text for semantic fidelity, not an automatic semantic completeness proof')
                    except Exception as exc:row.update(validated=False,error=str(exc))
                    finally:row['seconds']=time.perf_counter()-began;output.write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in row.items()if k not in ('artifact','provider_calls')},ensure_ascii=False),flush=True)
            finally:db.close()
        async with httpx.AsyncClient(base_url=url,timeout=30,trust_env=False)as client:(await client.post('/api/generate',json={'model':model,'keep_alive':0})).raise_for_status()
        report['completed']=True
    finally:await manager.stop();output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('model');parser.add_argument('--output',required=True,type=Path);args=parser.parse_args();assert not args.output.exists();assert len(TEXTS)==7;asyncio.run(main(args.model,args.output))
