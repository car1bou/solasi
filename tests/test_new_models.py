import unittest
from unittest.mock import patch
from lecture_study.local_models import catalog
from lecture_study.retrieval import embedding_format,embed_parts
import httpx

class NewModelsTests(unittest.IsolatedAsyncioTestCase):
    def test_fixed_mac_catalog_and_portable_filter(self):
        with patch('platform.system',return_value='Darwin'),patch('platform.machine',return_value='arm64'):
            entries={e['model']:e for e in catalog()}
            self.assertEqual(entries['gemma4:e2b']['bytes'],7476595162)
            self.assertEqual(entries['embeddinggemma-2:270m-mxfp8-text']['bytes'],442218503)
            self.assertEqual(entries['gemma4:e2b']['license'],'Apache-2.0')
            self.assertEqual(entries['gemma4:e2b-it-qat']['runner'],'llamacpp')
            self.assertEqual(entries['gemma4:e2b-it-qat']['bytes'],4336358185)
            self.assertEqual(entries['gemma4:e4b-it-qat']['bytes'],6146501801)
            self.assertEqual(entries['gemma4:12b']['runner'],'mlx')
        with patch('platform.system',return_value='Linux'),patch('platform.machine',return_value='x86_64'):
            self.assertNotIn('gemma4:e2b',{e['model'] for e in catalog()})
            self.assertIn('gemma4:e2b-it-qat',{e['model'] for e in catalog()})
            self.assertNotIn('gemma4:12b',{e['model'] for e in catalog()})

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
