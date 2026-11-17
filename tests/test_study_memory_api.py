import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
import httpx
from lecture_study.config import AppConfig
from lecture_study.db import new_id, now
from lecture_study.models import ProviderResult
from lecture_study import study_memory as memory


class StudyAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from lecture_study.server import create_app
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.app = create_app(AppConfig(root/'data', root/'runtime', root, port=8765))
        self.db = self.app.state.db
        self.app.state.secrets.get_secret = lambda provider: None
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://127.0.0.1:8765')
        login = await self.client.post('/api/bootstrap', json={'token': self.app.state.bootstrap_token}, headers={'Origin': 'http://127.0.0.1:8765'})
        self.headers = {'Origin': 'http://127.0.0.1:8765', 'X-Session-Token': login.json()['csrf_token']}
        self.cid = new_id()
        with self.db: self.db.execute('INSERT INTO courses VALUES (?,?,?,?)', (self.cid, '확률', '', now()))
        self.owned = {'course_id': self.cid}
        await self.client.put('/api/settings', json={'provider': 'openai', 'model': 'test-model', 'context_limit': 8192}, headers=self.headers)
        self.thread = (await self.post('/study/threads', self.owned)).json()

    async def asyncTearDown(self):
        for task in list(self.app.state.tasks): task.cancel()
        await asyncio.gather(*self.app.state.tasks, return_exceptions=True)
        await self.client.aclose()
        self.db.close()
        self.app.state.instance_lock.close()

    async def post(self, path, body):
        return await self.client.post('/api'+path, json=body, headers=self.headers)

    async def wait(self, job):
        for _ in range(150):
            row = (await self.client.get('/api/jobs/'+job['id'])).json()
            if row['status'] not in ('queued', 'running'): return row
            await asyncio.sleep(.01)
        self.fail('job did not finish')

    def response(self, answer='지난 대화의 분모를 이어서 살펴볼게요.'):
        return ProviderResult(text=json.dumps({'answer': answer, 'evidence_ids': [], 'context_ids': [], 'basis': 'conversation', 'uncertainty': ''}), model='test-model', usage={}, elapsed_ms=1)

    async def send(self, prompt, include=False, request_id=None):
        return await self.post('/study/threads/'+self.thread['id']+'/messages', self.owned|{'prompt': prompt, 'scope': self.owned, 'include_memory': include, 'request_id': request_id or new_id()})

    async def test_no_evidence_conversation_survives_and_followup_receives_history(self):
        with patch('lecture_study.study_memory_api.generate', new=AsyncMock(return_value=self.response())) as model:
            first = await self.send('20쪽까지 공부했고 베이즈 정리의 분모가 헷갈려요', True)
            self.assertEqual(first.status_code, 202, first.text)
            self.assertEqual((await self.wait(first.json()))['status'], 'done')
            second = await self.send('그 분모를 다시 설명해줘', True)
            self.assertEqual((await self.wait(second.json()))['status'], 'done')
            payload = model.call_args.args[1][1]['content']
            self.assertIn('20쪽까지', payload)
            self.assertIn('그 분모', payload)
        saved = (await self.client.get('/api/study/threads/'+self.thread['id'], params=self.owned)).json()
        self.assertEqual(len(saved['messages']), 4)

    async def test_external_default_and_explicit_exclusion_have_no_history_or_query_expansion(self):
        owned = memory.owner(self.db, course_id=self.cid)
        memory.add_user(self.db, self.thread['id'], owned, '절대 전송하지 않을 이전 대화', self.owned)
        with patch('lecture_study.study_memory_api.generate', new=AsyncMock(return_value=self.response('현재 질문 답')) ) as model, patch('lecture_study.study_memory_api.retrieve', new=AsyncMock(return_value=__import__('lecture_study.models', fromlist=['SearchResult']).SearchResult(evidence=[], mode='keyword'))) as retrieve:
            submitted = await self.send('현재 질문')
            self.assertEqual(submitted.status_code, 202, submitted.text)
            self.assertEqual((await self.wait(submitted.json()))['status'], 'done')
            self.assertNotIn('절대 전송', json.dumps(model.call_args.args[1], ensure_ascii=False))
            self.assertEqual(retrieve.call_args.args[1], '현재 질문')

    async def test_failure_preserves_user_and_idempotent_retry_does_not_duplicate(self):
        rid = new_id()
        with patch('lecture_study.study_memory_api.generate', new=AsyncMock(side_effect=ValueError('모델 실패'))):
            first = (await self.send('계속 기억할 질문', True, rid)).json()
            self.assertEqual((await self.wait(first))['status'], 'failed')
        with patch('lecture_study.study_memory_api.generate', new=AsyncMock(return_value=self.response())):
            retry = await self.post('/study/threads/'+self.thread['id']+'/retry', self.owned|{'job_id': first['id']})
            self.assertEqual(retry.status_code, 202, retry.text)
            self.assertEqual((await self.wait(retry.json()))['status'], 'done')
            again = (await self.send('계속 기억할 질문', True, rid)).json()
            self.assertEqual(again['id'], first['id'])
        self.assertEqual(self.db.execute("SELECT count(*) FROM study_messages WHERE role='user'").fetchone()[0], 1)
        self.assertEqual(self.db.execute("SELECT count(*) FROM study_messages WHERE role='assistant'").fetchone()[0], 1)

    async def test_forget_during_generation_blocks_result_and_retry(self):
        started = asyncio.Event()
        release = asyncio.Event()
        async def delayed(*args, **kwargs):
            started.set()
            await release.wait()
            return self.response('오래된 기억')
        with patch('lecture_study.study_memory_api.generate', new=delayed):
            first = (await self.send('어려운 개념', True)).json()
            await asyncio.wait_for(started.wait(), 2)
            cleared = await self.client.delete('/api/study/memories', params=self.owned, headers=self.headers)
            self.assertEqual(cleared.status_code, 200, cleared.text)
            release.set()
            self.assertIn((await self.wait(first))['status'], ('cancelled', 'failed'))
        retry = await self.post('/study/threads/'+self.thread['id']+'/retry', self.owned|{'job_id': first['id']})
        self.assertEqual(retry.status_code, 422)
        self.assertEqual(self.db.execute("SELECT count(*) FROM study_messages WHERE role='assistant'").fetchone()[0], 0)

    async def test_wrong_owner_and_uninstall_preparation_cannot_mutate(self):
        other = new_id()
        with self.db: self.db.execute('INSERT INTO courses VALUES (?,?,?,?)', (other, '다른 과목', '', now()))
        result = await self.client.get('/api/study/threads/'+self.thread['id'], params={'course_id': other})
        self.assertEqual(result.status_code, 404)
        self.app.state.uninstall_preparing = True
        denied = await self.send('새 질문', True)
        self.assertEqual(denied.status_code, 422)
        self.assertEqual(self.db.execute('SELECT count(*) FROM study_messages').fetchone()[0], 0)

    async def test_idle_extraction_is_local_only_and_course_memory_reaches_new_conversation(self):
        owned=memory.owner(self.db,course_id=self.cid)
        msg=memory.add_user(self.db,self.thread['id'],owned,'20쪽까지 공부했어요',self.owned)
        extracted=ProviderResult(text=json.dumps({'summary':'20쪽까지 공부함','items':[{'kind':'progress','text':'20쪽까지 공부했어요','quote':'20쪽까지 공부했어요','message_id':'발화 1','status':'active','replaces':''}]}),model='local-test',usage={},elapsed_ms=1)
        with patch('lecture_study.study_memory_api.generate',new=AsyncMock(return_value=extracted)) as model:
            self.assertFalse(await self.app.state.study_background_tick())
            model.assert_not_called()
            await self.client.put('/api/settings',json={'provider':'ollama','model':'qwen3.5:4b','context_limit':8192},headers=self.headers)
            self.app.state.ollama_url='http://127.0.0.1:11434'
            self.assertTrue(await self.app.state.study_background_tick())
            self.assertEqual(model.call_args.kwargs['output_limit'],512)
            self.assertEqual(model.call_args.args[3]['properties']['items']['maxItems'],4)
            quotes=model.call_args.args[3]['properties']['items']['items']['properties']['quote']['enum']
            self.assertIn(msg['text'],quotes)
            self.assertTrue(all(quote in msg['text'] for quote in quotes))
        self.assertEqual(len(memory.memory_list(self.db,self.cid)),1)
        await self.client.put('/api/settings',json={'provider':'openai','model':'test-model','context_limit':8192},headers=self.headers)
        self.app.state.ollama_url=None
        self.thread=(await self.post('/study/threads',self.owned)).json()
        with patch('lecture_study.study_memory_api.generate',new=AsyncMock(return_value=self.response('20쪽까지 공부했어요'))) as model:
            job=(await self.send('어디까지 했지?',True)).json()
            finished=await self.wait(job)
            self.assertEqual(finished['status'],'done',finished['error'])
            self.assertIn('20쪽까지',model.call_args.args[1][1]['content'])

    async def test_budget_and_citations_are_checked(self):
        from lecture_study.study_memory_api import bounded_input,validate_answer
        provider=__import__('lecture_study.models',fromlist=['ProviderConfig']).ProviderConfig(provider='openai',model='test-model',context_limit=512)
        with self.assertRaisesRegex(ValueError,'예산'):bounded_input(provider,'긴 질문'*100,[],[],'',[])
        with self.assertRaises(ValueError):validate_answer({'answer':'답','basis':'sources','evidence_ids':['invented'],'context_ids':[],'uncertainty':''},[],[])

    async def test_model_context_uses_readable_labels_and_persists_original_provenance(self):
        owned=memory.owner(self.db,course_id=self.cid)
        original=memory.add_user(self.db,self.thread['id'],owned,'20쪽까지 공부했어',self.owned)
        async def reply(provider,messages,images,schema,**kwargs):
            self.assertEqual(messages[-1],{'role':'user','content':'어디까지 했지?'})
            payload=json.loads(messages[1]['content'])
            self.assertNotIn(original['id'],messages[1]['content'])
            label=payload['history'][0]['id']
            self.assertEqual(label,'이전 대화 1')
            return ProviderResult(text=json.dumps({'answer':'20쪽까지 공부했어요','basis':'conversation','context_ids':[label],'evidence_ids':[],'uncertainty':''}),model='test-model',usage={},elapsed_ms=1)
        with patch('lecture_study.study_memory_api.generate',new=reply):
            submitted=(await self.send('어디까지 했지?',True)).json()
            done=await self.wait(submitted)
            self.assertEqual(done['status'],'done',done['error'])
        body=json.loads(self.db.execute('SELECT body FROM artifacts WHERE job_id=?',(submitted['id'],)).fetchone()[0])
        self.assertEqual(body['context_ids'],[original['id']])

    async def test_background_deferral_keeps_extraction_pending(self):
        from lecture_study.second_brain import BackgroundDeferred
        owned=memory.owner(self.db,course_id=self.cid)
        memory.add_user(self.db,self.thread['id'],owned,'20쪽까지 공부했어요',self.owned)
        await self.client.put('/api/settings',json={'provider':'ollama','model':'qwen3.5:4b','context_limit':8192},headers=self.headers)
        self.app.state.ollama_url='http://127.0.0.1:11434'
        with patch('lecture_study.study_memory_api.admit_background',new=AsyncMock(side_effect=BackgroundDeferred('사용자 작업 후 자동 처리'))):
            await self.app.state.study_background_tick()
        self.assertIsNotNone(memory.next_extraction(self.db))
        self.assertIsNone(memory.thread_row(self.db,self.thread['id'],owned)['summary_error'])

    async def test_large_memory_collection_does_not_expand_replacement_schema(self):
        owned=memory.owner(self.db,course_id=self.cid)
        original=memory.add_user(self.db,self.thread['id'],owned,'기존 학습 기억 '+','.join(str(i) for i in range(200)),self.owned)
        with self.db:
            self.db.execute('UPDATE study_messages SET processed=1 WHERE id=?',(original['id'],))
            for i in range(200):
                self.db.execute("INSERT INTO study_memories(id,course_id,kind,text,quote,source_message_id,created_at,updated_at) VALUES (?,?,'topic',?,?,?,?,?)",(new_id(),self.cid,'주제 '+str(i),str(i),original['id'],now(),now()))
        memory.add_user(self.db,self.thread['id'],owned,'20쪽까지 공부했어요',self.owned)
        await self.client.put('/api/settings',json={'provider':'ollama','model':'qwen3.5:4b','context_limit':8192},headers=self.headers)
        self.app.state.ollama_url='http://127.0.0.1:11434'
        result=ProviderResult(text=json.dumps({'summary':'20쪽까지 공부함','items':[]}),model='local-test',usage={},elapsed_ms=1)
        with patch('lecture_study.study_memory_api.generate',new=AsyncMock(return_value=result)) as model:
            await self.app.state.study_background_tick()
            self.assertEqual(model.await_count,1)
            schema=model.call_args.args[3]
            payload=json.loads(model.call_args.args[1][-1]['content'])
            self.assertEqual(schema['properties']['items']['items']['properties']['replaces']['enum'],['',*[m['id'] for m in payload['previous_memories']]])

    async def test_quiz_override_revokes_old_retry_before_new_snapshot(self):
        from lecture_study.jobs import submit_job
        job=submit_job(self.db,None,'ai',{},course_id=self.cid)
        aid,attempt=new_id(),new_id()
        with self.db:
            self.db.execute("INSERT INTO artifacts(id,job_id,course_id,kind,body,evidence,metadata,created_at) VALUES (?,?,?,'quiz',?,'[]','{}',?)",(aid,job['id'],self.cid,json.dumps({'questions':[{'id':'q','prompt':'독립 조건은?'}]}),now()))
            self.db.execute("INSERT INTO attempts(id,quiz_id,question_id,submitted_answer,grade,explanation,evidence_ids,metadata,status,created_at) VALUES (?,?,?,'답','incorrect','해설','[]','{}','done',?)",(attempt,aid,'q',now()))
        memory.sync_quizzes(self.db)
        with patch('lecture_study.study_memory_api.generate',new=AsyncMock(side_effect=ValueError('모델 실패'))):
            first=(await self.send('복습하자',True)).json();await self.wait(first)
        with self.db:self.db.execute('INSERT INTO attempt_revisions VALUES (?,1,?,?,?)',(attempt,'correct','정정',now()))
        memory.sync_quizzes(self.db)
        retry=await self.post('/study/threads/'+self.thread['id']+'/retry',self.owned|{'job_id':first['id']})
        self.assertEqual(retry.status_code,422)


if __name__ == '__main__': unittest.main()
