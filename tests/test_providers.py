import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from lecture_study.models import ProviderConfig
from lecture_study.providers import generate,model_status
from lecture_study.credentials import Secrets

SCHEMA={'type':'object','properties':{'answer':{'type':'string'}},'required':['answer'],'additionalProperties':False}

class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_providers_map_text_images_usage_and_complete_only(self):
        with tempfile.TemporaryDirectory() as folder:
            image=Path(folder)/'image.png';image.write_bytes(b'\x89PNG\r\n\x1a\nfixture')
            for provider,model in [('openai','gpt-4.1-mini'),('gemini','gemini-2.5-flash'),('claude','claude-sonnet-4-20250514'),('ollama','qwen3.5:4b')]:
                with self.subTest(provider=provider):
                    requests=[]
                    def respond(request):
                        requests.append(request)
                        if request.url.path=='/api/tags': return httpx.Response(200,json={'models':[{'name':model,'digest':'a'*64}]})
                        if request.url.path=='/api/show': return httpx.Response(200,json={'capabilities':['completion','vision']})
                        if provider=='openai': body={'status':'completed','model':model,'output':[{'type':'message','content':[{'type':'output_text','text':'{"answer":"답"}'}]}],'usage':{'input_tokens':10,'output_tokens':3}}
                        elif provider=='gemini': body={'modelVersion':model,'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'{"answer":"답"}'}]}}],'usageMetadata':{'promptTokenCount':10,'candidatesTokenCount':3}}
                        elif provider=='claude': body={'model':model,'stop_reason':'end_turn','content':[{'type':'text','text':'{"answer":"답"}'}],'usage':{'input_tokens':10,'output_tokens':3}}
                        else: body={'done':True,'model':model,'message':{'content':'{"answer":"답"}'},'prompt_eval_count':10,'eval_count':3}
                        return httpx.Response(200,json=body)
                    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                        result=await generate(ProviderConfig(provider=provider,model=model,vision=True),[{'role':'system','content':'규칙'},{'role':'user','content':'질문'}],[image],SCHEMA,client=client,secret='test-key',ollama_url='http://127.0.0.1:11435',source_copy=True)
                    self.assertEqual(json.loads(result.text),{'answer':'답'});self.assertEqual(result.model,model)
                    self.assertTrue(result.usage);self.assertGreaterEqual(result.elapsed_ms,0)
                    sent=next(r for r in reversed(requests) if r.method=='POST' and r.url.path!='/api/show')
                    self.assertEqual(result.digest,'a'*64 if provider=='ollama' else None)
                    payload=json.loads(sent.content)
                    if provider!='ollama':
                        for key in ('options','temperature','presence_penalty'):self.assertNotIn(key,payload.get('generationConfig',payload))
                    self.assertIn('질문',sent.content.decode());self.assertNotIn(str(image),sent.content.decode())
                    if provider=='openai':
                        self.assertFalse(payload['store']);self.assertEqual(payload['text']['format']['type'],'json_schema')
                        self.assertTrue(payload['input'][0]['content'][1]['image_url'].startswith('data:image/png;base64,'))
                    elif provider=='gemini':
                        self.assertIn('inlineData',payload['contents'][0]['parts'][1]);self.assertEqual(payload['generationConfig']['responseJsonSchema'],SCHEMA)
                    elif provider=='claude':
                        self.assertEqual(payload['output_config']['format']['schema'],SCHEMA);self.assertEqual(payload['messages'][0]['content'][1]['source']['type'],'base64')
                    else:
                        self.assertEqual(payload['options']['num_ctx'],8192);self.assertFalse(payload['stream']);self.assertFalse(payload['think'])
                        self.assertEqual(payload['format'],SCHEMA);self.assertIn('images',payload['messages'][-1])

    async def test_internal_output_budget_reaches_every_provider(self):
        for provider in ('openai','gemini','claude','ollama'):
            seen=[]
            def respond(request):
                if request.url.path=='/api/tags':return httpx.Response(200,json={'models':[{'name':'test','digest':'a'*64}]})
                if request.url.path=='/api/show':return httpx.Response(200,json={'capabilities':['completion']})
                seen.append(json.loads(request.content))
                text='{"answer":"답"}'
                return httpx.Response(200,json={'model':'test','status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':text}]}],'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':text}]}}],'stop_reason':'end_turn','content':[{'type':'text','text':text}],'done':True,'message':{'content':text}})
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond))as client:
                await generate(ProviderConfig(provider=provider,model='test'),[{'role':'user','content':'질문'}],[],SCHEMA,client=client,secret='test-key',ollama_url='http://127.0.0.1:11435',output_limit=2048)
            payload=seen[0]
            actual=payload['options']['num_predict']if provider=='ollama'else payload['generationConfig']['maxOutputTokens']if provider=='gemini'else payload['max_tokens']if provider=='claude'else payload['max_output_tokens']
            self.assertEqual(actual,2048)
        for invalid in (0,4097,True):
            with self.assertRaisesRegex(ValueError,'출력'):await generate(ProviderConfig(),[],[],None,output_limit=invalid)

    async def test_summary_tokenizer_digest_mismatch_stops_before_chat(self):
        seen=[]
        def respond(request):
            seen.append(request.url.path)
            return httpx.Response(200,json={'models':[{'name':'test','digest':'a'*64}]}) if request.url.path=='/api/tags' else httpx.Response(200,json={'capabilities':['completion']})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond))as client:
            with self.assertRaisesRegex(ValueError,'토크나이저'):await generate(ProviderConfig(provider='ollama',model='test'),[{'role':'user','content':'원문'}],[],SCHEMA,client=client,ollama_url='http://127.0.0.1:11435',expected_digest='b'*64)
        self.assertNotIn('/api/chat',seen)

    async def test_model_change_while_waiting_stops_before_chat(self):
        seen=[];digest='a'*64
        def respond(request):
            seen.append(request.url.path)
            if request.url.path=='/api/tags':return httpx.Response(200,json={'models':[{'name':'test','digest':digest}]})
            if request.url.path=='/api/show':return httpx.Response(200,json={'capabilities':['completion']})
            return httpx.Response(200,json={'done':True,'message':{'content':'{"answer":"답"}'}})
        async def wait():
            nonlocal digest
            digest='b'*64
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond))as client:
            with self.assertRaises(ValueError):await generate(ProviderConfig(provider='ollama',model='test'),[{'role':'user','content':'원문'}],[],SCHEMA,client=client,ollama_url='http://127.0.0.1:11435',expected_digest='a'*64,before_local=wait)
        self.assertNotIn('/api/chat',seen)

    async def test_claude_transport_omits_unsupported_array_limits_without_mutating_contract(self):
        from lecture_study.outputs import QUIZ_SCHEMA
        original=json.dumps(QUIZ_SCHEMA)
        def inspect(node):
            if isinstance(node,dict):
                if node.get('type')=='array':
                    self.assertNotIn('maxItems',node)
                    self.assertIn(node.get('minItems',0),(0,1))
                for value in node.values():inspect(value)
            elif isinstance(node,list):
                for value in node:inspect(value)
        def respond(request):
            sent=json.loads(request.content)['output_config']['format']['schema'];inspect(sent)
            self.assertIn('anyOf',sent['properties']['questions']['items'])
            return httpx.Response(200,json={'model':'test','stop_reason':'end_turn','content':[{'type':'text','text':'{"answer":"답"}'}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            await generate(ProviderConfig(provider='claude',model='claude-sonnet-4'),[{'role':'user','content':'질문'}],[],QUIZ_SCHEMA,client=client,secret='test-key')
        self.assertEqual(json.dumps(QUIZ_SCHEMA),original)

    async def test_errors_are_safe_and_do_not_switch_providers(self):
        for status in (401,429,500):
            seen=[]
            def respond(request):
                seen.append(request.url.host)
                return httpx.Response(status,json={'error':{'message':'test-key private prompt'}})
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                with self.assertRaises(ValueError) as raised:
                    await generate(ProviderConfig(provider='openai',model='gpt-4.1-mini'),[{'role':'user','content':'민감내용'}],[],SCHEMA,client=client,secret='test-key')
            self.assertNotIn('test-key',str(raised.exception));self.assertEqual(seen,['api.openai.com'])
        with tempfile.TemporaryDirectory() as folder:
            image=Path(folder)/'x.png';image.write_bytes(b'bad')
            with self.assertRaisesRegex(ValueError,'이미지'):
                await generate(ProviderConfig(provider='openai',model='unknown'),[{'role':'user','content':'질문'}],[image],SCHEMA,secret='test-key')
        incomplete={'status':'incomplete','output':[{'type':'message','content':[{'type':'output_text','text':'부분'}]}]}
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=incomplete))) as client:
            with self.assertRaisesRegex(ValueError,'완료'):
                await generate(ProviderConfig(provider='openai',model='gpt-4.1-mini'),[{'role':'user','content':'질문'}],[],SCHEMA,secret='test-key',client=client)
        def timeout(request): raise httpx.ReadTimeout('test-key private')
        async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
            with self.assertRaisesRegex(ValueError,'시간'):
                await generate(ProviderConfig(provider='openai',model='gpt-4.1-mini'),[],[],SCHEMA,secret='test-key',client=client)

    async def test_local_remote_cloud_rejected_and_unknown_vision_disabled(self):
        with self.assertRaisesRegex(ValueError,'엔진'):
            await generate(ProviderConfig(),[{'role':'user','content':'질문'}],[],SCHEMA)
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'models':[{'name':'remote:cloud','digest':'a'*64,'remote_host':'https://ollama.com'}]}))) as client:
            with self.assertRaisesRegex(ValueError,'로컬'): await model_status(ProviderConfig(provider='ollama',model='remote:cloud'),client=client,ollama_url='http://127.0.0.1:11435')
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'id':'unknown'}))) as client:
            status=await model_status(ProviderConfig(provider='openai',model='unknown'),client=client,secret='test-key')
            self.assertTrue(status['accessible']);self.assertFalse(status['vision'])

