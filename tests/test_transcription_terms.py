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
        import json
        receipt=self.db.execute('SELECT snapshot FROM transcription_hint_snapshots WHERE chunk_id=?',(chunk['id'],)).fetchone()
        self.assertEqual(json.loads(receipt[0])['prompt'],'북발트해')
        tr.save_asr_terms(self.db,self.sid,["변경한 명칭"])
        self.assertEqual(tr.list_transcripts(self.db,self.sid)[0]["text"],"북발트해")
        self.assertEqual(tr.range_row(self.db,chunk["id"])["prompt"],"북발트해")
        self.assertEqual(tr.range_row(self.db,chunk["id"])["model"],tr.MODEL_NAME)

    async def test_registered_hint_snapshot_survives_source_change_and_reopen(self):
        import json
        from lecture_study.materials import save_note
        from lecture_study.retrieval import save_term
        ref=save_note(self.db,self.sid,'자그로스산맥')
        save_term(self.db,self.sid,'자그로스산맥',[],'',[ref])
        rid=audio.start_recording(self.db,self.sid,48000)
        audio.append_pcm(self.db,rid,0,0,48000,bytes([255,31])*48000)
        chunk=tr.plan_chunks(self.db,rid,True)[0]
        async def decode(*args,**kwargs):return [{'start_ms':0,'end_ms':1000,'text':'자그로스산맥'}]
        with patch.object(tr,'transcribe_range',new=decode):await tr.process_pending(self.db,rid,self.root/'runtime')
        raw=self.db.execute('SELECT snapshot FROM transcription_hint_snapshots WHERE chunk_id=?',(chunk['id'],)).fetchone()[0]
        snapshot=json.loads(raw);self.assertEqual(snapshot['selected'][0]['evidence'][0]['id'],ref.id)
        save_note(self.db,self.sid,'다른 메모');self.assertEqual(tr.asr_prompt(self.db,self.sid),'')
        reopened=open_db(self.root/'data')
        try:
            self.assertEqual(reopened.execute('SELECT snapshot FROM transcription_hint_snapshots WHERE chunk_id=?',(chunk['id'],)).fetchone()[0],raw)
            self.assertEqual(tr.range_row(reopened,chunk['id'])['prompt'],'자그로스산맥')
            self.assertEqual(tr.list_transcripts(reopened,self.sid)[0]['original_text'],'자그로스산맥')
        finally:reopened.close()

    async def test_hint_file_checks_run_off_the_audio_event_loop(self):
        import threading
        from lecture_study.asr_hints import hint_snapshot
        from unittest.mock import AsyncMock
        rid=audio.start_recording(self.db,self.sid,48000)
        audio.append_pcm(self.db,rid,0,0,48000,bytes([255,31])*48000)
        tr.plan_chunks(self.db,rid,True)
        thread=threading.current_thread()
        def check(*args):
            self.assertIsNot(threading.current_thread(),thread)
            return hint_snapshot(*args)
        decode=AsyncMock(return_value=[{'start_ms':0,'end_ms':1000,'text':'원문'}])
        with patch('lecture_study.asr_hints.hint_snapshot',side_effect=check),patch.object(tr,'transcribe_range',new=decode):
            await tr.process_pending(self.db,rid,self.root/'runtime')
        decode.assert_awaited_once()

    async def test_pcm_append_continues_while_hint_check_is_waiting(self):
        import asyncio,threading
        from lecture_study.asr_hints import hint_snapshot
        from unittest.mock import AsyncMock
        entered=threading.Event();release=threading.Event()
        rid=audio.start_recording(self.db,self.sid,48000)
        pcm=bytes([255,31])*48000;audio.append_pcm(self.db,rid,0,0,48000,pcm)
        tr.plan_chunks(self.db,rid,True)
        def slow(*args):
            entered.set()
            if not release.wait(2):raise ValueError('hint check blocked the event loop')
            return hint_snapshot(*args)
        decode=AsyncMock(return_value=[{'start_ms':0,'end_ms':1000,'text':'원문'}])
        with patch('lecture_study.asr_hints.hint_snapshot',side_effect=slow),patch.object(tr,'transcribe_range',new=decode):
            task=asyncio.create_task(tr.process_pending(self.db,rid,self.root/'runtime'))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait,1))
                audio.append_pcm(self.db,rid,1,48000,48000,pcm)
                self.assertEqual(audio.get_recording(self.db,rid)['source_frames'],96000)
            finally:release.set();await task
        decode.assert_awaited_once()

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
            from lecture_study.materials import save_note
            from lecture_study.retrieval import save_term
            ref=save_note(self.db,self.sid,'자그로스산맥');save_term(self.db,self.sid,'자그로스산맥',[],'',[ref])
            save_note(self.db,self.sid,'자료 수정')
            current=(await client.get(path)).json()
            self.assertNotIn('자그로스산맥',current['effective_prompt'])
            self.assertEqual(current['excluded_terms'],[{'term':'자그로스산맥','reason':'근거 재검토 필요'}])
            await client.put(path,json={"terms":[]},headers=headers)
            self.assertEqual((await client.get(path)).json()["terms"],[])
