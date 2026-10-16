import asyncio
import hashlib
import struct
import httpx
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from lecture_study.direct_models import DirectModels, DirectEmbeddings, EMBEDDING_FORMAT, model_identity
from lecture_study.models import ProviderConfig, Scope
from lecture_study.providers import generate
from lecture_study.db import open_db, create_session
from lecture_study.materials import save_note
from lecture_study.retrieval import rebuild_embeddings, retrieve


class DirectModelTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manager = DirectModels(self.root/'runtime', self.root/'cache')
        self.config = ProviderConfig(provider='local', model='qwen3.5:4b', vision=True)

    async def test_unsupported_and_missing_assets_are_not_ready(self):
        for model in ('gemma4:12b', 'unknown', 'qwen3.5:4b'):
            with self.assertRaises(ValueError):
                await self.manager.status(model)
        self.assertNotEqual(model_identity('qwen3.5:4b', 'a'*64), 'a'*64)

    async def test_local_provider_validates_output_and_preserves_limits(self):
        status = {'digest': 'd'*64, 'vision': True, 'completion': True}
        self.manager.status = AsyncMock(return_value=status)
        self.manager.generate = AsyncMock(return_value={'text': '{"answer":"답"}', 'usage': {'eval_count': 3}, 'finish_reason': 'stop'})
        before = AsyncMock()
        response = await generate(self.config, [{'role':'user','content':'질문'}], [], {'type':'object'}, direct_models=self.manager, before_local=before, output_limit=512, expected_digest='d'*64)
        self.assertEqual(response.digest, 'd'*64)
        self.assertEqual(response.text, '{"answer":"답"}')
        self.assertEqual(self.manager.generate.call_args.kwargs['output_limit'], 512)
        for result in ({'text':'{}','usage':{},'finish_reason':'length'}, {'text':'bad','usage':{},'finish_reason':'stop'}):
            self.manager.generate.return_value = result
            with self.assertRaises(ValueError):
                await generate(self.config, [{'role':'user','content':'질문'}], [], {'type':'object'}, direct_models=self.manager)
        self.manager.generate.reset_mock()
        with self.assertRaises(ValueError):
            await generate(self.config, [{'role':'user','content':'질문'}], [], None, direct_models=self.manager, expected_digest='b'*64)
        self.manager.generate.assert_not_called()

    async def test_missing_execution_engine_is_unavailable_and_exited_child_is_reaped(self):
        self.manager.python=str(self.root/'absent-python')
        self.manager.asset=AsyncMock(return_value={'digest':'a'*64})
        with self.assertRaises(ValueError):await self.manager.status('qwen3.5:4b')
        child=Mock(returncode=None)
        child.terminate.side_effect=ProcessLookupError()
        child.wait=AsyncMock(return_value=0)
        self.manager.processes.add(child)
        await self.manager._close(child)
        child.wait.assert_awaited_once()
        self.assertFalse(self.manager.processes)

    async def test_generation_subprocess_is_reaped_on_cancel(self):
        script = self.root/'wait.py'
        script.write_text('import os,time\nfrom pathlib import Path\nPath('+repr(str(self.root/'pid'))+').write_text(str(os.getpid()))\ntime.sleep(60)\n')
        self.manager._generation_command = lambda: [sys.executable, str(script)]
        self.manager.status = AsyncMock(return_value={'digest':'d'*64,'vision':True,'completion':True,'context_limit':8192})
        self.manager.view = AsyncMock(return_value=self.root)
        task = asyncio.create_task(self.manager.generate(self.config, [{'role':'user','content':'질문'}], [], None, output_limit=20))
        for _ in range(100):
            if (self.root/'pid').exists(): break
            await asyncio.sleep(.01)
        self.assertTrue((self.root/'pid').exists())
        pid = int((self.root/'pid').read_text())
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        with self.assertRaises(ProcessLookupError): os.kill(pid, 0)
        self.assertEqual(self.manager.processes, set())

    async def test_actual_child_contract_and_admission(self):
        script = self.root/'reply.py'
        script.write_text('''import json,struct,sys
n=struct.unpack('>I',sys.stdin.buffer.read(4))[0]
request=json.loads(sys.stdin.buffer.read(n))
assert request['output_limit']==123 and request['context_limit']==8192
reply=json.dumps({'ok':True,'result':{'text':'완료','usage':{'eval_count':1},'finish_reason':'stop'}}).encode()
sys.stdout.buffer.write(struct.pack('>I',len(reply))+reply);sys.stdout.buffer.flush()
''')
        self.manager._generation_command = lambda: [sys.executable, str(script)]
        self.manager.status = AsyncMock(return_value={'digest':'d'*64,'vision':True,'completion':True,'context_limit':8192})
        self.manager.view = AsyncMock(return_value=self.root)
        before = AsyncMock()
        result = await self.manager.generate(self.config, [{'role':'user','content':'질문'}], [], None, output_limit=123, before_local=before)
        self.assertEqual(result['text'], '완료')
        before.assert_awaited_once()
        self.assertEqual(self.manager.processes, set())

    async def test_new_embedding_index_preserves_old_set_and_refuses_mixing(self):
        db = open_db(self.root/'data')
        self.addCleanup(db.close)
        sid = create_session(db, 'lecture', '운영체제', None, None).id
        save_note(db, sid, '프로세스는 실행 중인 프로그램입니다.')
        old = 'old-index'
        with db:
            db.execute("INSERT INTO embedding_sets VALUES (?,?,?,? ,?,'ready',?)", (old,'embeddinggemma','a'*64,2,'embeddinggemma-search-v1/chunk512-v1','2026-10-16'))
            db.execute("INSERT INTO settings VALUES ('active_embedding_index',?)", (json.dumps(old),))
        self.manager.status = AsyncMock(return_value={'digest':'b'*64,'embedding':True})
        self.manager.embed = AsyncMock(return_value=[1.0,0.0])
        before = AsyncMock()
        client = DirectEmbeddings(self.manager, before)
        result = await retrieve(db, '프로세스', Scope(session_id=sid), None, client=client)
        self.assertEqual(result.mode, 'keyword')
        self.manager.embed.assert_not_called()
        new = await rebuild_embeddings(db, 'embeddinggemma', client)
        self.assertEqual(new['format'], EMBEDDING_FORMAT)
        self.assertNotEqual(new['index_id'], old)
        self.assertIsNotNone(db.execute('SELECT * FROM embedding_sets WHERE id=?',(old,)).fetchone())
        await retrieve(db, '프로세스', Scope(session_id=sid), None, client=client)
        self.assertTrue(self.manager.embed.call_args.args[1].startswith('task: search result | query: '))
        self.assertIs(self.manager.embed.call_args.kwargs['before_local'],before)

    async def test_model_view_rejects_extra_index_entries(self):
        config=self.root/'config.json';config.write_text('{}')
        weight=self.root/'tensor';weight.write_bytes(b'fixture')
        asset={'digest':'a'*64,'format':'safetensors','files':[{'kind':'json','name':'config.json','path':config},{'kind':'tensor','path':weight,'tensors':{'weight':{}}}]}
        self.manager.asset=AsyncMock(return_value=asset)
        view=await self.manager.view('qwen3.5:4b')
        index=view/'model.safetensors.index.json';value=json.loads(index.read_text())
        value['weight_map']['injected.weight']='model-00001.safetensors'
        index.write_text(json.dumps(value))
        with self.assertRaises(ValueError):await self.manager.view('qwen3.5:4b')

    async def test_incomplete_old_view_is_preserved_and_retry_rebuilds_it(self):
        config=self.root/'config.json';config.write_text('{}')
        weight=self.root/'tensor';weight.write_bytes(b'fixture')
        asset={'digest':'a'*64,'format':'safetensors','files':[{'kind':'json','name':'config.json','path':config},{'kind':'tensor','path':weight,'tensors':{'weight':{}}}]}
        self.manager.asset=AsyncMock(return_value=asset)
        destination=self.manager.cache_dir/asset['digest'];destination.mkdir(parents=True)
        (destination/'config.json').write_bytes(config.read_bytes())
        before={p:(p.read_bytes(),p.stat().st_mtime_ns)for p in (config,weight)}
        view=await self.manager.view('qwen3.5:4b')
        self.assertEqual(view,destination)
        self.assertTrue((view/'model.safetensors.index.json').is_file())
        preserved=list(self.manager.cache_dir.glob('.incomplete-*/previous/config.json'))
        self.assertEqual(len(preserved),1)
        self.assertEqual(preserved[0].read_bytes(),config.read_bytes())
        self.assertFalse((preserved[0].parent/'model.safetensors.index.json').exists())
        self.assertEqual(before,{p:(p.read_bytes(),p.stat().st_mtime_ns)for p in before})
        self.assertEqual(await self.manager.view('qwen3.5:4b'),view)
        (view/'model.safetensors.index.json').write_text('{\"weight_map\":')
        self.assertEqual(await self.manager.view('qwen3.5:4b'),view)
        self.assertEqual(len(list(self.manager.cache_dir.glob('.incomplete-*/previous'))),2)
        self.assertEqual(before,{p:(p.read_bytes(),p.stat().st_mtime_ns)for p in before})

    async def test_embedding_admission_occurs_after_waiting_for_model_lock(self):
        self.manager.status=AsyncMock(side_effect=ValueError('fixture ends before loading'))
        before=AsyncMock()
        await self.manager.lock.acquire()
        task=asyncio.create_task(DirectEmbeddings(self.manager,before).embed('embeddinggemma','발화'))
        await asyncio.sleep(.01)
        before.assert_not_awaited()
        self.manager.lock.release()
        with self.assertRaises(ValueError):await task
        before.assert_awaited_once()

    async def test_receipt_rejects_library_alias_outside_verified_files(self):
        import lecture_study.direct_models as direct
        engine=self.root/'engine';(engine/'lib').mkdir(parents=True)
        binary=engine/'EmbeddingWorker';binary.write_bytes(b'fixture')
        receipt={'engine':direct.EMBEDDING_ENGINE,'revision':'620d2225cc436ab0b001e3200e590e3b286ef9ab','architecture':'arm64','files':{'EmbeddingWorker':{'bytes':7,'sha256':hashlib.sha256(b'fixture').hexdigest()}}}
        (engine/'receipt.json').write_text(json.dumps(receipt))
        self.manager.engine_dir=engine
        outside=self.root/'unverified.dylib';outside.write_bytes(b'changed')
        (engine/'lib/libllama.dylib').symlink_to(outside)
        with self.assertRaises(ValueError):self.manager.check_embedding_engine()

    async def test_verified_download_needs_no_model_server_and_bad_blob_preserves_manifest(self):
        import lecture_study.direct_models as direct
        from lecture_study.local_models import CATALOG
        weights=b'GGUF'+struct.pack('<I',3)
        config=b'{}'
        weight_sha=hashlib.sha256(weights).hexdigest()
        config_sha=hashlib.sha256(config).hexdigest()
        manifest=json.dumps({'schemaVersion':2,'config':{'digest':'sha256:'+config_sha,'size':len(config)},'layers':[{'digest':'sha256:'+weight_sha,'size':len(weights),'mediaType':'application/vnd.ollama.image.model'}]}).encode()
        digest=hashlib.sha256(manifest).hexdigest()
        seen=[]
        def respond(request):
            seen.append(str(request.url))
            self.assertEqual(request.url.host,'registry.ollama.ai')
            if '/manifests/' in request.url.path:return httpx.Response(200,content=manifest)
            return httpx.Response(200,content=config if request.url.path.endswith(config_sha) else weights)
        with patch.dict(CATALOG,{'embeddinggemma':{'license':'Gemma Terms','runners':{'ggml':{'bytes':10,'digest':digest}}}}),patch.object(direct,'EMBEDDING_WEIGHT',weight_sha):
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                await self.manager.pull('embeddinggemma','ggml',client=client)
            self.assertEqual(self.manager.progress['status'],'done')
            target=self.manager.runtime/'ollama-models/manifests/registry.ollama.ai/library/embeddinggemma/latest'
            self.assertEqual(target.read_bytes(),manifest)
            self.assertTrue(seen)
            previous=target.read_bytes()
            # A failed retry cannot replace a verified manifest with a partial download.
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(200,content=b'bad'))) as client:
                await self.manager.pull('embeddinggemma','ggml',client=client)
            self.assertEqual(self.manager.progress['status'],'failed')
            self.assertEqual(target.read_bytes(),previous)
            bad_manifest=json.dumps(json.loads(manifest)|{'schemaVersion':3}).encode()
            bad_digest=hashlib.sha256(bad_manifest).hexdigest()
            with patch.dict(CATALOG,{'embeddinggemma':{'runners':{'ggml':{'bytes':10,'digest':bad_digest}}}}):
                async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(200,content=bad_manifest))) as client:
                    await self.manager.pull('embeddinggemma','ggml',client=client)
            self.assertEqual(self.manager.progress['status'],'failed')
            self.assertEqual(target.read_bytes(),previous)

    async def test_local_frozen_summary_keeps_extract_policy(self):
        from lecture_study.answers import capture_request, freeze_request
        from lecture_study.models import AIRequest
        db = open_db(self.root/'data')
        self.addCleanup(db.close)
        sid = create_session(db, 'lecture', '조건', None, None).id
        save_note(db, sid, '부모님이 돌아가신다면이라는 가정을 설명했습니다.')
        request = AIRequest(session_id=sid,kind='summary',prompt='요약',scope=Scope(session_id=sid),provider=self.config)
        frozen = await freeze_request(db,request,snapshot=capture_request(db,request))
        self.assertEqual(frozen['summary_format'], 'excerpts-v1')

    async def test_old_ollama_retry_remains_unchanged_in_embedded_app(self):
        import httpx
        from lecture_study.config import AppConfig
        from lecture_study.server import create_app
        from lecture_study.jobs import submit_job
        app = create_app(AppConfig(self.root/'vault',self.root/'runtime',embedded=True))
        async with app.router.lifespan_context(app):
            db = app.state.db
            sid = create_session(db,'lecture','이전 요청',None,None).id
            original = {'request':{'provider':{'provider':'ollama','model':'qwen3.5:4b'}},'summary_parts':[]}
            job = submit_job(db,sid,'ai',original)
            with db: db.execute("UPDATE jobs SET status='interrupted' WHERE id=?",(job['id'],))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:8765') as client:
                headers={'Origin':'http://127.0.0.1:8765'}
                login=await client.post('/api/bootstrap',json={'token':app.state.bootstrap_token},headers=headers)
                headers['X-Session-Token']=login.json()['csrf_token']
                response=await client.post('/api/jobs/'+job['id']+'/retry',headers=headers)
                self.assertEqual(response.status_code,422)
                self.assertEqual(json.loads(db.execute('SELECT request FROM jobs WHERE id=?',(job['id'],)).fetchone()[0]), original)
                self.assertEqual((await client.get('/api/settings')).json()['provider']['provider'],'local')
