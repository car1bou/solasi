import unittest
from unittest.mock import patch
from lecture_study.local_models import catalog
from lecture_study.retrieval import embedding_format,embed_parts
import httpx

class NewModelsTests(unittest.IsolatedAsyncioTestCase):
    def test_single_generation_model_and_separate_embedding_roles(self):
        for system,machine in [('Darwin','arm64'),('Linux','x86_64')]:
            with patch('platform.system',return_value=system),patch('platform.machine',return_value=machine):
                entries={e['model']:e for e in catalog()}
                self.assertEqual({m for m in entries if not m.startswith('embedding')},{'qwen3.5:4b'})
                self.assertEqual(entries['qwen3.5:4b']['license'],'Apache-2.0')
                self.assertIn('embeddinggemma',entries)

    async def test_new_embedding_generation_has_distinct_format_and_search_prefix(self):
        self.assertNotEqual(embedding_format('embeddinggemma'),embedding_format('embeddinggemma-2:270m-mxfp8-text'))
        calls=[]
        def reply(req):
            import json
            calls.append(json.loads(req.content));return httpx.Response(200,json={'embeddings':[[1,0]]})
        async with httpx.AsyncClient(base_url='http://127.0.0.1:11435',transport=httpx.MockTransport(reply)) as client:
            await embed_parts(client,'embeddinggemma-2:270m-mxfp8-text','교착 상태',query=True)
            await embed_parts(client,'embeddinggemma-2:270m-mxfp8-text','자원 대기',title='운영체제')
        self.assertEqual(calls[0]['input'],['task: search result | query: 교착 상태'])
        self.assertEqual(calls[1]['input'],['title: 운영체제 | text: 자원 대기'])
