import asyncio,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import AsyncMock,patch
from lecture_study.direct_models import DirectModels,DirectEmbeddings,EmbeddingInputTooLong,EMBEDDING_ENGINE,EMBEDDING_FORMAT
from lecture_study.models import ProviderConfig


class EmbeddingReuseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.manager=DirectModels(self.root,self.root/'cache')
        self.addAsyncCleanup(self.manager.stop)
        self.manager.status=AsyncMock(return_value={'digest':'a'*64,'embedding':True,'context_limit':8192})
        self.manager.asset=AsyncMock(return_value={'files':[{'kind':'model','path':self.root/'model'}]})
        self.manager._embedding_receipt=('verified',)
        self.script=self.root/'worker.py'
        self.script.write_text('''import sys,struct,json,time,os
from pathlib import Path
Path(sys.argv[1]).write_text(str(os.getpid()))
def send(data):
 raw=json.dumps(data).encode();sys.stdout.buffer.write(struct.pack('>I',len(raw))+raw);sys.stdout.buffer.flush()
if Path(sys.argv[2]+'/wait-ready').exists():time.sleep(60)
send({'ready':True,'dim':768,'pooling':'mean','context_tokens':2048,'engine':''' + repr(EMBEDDING_ENGINE)+'''})
while head:=sys.stdin.buffer.read(4):
 size=struct.unpack('>I',head)[0];text=sys.stdin.buffer.read(size).decode()
 if text=='wait':time.sleep(60)
 if text=='limit':send({'error':{'code':'context_limit'},'fatal':False});continue
 if text=='bad':send({'vector':[0]*768});continue
 if text=='fatal-limit':send({'error':{'code':'context_limit'},'fatal':True});continue
 send({'vector':[1.0]+[0.0]*767})
''')
        original=self.manager._spawn;self.children=[]
        async def spawn(argv):
            process=await original([sys.executable,str(self.script),str(self.root/'pid'),str(self.root)])
            self.children.append(process);return process
        self.manager._spawn=spawn

    def client(self,before=None):return DirectEmbeddings(self.manager,before,reuse=True)

    async def test_three_inputs_reuse_one_worker_and_close_at_scope_end(self):
        before=AsyncMock();client=self.client(before)
        for _ in range(3):self.assertEqual(len(await client.embed('embeddinggemma','한국어')),768)
        self.assertEqual(len(self.children),1);self.assertEqual(before.await_count,6)
        self.assertIsNone(self.children[0].returncode)
        await client.close()
        self.assertIsNotNone(self.children[0].returncode);self.assertFalse(self.manager.processes)

    async def test_single_calls_do_not_retain_and_cannot_borrow_another_job(self):
        first,second=self.client(),self.client()
        await first.embed('embeddinggemma','one');await second.embed('embeddinggemma','two')
        self.assertEqual(len(self.children),2);self.assertIsNotNone(self.children[0].returncode)
        await first.close();self.assertIsNone(self.children[1].returncode)
        await self.manager.embed('embeddinggemma','query')
        self.assertTrue(all(p.returncode is not None for p in self.children));self.assertFalse(self.manager.processes)

    async def test_limit_retries_keep_worker_but_bad_or_fatal_results_close_it(self):
        client=self.client()
        with self.assertRaises(EmbeddingInputTooLong):await client.embed('embeddinggemma','limit')
        await client.embed('embeddinggemma','split part');self.assertEqual(len(self.children),1)
        with self.assertRaises(ValueError):await client.embed('embeddinggemma','bad')
        self.assertFalse(self.manager.processes)
        with self.assertRaises(ValueError)as error:await client.embed('embeddinggemma','fatal-limit')
        self.assertNotIsInstance(error.exception,EmbeddingInputTooLong);self.assertFalse(self.manager.processes)

    async def test_changed_model_or_engine_closes_worker_and_rejects_scope(self):
        for change in ('model','engine'):
            with self.subTest(change=change):
                client=self.client();await client.embed('embeddinggemma','first')
                if change=='model':self.manager.status.return_value['digest']='b'*64
                else:self.manager._embedding_receipt=('changed',)
                with self.assertRaises(ValueError):await client.embed('embeddinggemma','second')
                self.assertFalse(self.manager.processes)
                self.manager.status.return_value['digest']='a'*64;self.manager._embedding_receipt=('verified',)

    async def test_generation_releases_worker_before_loading_and_can_interleave(self):
        client=self.client();await client.embed('embeddinggemma','first')
        async def view(model):
            self.assertFalse(self.manager.processes);return self.root
        self.manager.view=view;self.manager._call=AsyncMock(return_value={'text':'{}','usage':{}})
        await self.manager.generate(ProviderConfig(provider='local',model='qwen3.5:4b'),[{'role':'user','content':'요약'}],[],None,output_limit=20)
        self.assertFalse(self.manager.processes)
        await client.embed('embeddinggemma','resumed');self.assertEqual(len(self.children),2)
        await client.close()

    async def test_explicit_pause_releases_worker_and_resume_reloads(self):
        client=self.client();await client.embed('embeddinggemma','first');await client.close()
        self.assertFalse(self.manager.processes)
        await client.embed('embeddinggemma','resumed');self.assertEqual(len(self.children),2)
        await self.manager.stop();self.assertFalse(self.manager.processes)

    async def test_cancel_ready_inference_and_admission_reaps_owned_process(self):
        for stage in ('ready','inference','admission'):
            with self.subTest(stage=stage):
                client=self.client();entered=asyncio.Event()
                if stage=='ready':(self.root/'wait-ready').touch()
                if stage=='admission':
                    await client.embed('embeddinggemma','loaded')
                    async def wait():entered.set();await asyncio.sleep(60)
                    client.before_request=wait
                task=asyncio.create_task(client.embed('embeddinggemma','wait'if stage=='inference'else'first'))
                for _ in range(200):
                    if (stage=='admission'and entered.is_set())or(stage!='admission'and self.manager.processes):break
                    await asyncio.sleep(.005)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):await task
                self.assertFalse(self.manager.processes)
                (self.root/'wait-ready').unlink(missing_ok=True)

    async def app(self):
        import httpx
        from lecture_study.config import AppConfig
        from lecture_study.server import create_app
        app=create_app(AppConfig(self.root/'vault',self.root/'runtime',embedded=True))
        app.state.direct_models=self.manager
        self.addCleanup(app.state.instance_lock.close);self.addCleanup(app.state.db.close)
        async def stop():
            for task in list(app.state.tasks):task.cancel()
            await asyncio.gather(*app.state.tasks,return_exceptions=True)
        self.addAsyncCleanup(stop)
        client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:8765')
        self.addAsyncCleanup(client.aclose)
        headers={'Origin':'http://127.0.0.1:8765'}
        login=await client.post('/api/bootstrap',json={'token':app.state.bootstrap_token},headers=headers)
        headers['X-Session-Token']=login.json()['csrf_token']
        from lecture_study.db import create_session
        from lecture_study.materials import save_note
        sid=create_session(app.state.db,'lecture','색인',None,None).id
        save_note(app.state.db,sid,'\n\n'.join('한국어 원문 '+str(i)for i in range(3)))
        self.assertEqual(app.state.db.execute('select count(*)from searchable_chunks').fetchone()[0],3)
        return app,client,headers,sid

    async def job(self,client,ident,predicate):
        for _ in range(300):
            row=(await client.get('/api/jobs/'+ident)).json()
            if predicate(row):return row
            await asyncio.sleep(.005)
        self.fail('job did not reach expected state: '+str(row))

    async def test_api_rebuild_owns_one_worker_and_releases_at_completion(self):
        app,client,headers,sid=await self.app()
        submitted=await client.post('/api/index/rebuild',json={'session_id':sid,'model':'embeddinggemma'},headers=headers)
        self.assertEqual(submitted.status_code,202,submitted.text)
        job=await self.job(client,submitted.json()['id'],lambda j:j['status']in ('done','failed'))
        self.assertEqual(job['status'],'done',job)
        self.assertEqual(len(self.children),1);self.assertFalse(self.manager.processes)
        self.assertEqual(app.state.active_embedding_clients,0)

    async def test_recording_pause_releases_and_resume_prepares_new_worker(self):
        from lecture_study.audio import start_recording,stop_recording
        app,client,headers,sid=await self.app();original=self.manager.embed;rid=None
        async def embed(*args,**kwargs):
            nonlocal rid
            result=await original(*args,**kwargs)
            if rid is None:rid=start_recording(app.state.db,sid,16000)
            return result
        self.manager.embed=embed
        submitted=await client.post('/api/index/rebuild',json={'session_id':sid,'model':'embeddinggemma'},headers=headers)
        ident=submitted.json()['id']
        await self.job(client,ident,lambda j:bool((j['result']or{}).get('paused_reason')))
        self.assertFalse(self.manager.processes)
        stop_recording(app.state.db,rid)
        job=await self.job(client,ident,lambda j:j['status']in ('done','failed'))
        self.assertEqual(job['status'],'done',job);self.assertEqual(len(self.children),2)
        self.assertFalse(self.manager.processes)

    async def test_transcript_arriving_after_chunk_check_releases_before_wait_and_cancel(self):
        from lecture_study.audio import start_recording,append_pcm
        from lecture_study.transcription import plan_chunks
        app,client,headers,sid=await self.app();original=self.manager.embed;count=0
        with app.state.db:
            app.state.db.execute("INSERT INTO embedding_sets VALUES ('old','embeddinggemma',?,768,?,'ready','2026-10-19')",('a'*64,EMBEDDING_FORMAT))
            app.state.db.execute("INSERT INTO settings VALUES ('active_embedding_index','\"old\"')")
        async def embed(*args,**kwargs):
            nonlocal count
            count+=1
            if count==2:
                rid=start_recording(app.state.db,sid,16000)
                append_pcm(app.state.db,rid,0,0,16000,b'\1\0'*16000);plan_chunks(app.state.db,rid,stopping=True)
            return await original(*args,**kwargs)
        self.manager.embed=embed
        submitted=await client.post('/api/index/rebuild',json={'session_id':sid,'model':'embeddinggemma'},headers=headers)
        ident=submitted.json()['id']
        await self.job(client,ident,lambda j:(j['result']or{}).get('paused_reason')=='녹음·전사 중 · 색인 대기')
        self.assertFalse(self.manager.processes)
        result=await client.post('/api/jobs/'+ident+'/cancel',headers=headers)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(app.state.active_embedding_clients,0);self.assertFalse(self.manager.processes)
        self.assertEqual(json.loads(app.state.db.execute("select value from settings where key='active_embedding_index'").fetchone()[0]),'old')
        self.assertEqual(app.state.db.execute("select count(*)from embedding_sets where status='building'").fetchone()[0],0)

    async def test_timeout_closes_retained_worker(self):
        client=self.client();await client.embed('embeddinggemma','first')
        with patch('lecture_study.direct_models.read_result',new=AsyncMock(side_effect=TimeoutError)):
            with self.assertRaisesRegex(ValueError,'제한 시간'):await client.embed('embeddinggemma','second')
        self.assertFalse(self.manager.processes)

    async def test_repeated_cancellation_waits_for_process_reaping(self):
        from unittest.mock import Mock
        release=asyncio.Event();entered=asyncio.Event();reaped=False
        async def wait():
            nonlocal reaped
            entered.set();await release.wait();reaped=True
        process=Mock(returncode=None);process.wait=wait
        self.manager.processes.add(process)
        task=asyncio.create_task(self.manager._close(process));await entered.wait()
        task.cancel();await asyncio.sleep(0);task.cancel();await asyncio.sleep(0)
        self.assertFalse(task.done())
        release.set()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(reaped);self.assertFalse(self.manager.processes)

    async def test_recording_start_during_model_lock_wait_does_not_start_index_worker(self):
        from lecture_study.audio import start_recording
        app,client,headers,sid=await self.app();original=self.manager.embed;entered=asyncio.Event()
        async def embed(*args,**kwargs):
            entered.set();return await original(*args,**kwargs)
        self.manager.embed=embed
        await self.manager.lock.acquire()
        submitted=await client.post('/api/index/rebuild',json={'session_id':sid,'model':'embeddinggemma'},headers=headers)
        await entered.wait();start_recording(app.state.db,sid,16000);self.manager.lock.release()
        ident=submitted.json()['id']
        await self.job(client,ident,lambda j:bool((j['result']or{}).get('paused_reason')))
        self.assertFalse(self.children);self.assertFalse(self.manager.processes)
        await client.post('/api/jobs/'+ident+'/cancel',headers=headers)

    async def test_final_status_rejects_engine_changed_after_last_vector(self):
        client=self.client();await client.embed('embeddinggemma','first')
        self.manager._embedding_receipt=('changed after last vector',)
        with self.assertRaises(ValueError):await client.status('embeddinggemma')
        self.assertFalse(self.manager.processes)
