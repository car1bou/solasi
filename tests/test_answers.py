import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock,patch
from lecture_study.db import open_db,create_session
from lecture_study.materials import save_note
from lecture_study.models import AIRequest,Scope,ProviderConfig,ProviderResult,Evidence
from lecture_study.answers import freeze_request,validate_generated,run_ai_request,get_artifact
from lecture_study.jobs import submit_job

class AnswerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.db=open_db(Path(self.temp.name));self.addCleanup(self.db.close)
        self.sid=create_session(self.db,'lecture','검증',None,None).id
        self.ref=save_note(self.db,self.sid,'프로세스는 실행 중인 프로그램입니다.')
        self.request=AIRequest(session_id=self.sid,kind='answer',prompt='프로세스는 무엇인가?',scope=Scope(session_id=self.sid),provider=ProviderConfig(provider='openai',model='gpt-4.1-mini'))

    async def test_frozen_evidence_and_idempotent_artifact(self):
        frozen=await freeze_request(self.db,self.request)
        self.assertEqual(frozen['evidence'][0]['ref']['id'],self.ref.id)
        new=save_note(self.db,self.sid,'완전히 변경된 프로세스 메모')
        body={'answer':'실행 중인 프로그램입니다.','citations':[{'source_id':self.ref.id,'page':None,'start_ms':None,'end_ms':None}],'uncertainty':''}
        result=ProviderResult(text=json.dumps(body),model='gpt-4.1-mini',usage={'input_tokens':20},elapsed_ms=8)
        with patch('lecture_study.answers.generate',new=AsyncMock(return_value=result)) as generate:
            job=submit_job(self.db,self.sid,'ai',frozen)
            first=await run_ai_request(self.db,frozen,job['id'],secret='test-key')
            second=await run_ai_request(self.db,frozen,job['id'],secret='test-key')
            self.assertEqual(first.id,second.id);self.assertEqual(generate.await_count,1)
            saved=get_artifact(self.db,first.id)
            self.assertEqual(saved['evidence'][0]['ref']['id'],self.ref.id)
            self.assertNotIn(new.id,{e['ref']['id'] for e in saved['evidence']})
            self.assertEqual(generate.call_args.args[1][-1]['role'],'user')
            self.assertIn('프로세스는 실행 중인 프로그램',generate.call_args.args[1][-1]['content'])
            self.assertNotIn('완전히 변경된',generate.call_args.args[1][-1]['content'])
            self.assertNotIn('test-key','\n'.join(self.db.iterdump()))
            get_artifact(self.db,first.id);self.assertEqual(generate.await_count,1)

    async def test_generation_schema_limits_citations_to_actual_evidence(self):
        from lecture_study.answers import ANSWER_SCHEMA
        frozen=await freeze_request(self.db,self.request);job=submit_job(self.db,self.sid,'ai',frozen)
        body={'answer':'정의','citations':[{'source_id':self.ref.id,'page':None,'start_ms':None,'end_ms':None}],'uncertainty':''}
        with patch('lecture_study.answers.generate',new=AsyncMock(return_value=ProviderResult(text=json.dumps(body),model='test',usage={},elapsed_ms=1))) as generate:
            await run_ai_request(self.db,frozen,job['id'])
        schema=generate.call_args.args[3]
        self.assertEqual(schema['properties']['citations']['items']['properties']['source_id']['enum'],[self.ref.id])
        self.assertNotIn('enum',ANSWER_SCHEMA['properties']['citations']['items']['properties']['source_id'])

    def test_unknown_ids_and_fabricated_location_rejected(self):
        evidence=[Evidence(ref=self.ref,text='원문',label='노트')]
        for citation in ({'source_id':'invented'},{'source_id':self.ref.id,'page':3},{'source_id':self.ref.id,'start_ms':100},{'source_id':self.ref.id,'url':'https://fabricated.example'}):
            with self.assertRaises(ValueError): validate_generated({'answer':'답','citations':[citation],'uncertainty':''},evidence)
        body=validate_generated({'answer':'<img src=x onerror=alert(1)>','citations':[{'source_id':self.ref.id}],'uncertainty':''},evidence)
        self.assertEqual(body['answer'],'<img src=x onerror=alert(1)>')

    async def test_cancelled_generation_does_not_stop_pcm_and_budget_is_explicit(self):
        from lecture_study.audio import start_recording,append_pcm,get_recording
        rid=start_recording(self.db,self.sid,48000)
        append_pcm(self.db,rid,0,0,4800,b'\x00\x01'*4800)
        frozen=await freeze_request(self.db,self.request)
        job=submit_job(self.db,self.sid,'ai',frozen)
        async def wait(*a,**kw): await asyncio.sleep(60)
        with patch('lecture_study.answers.generate',new=wait):
            task=asyncio.create_task(run_ai_request(self.db,frozen,job['id'],secret='test-key'))
            await asyncio.sleep(.01);task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
        append_pcm(self.db,rid,1,4800,4800,b'\x00\x01'*4800)
        self.assertEqual(get_recording(self.db,rid)['stored_frames'],9600)
        tiny=self.request.model_copy(update={'provider':ProviderConfig(provider='openai',model='gpt-4.1-mini',context_limit=512)})
        with self.assertRaisesRegex(ValueError,'예산'): await freeze_request(self.db,tiny)

    async def test_deleted_evidence_blocks_retry(self):
        from lecture_study.lifecycle import delete_session
        frozen=await freeze_request(self.db,self.request)
        job=submit_job(self.db,self.sid,'ai',frozen)
        delete_session(self.db,self.sid,True)
        with patch('lecture_study.answers.generate',new=AsyncMock()) as generate:
            with self.assertRaises((KeyError,ValueError)): await run_ai_request(self.db,frozen,job['id'],secret='test-key')
            generate.assert_not_called()

    async def test_cumulative_cutoff_keeps_previous_late_timestamps(self):
        from lecture_study.db import new_id,now
        from lecture_study.audio import start_recording,append_pcm
        from lecture_study.transcription import plan_chunks,accept_transcription,list_transcripts
        course=new_id()
        with self.db:
            self.db.execute('INSERT INTO courses VALUES (?,?,?,?)',(course,'과목','',now()))
            self.db.execute('UPDATE sessions SET course_id=?,lecture_no=2 WHERE id=?',(course,self.sid))
        previous=create_session(self.db,'lecture','이전 수업',course,1).id
        for sid,seconds in ((previous,10),(self.sid,1)):
            rid=start_recording(self.db,sid,48000)
            for n in range(seconds): append_pcm(self.db,rid,n,48000*n,48000,b'\x00\x01'*48000)
            chunk=plan_chunks(self.db,rid,True)[0]
            accept_transcription(self.db,rid,chunk['id'],chunk['revision'],True,[{'start_ms':0,'end_ms':1000*seconds,'text':'프로세스 수업'}])
        frozen=await freeze_request(self.db,self.request)
        self.assertEqual(frozen['cutoff_ms'],1000)
        old=list_transcripts(self.db,previous)[0]['id']+':v1'
        self.assertIn(old,{e['ref']['id'] for e in frozen['evidence']})

    async def test_chunk_join_is_source_data_and_cross_session_deletion_scrubs_copies(self):
        from lecture_study.db import new_id,now
        from lecture_study.lifecycle import delete_session
        from lecture_study.answers import checked_evidence
        long=save_note(self.db,self.sid,'프로세스 '*300)
        frozen=await freeze_request(self.db,self.request);checked_evidence(self.db,frozen)
        self.assertTrue(frozen['excerpted']);self.assertEqual(frozen['evidence'][0]['ref']['id'],long.id)
        course=new_id()
        with self.db:
            self.db.execute('INSERT INTO courses VALUES (?,?,?,?)',(course,'과목','',now()))
            self.db.execute('UPDATE sessions SET course_id=? WHERE id=?',(course,self.sid))
        previous=create_session(self.db,'lecture','이전',course,1).id
        ref=save_note(self.db,previous,'프로세스 과거 원문')
        request=self.request.model_copy(update={'scope':Scope(session_id=self.sid,mode='selected',lecture_ids=[previous])})
        frozen=await freeze_request(self.db,request);self.assertIn(ref.id,{e['ref']['id'] for e in frozen['evidence']})
        job=submit_job(self.db,self.sid,'ai',frozen)
        with patch('lecture_study.answers.generate',new=AsyncMock(return_value=ProviderResult(text=json.dumps({'answer':'답','citations':[{'source_id':ref.id}],'uncertainty':''}),model='gpt-4.1-mini',usage={},elapsed_ms=1))):
            result=await run_ai_request(self.db,frozen,job['id'],secret='test-key')
        delete_session(self.db,previous,True)
        saved=get_artifact(self.db,result.id)
        self.assertEqual(next(e['text'] for e in saved['evidence'] if e['ref']['id']==ref.id),'')
        stored=json.loads(self.db.execute('SELECT request FROM jobs WHERE id=?',(job['id'],)).fetchone()[0])
        self.assertEqual(next(e['text'] for e in stored['evidence'] if e['ref']['id']==ref.id),'')

class AnswerApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_api_local_retry_preserves_old_attempt_and_creates_new_job(self):
        import httpx
        from lecture_study.server import create_app
        from lecture_study.config import AppConfig
        with tempfile.TemporaryDirectory() as folder:
            app=create_app(AppConfig(Path(folder),Path(folder)/'runtime',port=8765))
            sid=create_session(app.state.db,'lecture','질문 검증',None,None).id
            ref=save_note(app.state.db,sid,'프로세스는 실행 중인 프로그램입니다.')
            body={'answer':'<script>실행하지 않는 텍스트</script>','citations':[{'source_id':ref.id}],'uncertainty':''}
            result=ProviderResult(text=json.dumps(body),model='qwen3.5:4b',usage={'eval_count':8},elapsed_ms=10)
            app.state.ollama_url='http://127.0.0.1:11435'
            try:
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:8765') as client:
                    origin={'Origin':'http://127.0.0.1:8765'}
                    login=await client.post('/api/bootstrap',json={'token':app.state.bootstrap_token},headers=origin)
                    headers=origin|{'X-Session-Token':login.json()['csrf_token']}
                    await client.put('/api/settings',json={'provider':'openai','model':'gpt-4.1-mini','context_limit':8192},headers=headers)
                    with patch.object(app.state.secrets,'get_secret',return_value='test-key'),patch('lecture_study.answers.generate',new=AsyncMock(side_effect=[ValueError('API 인증 실패'),result])) as generate,patch('lecture_study.server.model_status',new=AsyncMock(return_value={'completion':True,'vision':False})):
                        submitted=await client.post('/api/ai/jobs',json={'session_id':sid,'prompt':'프로세스란?', 'scope':{'session_id':sid}},headers=headers)
                        self.assertEqual(submitted.status_code,202,submitted.text);ident=submitted.json()['id']
                        for _ in range(100):
                            job=(await client.get('/api/jobs/'+ident)).json()
                            if job['status']=='failed': break
                            await asyncio.sleep(.001)
                        self.assertEqual(job['status'],'failed');self.assertEqual(generate.await_count,1)
                        retried=await client.post('/api/jobs/'+ident+'/retry-local',json={'model':'qwen3.5:4b'},headers=headers)
                        self.assertEqual(retried.status_code,200,retried.text);fresh=retried.json()['id'];self.assertNotEqual(fresh,ident)
                        original=(await client.get('/api/jobs/'+ident)).json();self.assertEqual(original['status'],'failed');self.assertEqual(original['request']['request']['provider']['model'],'gpt-4.1-mini')
                        for _ in range(100):
                            job=(await client.get('/api/jobs/'+fresh)).json()
                            if job['status']=='done': break
                            await asyncio.sleep(.001)
                        self.assertEqual(job['status'],'done',job)
                        saved=await client.get('/api/artifacts/'+job['result']['id']);self.assertEqual(saved.status_code,200)
                        self.assertEqual(saved.json()['body']['answer'],body['answer']);self.assertEqual(saved.json()['metadata']['provider'],'ollama')
                        await client.get('/api/sessions/'+sid+'/artifacts');await client.get('/api/artifacts/'+job['result']['id'])
                        self.assertEqual(generate.await_count,2)
                        self.assertEqual(app.state.db.execute('SELECT count(*) FROM artifacts WHERE job_id=?',(fresh,)).fetchone()[0],1)
                        attempts=app.state.db.execute('SELECT provider,status FROM ai_attempts WHERE job_id IN (?,?) ORDER BY created_at',(ident,fresh)).fetchall()
                        self.assertEqual([tuple(r) for r in attempts],[('openai','failed'),('ollama','done')])
                        self.assertNotIn('test-key','\n'.join(app.state.db.iterdump()))
            finally:
                for task in list(app.state.tasks):task.cancel()
                await asyncio.gather(*app.state.tasks,return_exceptions=True);app.state.db.close()
