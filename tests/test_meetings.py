import json
import unittest
from unittest.mock import AsyncMock,patch
from tests import test_answers
from lecture_study.db import create_session
from lecture_study.materials import save_note
from lecture_study.models import AIRequest,Scope,ProviderResult
from lecture_study.answers import freeze_request,get_artifact
from lecture_study.jobs import submit_job
from lecture_study.outputs import create_minutes,save_participants,edit_artifact,export_markdown

class MeetingTests(unittest.IsolatedAsyncioTestCase):
    setUp=test_answers.AnswerTests.setUp
    async def test_proposal_not_decision_missing_owner_is_unassigned(self):
        sid=create_session(self.db,'meeting','설계 회의',None,None).id
        from lecture_study.audio import start_recording,append_pcm
        from lecture_study.transcription import plan_chunks,accept_transcription,list_transcripts
        from lecture_study.models import SourceRef
        rid=start_recording(self.db,sid,48000);append_pcm(self.db,rid,0,0,48000,b'\x00\x01'*48000)
        chunk=plan_chunks(self.db,rid,True)[0]
        accept_transcription(self.db,rid,chunk['id'],chunk['revision'],True,[{'start_ms':0,'end_ms':1000,'text':'새 서버는 검토 제안입니다. 기존 서버를 사용하기로 결정했습니다. 김민수는 다음 주 금요일까지 자료를 정리합니다. 담당자를 정하지 않은 것은 일정 조율입니다.'}])
        source=list_transcripts(self.db,sid)[0]['id']+':v1';ref=SourceRef.model_validate_json(self.db.execute('SELECT ref FROM sources WHERE id=?',(source,)).fetchone()[0])
        participants=save_participants(self.db,sid,['김민수','이서연']);owner=participants[0]['id']
        self.assertEqual(save_participants(self.db,sid,['김민수','이서연'])[0]['id'],owner)
        request=AIRequest(session_id=sid,kind='minutes',prompt='회의록 작성',scope=Scope(session_id=sid),provider=self.request.provider)
        frozen=await freeze_request(self.db,request);self.assertEqual(frozen['source_sampling'],'copy-v1');self.assertIn('분류할 내용이 없는 배열',frozen['minutes_instruction']);job=submit_job(self.db,sid,'ai',frozen)
        body={'topics':[{'title':'서버','text':'서버 선택 논의','evidence_ids':[ref.id]}],
              'decisions':[{'text':'기존 서버 사용','quote':'기존 서버를 사용하기로 결정했습니다.','evidence_ids':[ref.id]}],
              'unresolved':[{'title':'제안','text':'새 서버 검토','evidence_ids':[ref.id]}],
              'actions':[{'text':'일정 조율','participant_id':None,'owner_quote':None,'due_date':None,'due_expression':None,'evidence_ids':[ref.id]},
                         {'text':'자료 정리','participant_id':owner,'owner_quote':'김민수는 다음 주 금요일까지 자료를 정리합니다.','due_date':None,'due_expression':'다음 주 금요일','evidence_ids':[ref.id]}]}
        async def create(data):
            with patch('lecture_study.outputs.generate',new=AsyncMock(return_value=ProviderResult(text=json.dumps(data),model='test',usage={},elapsed_ms=1)))as generated:
                result=await create_minutes(self.db,frozen,job['id']);self.assertTrue(generated.call_args.kwargs['source_copy']);self.assertIn(frozen['minutes_instruction'],generated.call_args.args[1][0]['content']);return result
        bad=json.loads(json.dumps(body));bad['decisions'][0]['quote']='새 서버는 검토 제안입니다.'
        with self.assertRaisesRegex(ValueError,'결정'): await create(bad)
        bad=json.loads(json.dumps(body));bad['actions'][0]['participant_id']='invented'
        with self.assertRaisesRegex(ValueError,'참석자'): await create(bad)
        minutes=await create(body);self.assertIsNone(minutes.body['actions'][0]['participant_id']);self.assertIsNone(minutes.body['actions'][0]['due_date'])
        edited=edit_artifact(self.db,minutes.id,body|{'topics':[{'title':'수정','text':'검토 후 수정','evidence_ids':[ref.id]}]},True)
        self.assertTrue(edited['edited']);self.assertTrue(edited['confirmed']);self.assertEqual(edited['original_body'],minutes.body)
        self.assertEqual(edited['history'][0]['body']['topics'][0]['title'],'수정')
        markdown=export_markdown(self.db,minutes.id)
        for text in ('주제별 요약','결정 사항','미결 사항','후속 할 일','미정','김민수','다음 주 금요일','확인됨',ref.id): self.assertIn(text,markdown)
        self.assertEqual(len(get_artifact(self.db,minutes.id)['evidence']),1)
        save_participants(self.db,sid,['이서연'])
        self.assertIn('김민수',export_markdown(self.db,minutes.id))

    async def test_minutes_dispatch_and_edit_export_api(self):
        import asyncio,httpx,tempfile
        from pathlib import Path
        from lecture_study.server import create_app
        from lecture_study.config import AppConfig
        with tempfile.TemporaryDirectory() as folder:
            app=create_app(AppConfig(Path(folder),Path(folder)/'runtime',port=8765));db=app.state.db
            sid=create_session(db,'meeting','내보내기 검증',None,None).id;ref=save_note(db,sid,'회의 주제는 일정 조율입니다. 담당자는 정하지 않았습니다.')
            app.state.ollama_url='http://127.0.0.1:11435'
            body={'topics':[{'title':'일정','text':'일정 조율','evidence_ids':[ref.id]}],'decisions':[],'unresolved':[],'actions':[{'text':'담당자 결정','participant_id':None,'owner_quote':None,'due_date':None,'due_expression':None,'evidence_ids':[ref.id]}]}
            try:
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:8765') as client:
                    origin={'Origin':'http://127.0.0.1:8765'};login=await client.post('/api/bootstrap',json={'token':app.state.bootstrap_token},headers=origin);headers=origin|{'X-Session-Token':login.json()['csrf_token']}
                    with patch('lecture_study.outputs.generate',new=AsyncMock(return_value=ProviderResult(text=json.dumps(body),model='test',usage={},elapsed_ms=1))) as generate:
                        posted=await client.post('/api/ai/jobs',json={'session_id':sid,'kind':'minutes','prompt':'회의록 작성','scope':{'session_id':sid}},headers=headers);self.assertEqual(posted.status_code,202,posted.text)
                        await asyncio.gather(*app.state.tasks);job=(await client.get('/api/jobs/'+posted.json()['id'])).json();self.assertEqual(job['status'],'done',job)
                        aid=job['result']['id'];edited=await client.patch('/api/artifacts/'+aid,json={'body':body,'confirmed':True},headers=headers);self.assertEqual(edited.status_code,200,edited.text)
                        exported=await client.get('/api/artifacts/'+aid+'/export');self.assertEqual(exported.status_code,200);self.assertIn('사용자 확인됨',exported.text);self.assertIn('미정',exported.text);self.assertEqual(generate.await_count,1)
            finally:
                for task in list(app.state.tasks): task.cancel()
                await asyncio.gather(*app.state.tasks,return_exceptions=True);db.close()

    async def test_grouped_minutes_cannot_omit_processed_source(self):
        from lecture_study.models import Evidence
        sid=create_session(self.db,'meeting','문맥 병합',None,None).id
        first=save_note(self.db,sid,'금요일 네 대는 제안이며 아직 미확정입니다.')
        second=save_note(self.db,sid,'월요일 세 대로 정정했으나 계약은 하지 않았습니다.')
        request=self.request.model_copy(update={'session_id':sid,'kind':'minutes','scope':Scope(session_id=sid)})
        evidence=[Evidence(ref=first,text='금요일 네 대는 제안이며 아직 미확정입니다.',label='메모'),Evidence(ref=second,text='월요일 세 대로 정정했으나 계약은 하지 않았습니다.',label='정정')]
        frozen={'request':request.model_dump(),'evidence':[e.model_dump()for e in evidence],'summary_parts':[[e.model_dump()for e in evidence]],'participants':[],'cutoff_ms':None,'warning':''};job=submit_job(self.db,sid,'ai',frozen)
        body={'topics':[{'title':'제안','text':'금요일 네 대 제안','evidence_ids':[first.id]}],'decisions':[],'unresolved':[],'actions':[]}
        with patch('lecture_study.outputs.generate',new=AsyncMock(return_value=ProviderResult(text=json.dumps(body),model='test',usage={},elapsed_ms=1))):
            with self.assertRaisesRegex(ValueError,'누락'):await create_minutes(self.db,frozen,job['id'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM artifact_parts WHERE job_id=?',(job['id'],)).fetchone()[0],0)

    def test_explicit_unassigned_candidate_cannot_be_named_owner(self):
        from lecture_study.outputs import validate_minutes
        from lecture_study.models import Evidence,SourceRef
        text='김민수는 담당자 후보이나 담당을 확정하지 않았습니다.'
        ref=SourceRef(id='t1',kind='transcript',session_id=self.sid,start_ms=0,end_ms=1000)
        body={'topics':[],'decisions':[],'unresolved':[],'actions':[{'text':'자료 정리','participant_id':'p1','owner_quote':text,'due_date':None,'due_expression':None,'evidence_ids':['t1']}]}
        with self.assertRaisesRegex(ValueError,'담당'):validate_minutes(body,[Evidence(ref=ref,text=text,label='전사')],[{'id':'p1','name':'김민수'}])

    def test_owner_negation_is_checked_inside_its_sentence(self):
        from lecture_study.outputs import validate_minutes
        from lecture_study.models import Evidence,SourceRef
        ref=SourceRef(id='t1',kind='transcript',session_id=self.sid,start_ms=0,end_ms=1000)
        for text,rejected in [('김민수는 담당자가 아닙니다.',True),('김민수는 이 일을 안 맡습니다.',True),('김민수가 담당합니다. 못 바꿉니다.',False)]:
            with self.subTest(text=text):
                body={'topics':[],'decisions':[],'unresolved':[],'actions':[{'text':'자료 정리','participant_id':'p1','owner_quote':text,'due_date':None,'due_expression':None,'evidence_ids':['t1']}]}
                if rejected:
                    with self.assertRaisesRegex(ValueError,'담당'):validate_minutes(body,[Evidence(ref=ref,text=text,label='전사')],[{'id':'p1','name':'김민수'}])
                else:validate_minutes(body,[Evidence(ref=ref,text=text,label='전사')],[{'id':'p1','name':'김민수'}])


class LiteralDeadlineTests(unittest.TestCase):
    def test_iso_date_and_verbatim_until_expression_refer_to_the_same_date(self):
        from lecture_study.models import Evidence,SourceRef
        from lecture_study.outputs import validate_minutes
        for expression in ('2026-10-19','2026-10-19까지','2026-10-19 까지'):
            evidence=[Evidence(ref=SourceRef(id='t1',kind='transcript',session_id='s',start_ms=0,end_ms=1000),text='자료는 '+expression+' 정리합니다.',label='전사')]
            action={'text':'자료 정리','participant_id':None,'owner_quote':None,'due_date':'2026-10-19','due_expression':expression,'evidence_ids':['t1']}
            body={'topics':[],'decisions':[],'unresolved':[],'actions':[action]}
            self.assertEqual(validate_minutes(body,evidence,[])['actions'][0]['due_expression'],expression)
    def test_suffix_acceptance_never_invents_a_date_or_drops_a_condition(self):
        from lecture_study.models import Evidence,SourceRef
        from lecture_study.outputs import validate_minutes
        for date,expression in (('2026-10-18','2026-10-19까지'),('2026-10-19','다음 주 금요일'),('2026-10-19','2026-10-19까지 승인된 경우')):
            evidence=[Evidence(ref=SourceRef(id='t1',kind='transcript',session_id='s',start_ms=0,end_ms=1000),text='자료는 '+expression+' 정리합니다.',label='전사')]
            body={'topics':[],'decisions':[],'unresolved':[],'actions':[{'text':'자료 정리','participant_id':None,'owner_quote':None,'due_date':date,'due_expression':expression,'evidence_ids':['t1']}]}
            with self.assertRaises(ValueError):validate_minutes(body,evidence,[])

    def test_iso_quote_restores_only_source_whitespace(self):
        from lecture_study.models import Evidence,SourceRef
        from lecture_study.outputs import validate_minutes
        evidence=[Evidence(ref=SourceRef(id='t1',kind='transcript',session_id='s',start_ms=0,end_ms=1000),text='자료는 2026-10-19까지 정리합니다.',label='전사')]
        action={'text':'자료 정리','participant_id':None,'owner_quote':None,'due_date':'2026-10-19','due_expression':'2026-10-19 까지','evidence_ids':['t1']}
        body={'topics':[],'decisions':[],'unresolved':[],'actions':[action]}
        self.assertEqual(validate_minutes(body,evidence,[])['actions'][0]['due_expression'],'2026-10-19까지')
        for expression in ('2026-10-18 까지','2026-10-19까지 승인된 경우','다음 주 금요일'):
            body['actions'][0]['due_expression']=expression
            with self.assertRaises(ValueError):validate_minutes(body,evidence,[])
