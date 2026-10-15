import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from lecture_study.db import open_db,create_session
from lecture_study import audio,transcription as tr
from lecture_study.lifecycle import delete_session


class VocabularyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.db=open_db(self.root/"data");self.addCleanup(self.db.close)
        self.sid=create_session(self.db,"lecture","지리",None,None).id
        self.other=create_session(self.db,"meeting","다른 회의",None,None).id

    def test_terms_are_scoped_persisted_bounded_and_deleted(self):
        self.assertEqual(tr.get_asr_terms(self.db,self.sid),[])
        tr.save_asr_terms(self.db,self.sid,[" 북발트해 ","북발트해",""])
        self.assertEqual(tr.get_asr_terms(self.db,self.sid),["북발트해"])
        self.assertEqual(tr.get_asr_terms(self.db,self.other),[])
        other_db=open_db(self.root/"data")
        self.assertEqual(tr.get_asr_terms(other_db,self.sid),["북발트해"]);other_db.close()
        for terms in (["가"*70],["줄\n바꿈"],[1]):
            with self.assertRaises(ValueError): tr.save_asr_terms(self.db,self.sid,terms)
        self.assertEqual(tr.get_asr_terms(self.db,self.sid),["북발트해"])
        delete_session(self.db,self.sid,True)
        self.assertFalse(self.db.execute("SELECT 1 FROM settings WHERE key=?",("asr_terms:"+self.sid,)).fetchone())

    async def test_worker_uses_current_session_terms_and_preserves_raw(self):
        tr.save_asr_terms(self.db,self.sid,["북발트해"])
        tr.save_asr_terms(self.db,self.other,["다른 회의 참석자"])
        rid=audio.start_recording(self.db,self.sid,48000)
        audio.append_pcm(self.db,rid,0,0,48000,bytes([255,31])*48000)
        chunk=tr.plan_chunks(self.db,rid,True)[0]
        async def decoder(clip,start,prompt,runtime,**kwargs):
            self.assertEqual(prompt,"북발트해")
            return [{"start_ms":0,"end_ms":1000,"text":"북발트해"}]
        original=audio.recording_path(self.db,rid).read_bytes()
        with patch.object(tr,"transcribe_range",new=decoder):
            await tr.process_pending(self.db,rid,self.root/"runtime")
        self.assertEqual(audio.recording_path(self.db,rid).read_bytes(),original)
        self.assertEqual(tr.list_transcripts(self.db,self.sid)[0]["original_text"],"북발트해")
        self.assertEqual(tr.range_row(self.db,chunk["id"])["prompt"],"북발트해")
        self.assertEqual(tr.range_row(self.db,chunk["id"])["model"],tr.MODEL_NAME)
        tr.save_asr_terms(self.db,self.sid,["변경한 명칭"])
        self.assertEqual(tr.list_transcripts(self.db,self.sid)[0]["text"],"북발트해")
        self.assertEqual(tr.range_row(self.db,chunk["id"])["prompt"],"북발트해")
        self.assertEqual(tr.range_row(self.db,chunk["id"])["model"],tr.MODEL_NAME)

    async def test_exact_silence_records_no_inference_model(self):
        rid=audio.start_recording(self.db,self.sid,48000)
        audio.append_pcm(self.db,rid,0,0,48000,bytes(96000))
        chunk=tr.plan_chunks(self.db,rid,True)[0]
        with patch.object(tr,'transcribe_range') as decoder:
            await tr.process_pending(self.db,rid,self.root/'runtime')
        decoder.assert_not_called()
        self.assertIsNone(tr.range_row(self.db,chunk['id'])['model'])

    async def test_long_prompt_rejected_before_engine_or_silent_truncation(self):
        with self.assertRaisesRegex(ValueError,"핵심 명칭"):
            await tr.transcribe_range(self.root/"absent.wav",0,"가"*70,self.root/"runtime")

    async def test_api_terms_validation_and_no_other_session_leak(self):
        import httpx
        from lecture_study.server import create_app
        from lecture_study.config import AppConfig
        app=create_app(AppConfig(self.root/"data",self.root/"runtime",port=8765))
        self.addCleanup(app.state.db.close)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://127.0.0.1:8765") as client:
            origin={"Origin":"http://127.0.0.1:8765"}
            login=await client.post("/api/bootstrap",json={"token":app.state.bootstrap_token},headers=origin)
            headers={**origin,"X-Session-Token":login.json()["csrf_token"]}
            path="/api/sessions/"+self.sid+"/transcription-terms"
            saved=await client.put(path,json={"terms":["북발트해"]},headers=headers)
            self.assertEqual(saved.status_code,200,saved.text)
            self.assertEqual((await client.get(path)).json()["terms"],["북발트해"])
            self.assertEqual((await client.get("/api/sessions/"+self.other+"/transcription-terms")).json()["terms"],[])
            invalid=await client.put(path,json={"terms":["가"*70]},headers=headers)
            self.assertEqual(invalid.status_code,422)
            self.assertEqual((await client.get(path)).json()["terms"],["북발트해"])
            await client.put(path,json={"terms":[]},headers=headers)
            self.assertEqual((await client.get(path)).json()["terms"],[])