class SecretTests(unittest.TestCase):
    def test_memory_and_keyring_failure_never_fall_back_to_file(self):
        store=Secrets('test-only')
        with patch('lecture_study.credentials.safe_backend',return_value=None):
            store.set_secret('openai','test-key',False);self.assertEqual(store.get_secret('openai'),'test-key')
            with self.assertRaisesRegex(ValueError,'저장소'): store.set_secret('openai','new-key',True)
            self.assertEqual(store.get_secret('openai'),'test-key')
            store.delete_secret('openai');self.assertIsNone(store.get_secret('openai'))
            self.assertNotIn('test-key',json.dumps(store.status()))

class ProviderApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_secret_never_reaches_db_logs_response_and_inputs_hide_keys(self):
        from lecture_study.server import create_app
        from lecture_study.config import AppConfig
        from lecture_study.db import create_session
        with tempfile.TemporaryDirectory() as folder:
            app=create_app(AppConfig(Path(folder),Path(folder)/'runtime',port=8765))
            try:
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:8765') as client:
                    origin={'Origin':'http://127.0.0.1:8765'}
                    malformed=await client.post('/api/bootstrap',json={'token':'한글'},headers=origin)
                    self.assertEqual(malformed.status_code,403)
                    login=await client.post('/api/bootstrap',json={'token':app.state.bootstrap_token},headers=origin)
                    auth=origin|{'X-Session-Token':login.json()['csrf_token']}
                    with patch('lecture_study.credentials.safe_backend',return_value=None):
                        saved=await client.put('/api/credentials/openai',json={'value':'test-key','persistent':False},headers=auth)
                        self.assertEqual(saved.status_code,200)
                        state=await client.get('/api/settings')
                        invalid=await client.put('/api/credentials/openai',json={'value':'test-key','persistent':'yes'},headers=auth)
                        self.assertEqual(invalid.status_code,422)
                        self.assertNotIn('test-key',saved.text+state.text+invalid.text+'\n'.join(app.state.db.iterdump()))
                        deleted=await client.delete('/api/credentials/openai',headers=auth);self.assertEqual(deleted.status_code,200)
                        self.assertIsNone(app.state.secrets.get_secret('openai'))
                    configured=await client.put('/api/settings',json={'provider':'openai','model':'unknown','context_limit':8192,'vision':True},headers=auth)
                    self.assertEqual(configured.status_code,422)
                    unconfirmed=await client.post('/api/local/pull',json={'model':'qwen3.5:4b','runner':'mlx','confirmed':False},headers=auth)
                    self.assertEqual(unconfirmed.status_code,422);self.assertIsNone(app.state.local_models.pull_task)
                    external=await client.post('/api/local/connect',json={'mode':'existing','url':'https://evil.example'},headers=auth)
                    self.assertEqual(external.status_code,422)
            finally: app.state.db.close()

