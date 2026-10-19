import unittest
from pydantic import ValidationError
from test_materials import MaterialsTests
from lecture_study.credentials import Secrets,PROVIDERS
from lecture_study.models import AIRequest

class RetiredSearchTests(MaterialsTests):
    async def test_new_input_rejects_retired_search(self):
        response=await self.client.post('/api/ai/jobs',headers=self.headers,json={'session_id':self.session_id,'prompt':'질문','scope':{'session_id':self.session_id},'web':True,'web_query':'query'})
        self.assertEqual(response.status_code,422,response.text)
    def test_old_request_read_drops_fields_without_key_access(self):
        value=AIRequest.model_validate({'kind':'answer','session_id':'old','prompt':'질문','scope':{'session_id':'old'},'provider':{'provider':'local','model':'qwen3.5:4b'},'web':True,'web_query':'old'})
        self.assertNotIn('web',value.model_dump())
        self.assertNotIn('exa',PROVIDERS)
        with self.assertRaises(ValueError):Secrets('unused').get_secret('exa')
