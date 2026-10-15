import asyncio,json,unittest
from unittest.mock import AsyncMock,patch
import httpx
from tests import test_assistance
from pathlib import Path
from lecture_study.config import AppConfig
from lecture_study.server import create_app
from lecture_study.models import ProviderResult
from lecture_study.materials import save_note
from lecture_study.lifecycle import delete_session

class CandidateApiTests(unittest.IsolatedAsyncioTestCase):
    setUp=test_assistance.AssistanceTests.setUp
    speech=test_assistance.AssistanceTests.speech
    async def test_optin_api_block_dedup_persistent_edits_and_explicit_answer(self):
        tid=self.speech();app=create_app(AppConfig(Path(self.temp.name),Path(self.temp.name)/'runtime',port=8765))
        self.addCleanup(app.state.db.close)
        body={'cards':[{'prompt':'뮤텍스와 세마포어의 차이는?','quote':'뮤텍스와 세마포어는 어떻게 다른가요?','source_id':tid}]}
        generated=AsyncMock(return_value=ProviderResult(text=json.dumps(body),model='test',usage={},elapsed_ms=1))
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:8765') as client:
                origin={'Origin':'http://127.0.0.1:8765'};login=await client.post('/api/bootstrap',headers=origin,json={'token':app.state.bootstrap_token});headers=origin|{'X-Session-Token':login.json()['csrf_token']};base='/api/sessions/'+self.sid
                initial=(await client.get(base+'/question-cards')).json();self.assertFalse(initial['options']['enabled'])
                with patch('lecture_study.assistance.generate',new=generated):
                    blocked=await client.post(base+'/question-candidates',json={'automatic':True},headers=headers);self.assertEqual(blocked.status_code,422)
                    self.assertEqual(generated.await_count,0)
                    response=await client.put(base+'/question-candidates/options',json={'enabled':True},headers=headers);self.assertEqual(response.status_code,200)
                    posted=await client.post(base+'/question-candidates',json={'automatic':True},headers=headers);self.assertEqual(posted.status_code,202,posted.text);jid=posted.json()['job']['id']
                    await asyncio.gather(*app.state.tasks)
                    again=await client.post(base+'/question-candidates',json={'automatic':True},headers=headers);self.assertEqual(again.json()['job']['id'],jid)
                    save_note(app.state.db,self.sid,'다른 노트 편집')
                    again=await client.post(base+'/question-candidates',json={'automatic':True},headers=headers);self.assertEqual(again.json()['job']['id'],jid);self.assertEqual(generated.await_count,1)
                cards=(await client.get(base+'/question-cards')).json()['cards'];self.assertEqual(len(cards),1);card=cards[0];self.assertIsNone(card['answer_job_id'])
                url=base+'/question-cards/'+card['id'];edited=await client.patch(url,json={'prompt':'공유 자원 접근은?','pinned':True},headers=headers);self.assertEqual(edited.status_code,200)
                self.assertTrue((await client.get(base+'/question-cards')).json()['cards'][0]['edited'])
                answer={'answer':'공유 자원 접근을 제어합니다.','citations':[{'source_id':tid}],'uncertainty':''}
                with patch('lecture_study.answers.generate',new=AsyncMock(return_value=ProviderResult(text=json.dumps(answer),model='test',usage={},elapsed_ms=1))) as gen:
                    one=await client.post(url+'/answer',json={'scope':{'session_id':self.sid,'mode':'current'}},headers=headers);self.assertEqual(one.status_code,202,one.text)
                    two=await client.post(url+'/answer',json={'scope':{'session_id':self.sid,'mode':'current'}},headers=headers);self.assertEqual(one.json()['id'],two.json()['id']);await asyncio.gather(*app.state.tasks);self.assertEqual(gen.await_count,1)
                await client.patch(url,json={'dismissed':True},headers=headers)
                self.assertTrue((await client.get(base+'/question-cards')).json()['cards'][0]['dismissed'])
                await client.put('/api/settings',json={'provider':'openai','model':'gpt-4.1-mini'},headers=headers)
                blocked=await client.post(base+'/question-candidates',json={'automatic':True},headers=headers);self.assertEqual(blocked.status_code,422)
                blocked=await client.put(base+'/question-candidates/options',json={'enabled':True},headers=headers);self.assertEqual(blocked.status_code,422)
            delete_session(app.state.db,self.sid,True)
            self.assertEqual(app.state.db.execute('SELECT count(*) FROM question_card_preferences').fetchone()[0],0)
            self.assertIsNone(app.state.db.execute('SELECT 1 FROM settings WHERE key=?',('candidate_last:'+self.sid,)).fetchone())
        finally:
            for task in list(app.state.tasks):task.cancel()
            await asyncio.gather(*app.state.tasks,return_exceptions=True)
