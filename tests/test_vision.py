import json
from unittest.mock import AsyncMock,patch
import unittest
from tests import test_materials
from tests.fixtures import pdf_fixture,png_fixture
from lecture_study.models import ProviderResult

class VisionTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=test_materials.MaterialsTests.asyncSetUp
    asyncTearDown=test_materials.MaterialsTests.asyncTearDown
    select=test_materials.MaterialsTests.select
    # Reuse the file-access fixture, without inheriting its unrelated test cases.
    async def test_vector_page_and_capability_before_image_access(self):
        import asyncio
        from lecture_study.outputs import image_evidence
        response=await self.select('vector.pdf',pdf_fixture());await asyncio.gather(*self.app.state.tasks)
        asset=response.json()[0]['asset']['id'];image_id=f'{asset}:v1:page:3'
        body={'session_id':self.session_id,'kind':'vision','prompt':'이 그림을 설명해 주세요.','image_id':image_id,'scope':{'session_id':self.session_id}}
        with patch('lecture_study.outputs.model_status',new=AsyncMock(return_value={'vision':False})),patch('lecture_study.materials.render_page',new=AsyncMock()) as render:
            submitted=await self.client.post('/api/ai/jobs',json=body,headers=self.headers);self.assertEqual(submitted.status_code,202,submitted.text)
            await asyncio.gather(*self.app.state.tasks)
            job=(await self.client.get('/api/jobs/'+submitted.json()['id'])).json()
            self.assertEqual(job['status'],'failed');self.assertIn('이미지',job['error']);render.assert_not_called()
        text_query=await self.client.post('/api/sessions/'+self.session_id+'/search',json={'query':'Lecture','scope':{'session_id':self.session_id}},headers=self.headers);self.assertEqual(text_query.status_code,200);self.assertTrue(text_query.json()['evidence'])
        result=ProviderResult(text=json.dumps({'description':'페이지 그림 설명','evidence_ids':[image_id],'limitations':'작은 글자 확인 필요'}),model='vision-test',usage={},elapsed_ms=1)
        self.app.state.ollama_url='http://127.0.0.1:11435'
        with patch('lecture_study.outputs.model_status',new=AsyncMock(return_value={'vision':True})),patch('lecture_study.outputs.generate',new=AsyncMock(return_value=result)) as generate:
            retried=await self.client.post('/api/jobs/'+submitted.json()['id']+'/retry',headers=self.headers);await asyncio.gather(*self.app.state.tasks)
            job=(await self.client.get('/api/jobs/'+submitted.json()['id'])).json();self.assertEqual(job['status'],'done',job)
            saved=(await self.client.get('/api/artifacts/'+job['result']['id'])).json()
            self.assertEqual(saved['kind'],'vision');self.assertEqual(saved['body']['label'],'AI 해석')
            self.assertIn(image_id,{e['ref']['id'] for e in saved['evidence']});self.assertTrue(generate.call_args.args[2][0].read_bytes().startswith(b'\x89PNG'))
            self.assertEqual(saved['metadata']['image_ref']['coord_system'],'pdf_points')
        forged=body|{'image_id':'/etc/passwd'};self.assertEqual((await self.client.post('/api/ai/jobs',json=forged,headers=self.headers)).status_code,404)
        other=(await self.client.post('/api/sessions',json={'kind':'lecture','title':'다른 과목'},headers=self.headers)).json()['id']
        forged=body|{'session_id':other,'scope':{'session_id':other}}
        self.assertEqual((await self.client.post('/api/ai/jobs',json=forged,headers=self.headers)).status_code,422)
        (self.sources/'vector.pdf').write_bytes(pdf_fixture()+b'changed')
        job_count=self.app.state.db.execute('SELECT count(*) FROM jobs').fetchone()[0]
        with patch('lecture_study.outputs.model_status',new=AsyncMock(return_value={'vision':True})),patch('lecture_study.outputs.generate',new=AsyncMock()) as generate:
            submitted=await self.client.post('/api/ai/jobs',json=body,headers=self.headers)
            self.assertEqual(submitted.status_code,422,submitted.text);self.assertIn('변경',submitted.json()['detail']);generate.assert_not_called()
        self.assertEqual(self.app.state.db.execute('SELECT count(*) FROM jobs').fetchone()[0],job_count)

    async def test_png_and_extracted_pdf_raster_use_original_refs(self):
        import asyncio
        for filename,payload in (('plain.png',png_fixture()),('raster.pdf',pdf_fixture())):
            selected=await self.select(filename,payload);await asyncio.gather(*self.app.state.tasks)
            aid=selected.json()[0]['asset']['id'];asset=(await self.client.get('/api/sessions/'+self.session_id+'/materials')).json()['assets'][-1]
            ref=asset['extraction']['images'][0]['ref'] if filename.endswith('pdf') else asset['extraction']['pages'][0]['ref']
            body={'session_id':self.session_id,'kind':'vision','prompt':'보이는 색과 모양을 설명','image_id':ref['id'],'scope':{'session_id':self.session_id}}
            result=ProviderResult(text=json.dumps({'description':'검사 fixture 설명','evidence_ids':[ref['id']],'limitations':'실제 해석 품질 검증 아님'}),model='test',usage={},elapsed_ms=1)
            with patch('lecture_study.outputs.model_status',new=AsyncMock(return_value={'vision':True})),patch('lecture_study.outputs.generate',new=AsyncMock(return_value=result)) as generate:
                submitted=await self.client.post('/api/ai/jobs',json=body,headers=self.headers);self.assertEqual(submitted.status_code,202,submitted.text);await asyncio.gather(*self.app.state.tasks)
                job=(await self.client.get('/api/jobs/'+submitted.json()['id'])).json();self.assertEqual(job['status'],'done',job)
                saved=(await self.client.get('/api/artifacts/'+job['result']['id'])).json();self.assertEqual(saved['metadata']['image_ref'],ref)
                self.assertTrue(generate.call_args.args[2][0].read_bytes().startswith((b'\x89PNG',b'\xff\xd8')))
