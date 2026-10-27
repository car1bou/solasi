import asyncio,json,tempfile,unittest
from pathlib import Path
from unittest.mock import AsyncMock,patch
import httpx
from lecture_study.config import AppConfig
from lecture_study.db import create_session
from lecture_study.jobs import submit_job,get_job
from lecture_study.models import AIRequest,ProviderConfig,Scope
from lecture_study.materials import save_note
from lecture_study.server import create_app


class SingleLocalModelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.app=create_app(AppConfig(self.root,self.root/'runtime',port=8765,embedded=True));self.db=self.app.state.db
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url='http://127.0.0.1:8765')
        self.auth={'Origin':'http://127.0.0.1:8765'}
        login=await self.client.post('/api/bootstrap',json={'token':self.app.state.bootstrap_token},headers=self.auth);self.auth['X-Session-Token']=login.json()['csrf_token']
        self.app.state.direct_models.available=AsyncMock(return_value={'connected':True})
        self.app.state.direct_models.status=AsyncMock(return_value={'completion':True,'vision':True,'digest':'a'*64})

    async def asyncTearDown(self):
        for task in list(self.app.state.tasks):task.cancel()
        await asyncio.gather(*self.app.state.tasks,return_exceptions=True)
        await self.app.state.direct_models.stop();await self.client.aclose();self.db.close();self.temp.cleanup()

    def test_catalog_and_direct_support_have_one_generation_model(self):
        from lecture_study.local_models import CATALOG
        from lecture_study.mlx_direct import SUPPORTED_MODELS
        self.assertEqual({m for m in CATALOG if not m.startswith('embedding')},{'qwen3.5:4b'})
        self.assertEqual(set(SUPPORTED_MODELS),{'qwen3.5:4b'});self.assertIn('embeddinggemma',CATALOG)

    async def test_old_local_setting_normalizes_new_requests_without_rewriting_history(self):
        for provider in ('local','ollama'):
            original=ProviderConfig(provider=provider,model='gemma4:12b').model_dump_json()
            with self.db:self.db.execute("INSERT OR REPLACE INTO settings VALUES ('provider',?)",(original,))
            result=await self.client.get('/api/settings');self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(result.json()['provider']['model'],'qwen3.5:4b');self.assertEqual(result.json()['provider']['provider'],'local')
            self.assertEqual(self.db.execute("SELECT value FROM settings WHERE key='provider'").fetchone()[0],original)
        api={'provider':'openai','model':'custom-api-model','context_limit':16384}
        saved=await self.client.put('/api/settings',json=api,headers=self.auth);self.assertEqual(saved.status_code,200,saved.text)
        self.assertEqual((await self.client.get('/api/settings')).json()['provider']['model'],'custom-api-model')

    async def test_other_local_model_cannot_be_configured_or_downloaded(self):
        with patch.object(self.app.state.direct_models,'pull',new=AsyncMock())as pull:
            for name in ('gemma4:12b','gemma4:e2b','qwen3.5:9b','arbitrary'):
                result=await self.client.put('/api/settings',json={'provider':'local','model':name},headers=self.auth)
                self.assertEqual(result.status_code,422,result.text)
                result=await self.client.post('/api/local/pull',json={'model':name,'runner':'mlx','confirmed':True},headers=self.auth)
                self.assertEqual(result.status_code,422,result.text)
            pull.assert_not_called()

    async def test_retired_job_is_preserved_and_current_local_retry_creates_new_job(self):
        sid=create_session(self.db,'lecture','검증',None,None).id;save_note(self.db,sid,'누적분포함수의 정의')
        request=AIRequest(session_id=sid,kind='answer',prompt='정의',scope=Scope(session_id=sid),provider=ProviderConfig(provider='local',model='gemma4:12b'))
        old=submit_job(self.db,sid,'ai',{'request':request.model_dump(),'snapshot':{}})
        with self.db:self.db.execute("UPDATE jobs SET status='failed' WHERE id=?",(old['id'],))
        baseline=get_job(self.db,old['id'])
        with patch('lecture_study.server.launch_job',side_effect=lambda app,job,operation:job):
            same=await self.client.post('/api/jobs/'+old['id']+'/retry',headers=self.auth)
            self.assertEqual(same.status_code,422,same.text);self.assertIn('현재 로컬 AI',same.json()['detail'])
            with patch('lecture_study.server.model_status',new=AsyncMock(return_value={'completion':True,'vision':True})):
                result=await self.client.post('/api/jobs/'+old['id']+'/retry-local',json={},headers=self.auth)
            self.assertEqual(result.status_code,200,result.text);fresh=result.json();self.assertNotEqual(fresh['id'],old['id'])
            self.assertEqual(fresh['request']['request']['provider']['model'],'qwen3.5:4b')
        self.assertEqual(get_job(self.db,old['id']),baseline)

    async def test_removed_gemma_ocr_engine_rejected_before_page_read(self):
        result=await self.client.post('/api/courses/'+'a'*32+'/assets/'+'b'*32+'/pages/1/handwriting',json={'document_sha256':'c'*64,'engine':'gemma'},headers=self.auth)
        self.assertEqual(result.status_code,422,result.text)
