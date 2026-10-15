import asyncio,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from lecture_study.config import AppConfig
from lecture_study.server import create_app
from lecture_study.db import create_session,new_id,now
from lecture_study.materials import save_note
from lecture_study.audio import start_recording,append_pcm
from lecture_study.transcription import plan_chunks
from lecture_study.jobs import submit_job
from lecture_study.models import Evidence,ProviderResult


class LocalPriorityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);self.app=create_app(AppConfig(root,root/'runtime',port=8765));self.db=self.app.state.db
        self.sid=create_session(self.db,'lecture','우선순위',None,None).id
        self.ref=save_note(self.db,self.sid,'프로세스는 실행 중인 프로그램입니다.')
        self.app.state.ollama_url='http://127.0.0.1:11435'
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url='http://127.0.0.1:8765')
        origin={'Origin':'http://127.0.0.1:8765'}
        login=await self.client.post('/api/bootstrap',json={'token':self.app.state.bootstrap_token},headers=origin)
        self.headers=origin|{'X-Session-Token':login.json()['csrf_token']}

    async def asyncTearDown(self):
        for task in list(self.app.state.tasks):task.cancel()
        await asyncio.gather(*self.app.state.tasks,return_exceptions=True)
        await self.client.aclose();self.db.close();self.app.state.instance_lock.close()

    def backlog(self,final=True):
        rid=start_recording(self.db,self.sid,16000)
        for seq in range(4 if final else 10):append_pcm(self.db,rid,seq,seq*16000,16000,b'\1\0'*16000)
        chunk=plan_chunks(self.db,rid,final)[0]
        return chunk['id']

    def clear(self,ident):
        with self.db:self.db.execute("UPDATE transcript_ranges SET status='done' WHERE id=?",(ident,))

    async def post(self,path,body):
        response=await self.client.post(path,json=body,headers=self.headers)
        self.assertLess(response.status_code,300,response.text)
        return response

    async def job(self,ident,predicate):
        for _ in range(200):
            job=(await self.client.get('/api/jobs/'+ident)).json()
            if predicate(job):return job
            await asyncio.sleep(.005)
        self.fail('job did not reach expected state: '+str(job))

    async def ask(self):
        return (await self.post('/api/ai/jobs',{'session_id':self.sid,'prompt':'프로세스란?','scope':{'session_id':self.sid}})).json()

    def answer(self):
        return ProviderResult(text=json.dumps({'answer':'실행 중인 프로그램','citations':[{'source_id':self.ref.id}],'uncertainty':''}),model='fixture',usage={},elapsed_ms=1)

    async def test_waiting_local_answer_can_cancel_retry_and_keeps_question_snapshot(self):
        pending=self.backlog();started=asyncio.Event()
        async def generate(*args,**kwargs):started.set();return self.answer()
        with patch('lecture_study.answers.generate',new=generate):
            submitted=await asyncio.wait_for(self.ask(),1)
            job=await self.job(submitted['id'],lambda j:bool((j['result'] or {}).get('paused_reason')))
            self.assertEqual(job['result']['paused_reason'],'전사 처리 후 실행');self.assertFalse(started.is_set())
            save_note(self.db,self.sid,'지연 중 새로 입력한 다른 정의')
            cancelled=(await self.post('/api/jobs/'+job['id']+'/cancel',{})).json()
            self.assertEqual(cancelled['status'],'cancelled');self.assertFalse(started.is_set())
            self.clear(pending)
            await self.post('/api/jobs/'+job['id']+'/retry',{})
            finished=await self.job(job['id'],lambda j:j['status'] in ('done','failed'))
            self.assertEqual(finished['status'],'done',finished)
            artifact=(await self.client.get('/api/artifacts/'+finished['result']['id'])).json()
            self.assertEqual(artifact['evidence'][0]['ref']['id'],self.ref.id)
            self.assertIn('실행 중인 프로그램',artifact['evidence'][0]['text'])

    async def test_preview_does_not_block_generation(self):
        self.backlog(final=False)
        async def generate(*args,**kwargs):return self.answer()
        with patch('lecture_study.answers.generate',new=generate):
            job=await self.ask();done=await self.job(job['id'],lambda j:j['status'] in ('done','failed'))
            self.assertEqual(done['status'],'done',done)

    async def test_inflight_local_answer_is_preserved_and_external_answer_runs_during_backlog(self):
        started=asyncio.Event();release=asyncio.Event()
        async def generate(provider,*args,**kwargs):
            if provider.provider=='ollama':started.set();await release.wait()
            return self.answer()
        with patch('lecture_study.answers.generate',new=generate),patch.object(self.app.state.secrets,'get_secret',return_value='fixture-key'):
            local=await self.ask();await asyncio.wait_for(started.wait(),1);self.backlog()
            await self.client.put('/api/settings',json={'provider':'openai','model':'gpt-4.1-mini','context_limit':8192},headers=self.headers)
            external=await self.ask();done=await self.job(external['id'],lambda j:j['status'] in ('done','failed'))
            self.assertEqual(done['status'],'done',done)
            running=(await self.client.get('/api/jobs/'+local['id'])).json();self.assertEqual(running['status'],'running')
            release.set();done=await self.job(local['id'],lambda j:j['status'] in ('done','failed'))
            self.assertEqual(done['status'],'done',done)

    async def test_local_free_grade_saves_answer_before_wait_and_retry_reuses_attempt(self):
        pending=self.backlog();jid=submit_job(self.db,self.sid,'ai',{})['id'];aid=new_id()
        question={'id':'q1','kind':'free','prompt':'프로세스란?','options':[],'answer':'실행 중인 프로그램','rubric':'정의','explanation':'정의','evidence_ids':[self.ref.id],'concept_ids':[],'external_extension':False}
        evidence=Evidence(ref=self.ref,text='프로세스는 실행 중인 프로그램입니다.',label='노트')
        with self.db:self.db.execute('INSERT INTO artifacts(id,job_id,session_id,kind,body,evidence,metadata,created_at) VALUES (?,?,?,?,?,?,?,?)',(aid,jid,self.sid,'quiz',json.dumps({'questions':[question]}),json.dumps([evidence.model_dump()]),'{}',now()))
        async def generate(*args,**kwargs):return ProviderResult(text=json.dumps({'grade':'correct','explanation':'정의 일치','evidence_ids':[self.ref.id]}),model='fixture',usage={},elapsed_ms=1)
        with patch('lecture_study.outputs.generate',new=generate):
            response=await asyncio.wait_for(self.post('/api/quizzes/'+aid+'/attempts',{'question_id':'q1','answer':'제출한 정의'}),1)
            self.assertEqual(response.status_code,202);job=response.json()
            waiting=await self.job(job['id'],lambda j:bool((j['result'] or {}).get('paused_reason')))
            attempt=self.db.execute('SELECT id,submitted_answer FROM attempts').fetchone()
            self.assertEqual(attempt['submitted_answer'],'제출한 정의')
            await self.post('/api/jobs/'+waiting['id']+'/cancel',{})
            self.assertEqual(self.db.execute('SELECT status FROM attempts').fetchone()[0],'cancelled')
            self.clear(pending);await self.post('/api/jobs/'+job['id']+'/retry',{})
            done=await self.job(job['id'],lambda j:j['status'] in ('done','failed'))
            self.assertEqual(done['status'],'done',done)
            saved=self.db.execute('SELECT id,grade,submitted_answer FROM attempts').fetchall()
            self.assertEqual(len(saved),1);self.assertEqual(tuple(saved[0]),(attempt['id'],'correct','제출한 정의'))

    async def test_semantic_search_waits_before_embed_and_cancel_keeps_model_unstarted(self):
        pending=self.backlog();chunk=self.db.execute('SELECT id FROM chunks WHERE source_id=?',(self.ref.id,)).fetchone()[0]
        import struct
        with self.db:
            self.db.execute("INSERT INTO embedding_sets VALUES ('index','embeddinggemma','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',2,'embeddinggemma-search-v1/chunk512-v1','ready',?)",(now(),))
            self.db.execute("INSERT INTO embeddings VALUES ('index',?,0,?)",(chunk,struct.pack('<ff',1,0)))
            self.db.execute("INSERT INTO settings VALUES ('active_embedding_index','\"index\"')")
        calls=[]
        async def request(transport,req):
            calls.append(req.url.path)
            if req.url.path=='/api/tags':body={'models':[{'name':'embeddinggemma','digest':'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'}]}
            elif req.url.path=='/api/embed':body={'embeddings':[[1,0]]}
            else:body={'capabilities':['embedding']}
            return httpx.Response(200,json=body)
        with patch.object(httpx.AsyncHTTPTransport,'handle_async_request',new=request):
            response=await asyncio.wait_for(self.post('/api/sessions/'+self.sid+'/search',{'query':'프로세스','scope':{'session_id':self.sid}}),1)
            self.assertEqual(response.status_code,202);job=response.json()
            await self.job(job['id'],lambda j:bool((j['result'] or {}).get('paused_reason')))
            self.assertNotIn('/api/embed',calls)
            await self.post('/api/jobs/'+job['id']+'/cancel',{})
            self.assertNotIn('/api/embed',calls)
            self.clear(pending)
            await self.post('/api/jobs/'+job['id']+'/retry',{})
            done=await self.job(job['id'],lambda j:j['status'] in ('done','failed'))
            self.assertEqual(done['status'],'done',done)
            self.assertEqual(done['result']['mode'],'hybrid')
            self.assertEqual(done['result']['evidence'][0]['ref']['id'],self.ref.id)

    async def test_cancel_before_operation_starts_updates_saved_job(self):
        from lecture_study.jobs import launch_job,get_job
        job=submit_job(self.db,self.sid,'test',{})
        async def operation():self.fail('cancelled operation was started')
        launch_job(self.app,job,operation)
        task=self.app.state.job_tasks[job['id']];task.cancel()
        await asyncio.gather(task,return_exceptions=True);await asyncio.sleep(0)
        self.assertEqual(get_job(self.db,job['id'])['status'],'cancelled')

    async def test_local_transport_rechecks_backlog_after_model_probe(self):
        from lecture_study.providers import generate
        from lecture_study.models import ProviderConfig
        from lecture_study.jobs import wait_for_transcription
        job=submit_job(self.db,self.sid,'test',{});calls=[];pending=[]
        async def response(request):
            calls.append(request.url.path)
            if request.url.path=='/api/tags':body={'models':[{'name':'qwen3.5:4b','digest':'a'*64}]}
            elif request.url.path=='/api/show':pending.append(self.backlog());body={'capabilities':['completion']}
            else:body={'done':True,'model':'qwen3.5:4b','message':{'content':'답변'}}
            return httpx.Response(200,json=body)
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            task=asyncio.create_task(generate(ProviderConfig(),[{'role':'user','content':'질문'}],[],None,client=client,ollama_url=self.app.state.ollama_url,before_local=lambda:wait_for_transcription(self.db,job['id'])))
            try:
                await self.job(job['id'],lambda j:bool((j['result'] or {}).get('paused_reason')))
                self.assertNotIn('/api/chat',calls);self.clear(pending[0])
                result=await asyncio.wait_for(task,1);self.assertEqual(result.text,'답변')
            finally:
                task.cancel();await asyncio.gather(task,return_exceptions=True)

    async def test_deleting_other_session_removes_saved_search_excerpt(self):
        from lecture_study.retrieval import retrieve
        from lecture_study.models import Scope
        from lecture_study.jobs import run_job,get_job
        from lecture_study.lifecycle import delete_session
        course=new_id()
        with self.db:
            self.db.execute('INSERT INTO courses VALUES (?,?,?,?)',(course,'과목','',now()))
            self.db.execute('UPDATE sessions SET course_id=? WHERE id=?',(course,self.sid))
        other=create_session(self.db,'lecture','이전',course,1).id
        ref=save_note(self.db,other,'프로세스 삭제 대상 비공개 원문')
        job=submit_job(self.db,self.sid,'search',{})
        await run_job(self.db,job['id'],lambda:retrieve(self.db,'프로세스',Scope(session_id=self.sid),None))
        self.assertIn('삭제 대상 비공개 원문',json.dumps(get_job(self.db,job['id'])['result'],ensure_ascii=False))
        delete_session(self.db,other,True)
        saved=get_job(self.db,job['id'])['result']
        self.assertNotIn('삭제 대상 비공개 원문',json.dumps(saved,ensure_ascii=False))
        self.assertEqual(next(e['text'] for e in saved['evidence'] if e['ref']['id']==ref.id),'')

    async def grade_deleted_source(self,stage):
        from lecture_study.outputs import save_attempt,grade_attempt
        from lecture_study.lifecycle import delete_session
        from lecture_study.models import ProviderConfig
        other=create_session(self.db,'lecture','이전',None,None).id
        ref=save_note(self.db,other,'프로세스 삭제 대상 비공개 원문')
        jid=submit_job(self.db,self.sid,'ai',{})['id'];aid=new_id()
        question={'id':'q1','kind':'free','prompt':'프로세스란?','options':[],'answer':'실행 중인 프로그램','rubric':'정의','explanation':'정의','evidence_ids':[ref.id],'concept_ids':[],'external_extension':False}
        evidence=Evidence(ref=ref,text='프로세스 삭제 대상 비공개 원문',label='노트')
        with self.db:self.db.execute('INSERT INTO artifacts(id,job_id,session_id,kind,body,evidence,metadata,created_at) VALUES (?,?,?,?,?,?,?,?)',(aid,jid,self.sid,'quiz',json.dumps({'questions':[question]}),json.dumps([evidence.model_dump()]),'{}',now()))
        ident=save_attempt(self.db,aid,'q1','보존할 답안');calls=[]
        async def response(request):
            calls.append(request.url.path)
            if request.url.path=='/api/tags':body={'models':[{'name':'qwen3.5:4b','digest':'a'*64}]}
            elif request.url.path=='/api/show':body={'capabilities':['completion']}
            else:
                if stage=='running':delete_session(self.db,other,True)
                body={'done':True,'model':'qwen3.5:4b','message':{'content':json.dumps({'grade':'correct','explanation':'판정','evidence_ids':[ref.id]})}}
            return httpx.Response(200,json=body)
        async def admitted():
            if stage=='waiting':delete_session(self.db,other,True)
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            result=await grade_attempt(self.db,ident,provider=ProviderConfig(),client=client,ollama_url=self.app.state.ollama_url,before_local=admitted)
        self.assertEqual(result['status'],'failed');self.assertEqual(result['submitted_answer'],'보존할 답안')
        if stage=='waiting':self.assertNotIn('/api/chat',calls)
        else:self.assertIn('/api/chat',calls)

    async def test_grade_does_not_send_evidence_deleted_during_admission_wait(self):
        await self.grade_deleted_source('waiting')

    async def test_grade_does_not_save_success_if_source_is_deleted_inflight(self):
        await self.grade_deleted_source('running')

    async def test_preparation_snapshot_does_not_pick_new_note_revision(self):
        from lecture_study.answers import capture_request,freeze_request
        from lecture_study.models import AIRequest,Scope,ProviderConfig
        request=AIRequest(session_id=self.sid,kind='answer',prompt='프로세스',scope=Scope(session_id=self.sid),provider=ProviderConfig())
        snapshot=capture_request(self.db,request)
        save_note(self.db,self.sid,'프로세스 대기 중 바뀐 새 버전')
        frozen=await freeze_request(self.db,request,snapshot=snapshot)
        self.assertEqual(frozen['evidence'][0]['ref']['id'],self.ref.id)
        self.assertNotIn('바뀐 새 버전',frozen['evidence'][0]['text'])

    async def test_new_memo_and_candidate_requests_wait_for_final_asr(self):
        from tests.test_assistance import AssistanceTests
        from lecture_study.audio import stop_recording
        from unittest.mock import AsyncMock
        tid=AssistanceTests.speech(self)
        rid=self.db.execute("SELECT id FROM recordings WHERE status='recording'").fetchone()[0];stop_recording(self.db,rid)
        pending=self.backlog();jobs=[]
        async def generated(config,messages,*args,**kwargs):
            kind=json.loads(messages[-1]['content'])['kind']
            body={'addition':'공유 자원 접근 제어','evidence_ids':[tid]} if kind=='note' else {'cards':[]}
            return ProviderResult(text=json.dumps(body),model='fixture',usage={},elapsed_ms=1)
        gen=AsyncMock(side_effect=generated)
        with patch('lecture_study.assistance.generate',new=gen):
            for kind in ('note','candidates'):
                posted=(await self.post('/api/ai/jobs',{'session_id':self.sid,'kind':kind,'prompt':'확정 전사 활용','scope':{'session_id':self.sid,'mode':'current'},'note_source_id':self.ref.id if kind=='note' else None,'anchor_ms':500 if kind=='note' else None})).json()
                jobs.append(posted['id']);await self.job(posted['id'],lambda j:bool((j['result'] or {}).get('paused_reason')))
            self.assertEqual(gen.await_count,0);self.clear(pending)
            for jid in jobs:
                done=await self.job(jid,lambda j:j['status'] in ('done','failed'));self.assertEqual(done['status'],'done',done)
            self.assertEqual(gen.await_count,2)


if __name__=='__main__':unittest.main()