class LocalTests(unittest.IsolatedAsyncioTestCase):
    async def test_owned_process_env_and_only_owned_child_stopped(self):
        from lecture_study.local_models import OwnedOllama,catalog
        from unittest.mock import AsyncMock,Mock
        with tempfile.TemporaryDirectory() as folder:
            runtime=Path(folder);(runtime/'ollama').mkdir();(runtime/'ollama/ollama').touch()
            child=Mock(returncode=None);child.wait=AsyncMock(return_value=0)
            manager=OwnedOllama(runtime)
            with patch('lecture_study.local_models.component_status',return_value={'ready':True}),patch('lecture_study.local_models.asyncio.create_subprocess_exec',new=AsyncMock(return_value=child)) as spawn,patch('lecture_study.local_models.httpx.AsyncClient.get',new=AsyncMock(return_value=httpx.Response(200,json={'version':'0.40.3'}))):
                url=await manager.start();self.assertTrue(url.startswith('http://127.0.0.1:'))
                env=spawn.call_args.kwargs['env']
                self.assertEqual(env['OLLAMA_NO_CLOUD'],'1');self.assertEqual(env['OLLAMA_NUM_PARALLEL'],'1')
                self.assertEqual(env['OLLAMA_MODELS'],str((runtime/'ollama-models').resolve()));self.assertEqual(env.get('HOME'),__import__('os').environ.get('HOME'))
                await manager.stop();child.terminate.assert_called_once()
                self.assertIsNone(manager.url)
            self.assertEqual(catalog()[0]['model'],'qwen3.5:4b')
            self.assertGreater(catalog()[0]['bytes'],3_000_000_000)


class SourceCopySamplingTests(unittest.IsolatedAsyncioTestCase):
    async def test_copy_mode_is_local_structured_only(self):
        for schema,copy_source in ((SCHEMA,True),({},True),(None,True),(SCHEMA,False)):
            seen=[]
            def respond(request):
                if request.url.path=='/api/tags':return httpx.Response(200,json={'models':[{'name':'test','digest':'a'*64}]})
                if request.url.path=='/api/show':return httpx.Response(200,json={'capabilities':['completion']})
                seen.append(json.loads(request.content));return httpx.Response(200,json={'done':True,'message':{'content':'{"answer":"답"}'}})
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond))as client:
                await generate(ProviderConfig(model='test'),[{'role':'user','content':'원문'}],[],schema,client=client,ollama_url='http://127.0.0.1:11435',source_copy=copy_source)
            options=seen[0]['options'];self.assertEqual(options['num_ctx'],8192);self.assertEqual(options['num_predict'],4096)
            if schema is not None and copy_source:self.assertEqual((options['temperature'],options['presence_penalty']),(0,0))
            else:self.assertNotIn('temperature',options);self.assertNotIn('presence_penalty',options)
