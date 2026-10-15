import tempfile
import unittest
import json
from pathlib import Path
from lecture_study.db import open_db,create_session
from lecture_study.audio import start_recording,append_pcm,recording_path
from lecture_study.materials import register_file,inspect_file,ingest_asset,save_note
from lecture_study.transcription import plan_chunks,accept_transcription,edit_segment
from lecture_study.models import SourceRef
from lecture_study import lifecycle as life


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=open_db(self.root/"data");self.addCleanup(self.db.close)
        self.sid=create_session(self.db,"lecture","첫 강의",None,None).id
        self.other=create_session(self.db,"lecture","다음 강의",None,None).id

    async def test_delete_preserves_shared_asset_and_old_evidence(self):
        original=self.root/"lecture.txt";original.write_text("원본 자료",encoding="utf8")
        asset=register_file(self.db,self.sid,inspect_file(original))
        result=await ingest_asset(self.db,asset["id"],self.root/"runtime")
        register_file(self.db,self.other,inspect_file(original))
        note=save_note(self.db,self.sid,"처음 메모")
        save_note(self.db,self.sid,"수정 메모")
        old=life.resolve_source(self.db,note)
        self.assertEqual(old["status"],"changed")
        self.assertEqual(old["text_snapshot"],"처음 메모")
        with self.assertRaises(ValueError): life.delete_session(self.db,self.sid,False)
        life.delete_session(self.db,self.sid,True)
        self.assertTrue(original.is_file())
        self.assertEqual(self.db.execute("SELECT count(*) FROM assets WHERE id=?",(asset["id"],)).fetchone()[0],1)
        self.assertEqual(life.resolve_source(self.db,note)["status"],"deleted")
        self.assertEqual(life.resolve_source(self.db,result.pages[0].ref)["status"],"current")
        self.assertEqual(self.db.execute("SELECT count(*) FROM notes WHERE session_id=?",(self.sid,)).fetchone()[0],0)
        life.delete_session(self.db,self.other,True)
        self.assertTrue(original.is_file())
        self.assertEqual(life.resolve_source(self.db,result.pages[0].ref)["status"],"deleted")

    def test_audio_delete_retains_final_text_and_gap_is_not_playable(self):
        rid=start_recording(self.db,self.sid,48000)
        append_pcm(self.db,rid,0,0,12000,bytes([255,31])*12000)
        append_pcm(self.db,rid,2,24000,12000,bytes([255,31])*12000)
        chunks=plan_chunks(self.db,rid,True)
        accept_transcription(self.db,rid,chunks[-1]["id"],1,True,[{"start_ms":0,"end_ms":250,"text":"메모리"}])
        saved=self.db.execute("SELECT * FROM transcripts").fetchone()
        ref=SourceRef.model_validate_json(self.db.execute("SELECT ref FROM sources WHERE id=?",(saved["id"]+":v1",)).fetchone()[0])
        self.assertAlmostEqual(life.playback_position(self.db,rid,500),.25)
        self.assertAlmostEqual(life.resolve_source(self.db,ref)["end_seconds"],.5)
        with self.assertRaises(ValueError): life.playback_position(self.db,rid,300)
        edit_segment(self.db,saved["id"],"가상 메모리")
        self.assertEqual(life.resolve_source(self.db,ref)["text_snapshot"],"메모리")
        path=recording_path(self.db,rid)
        life.delete_audio(self.db,self.sid)
        self.assertFalse(path.exists())
        self.assertEqual(self.db.execute("SELECT count(*) FROM transcripts").fetchone()[0],1)
        resolved=life.resolve_source(self.db,ref)
        self.assertEqual(resolved["status"],"changed")
        self.assertIsNone(resolved["open_url"])

    def test_cleanup_failure_retries_after_restart_without_external_deletion(self):
        from unittest.mock import patch
        from lecture_study.server import create_app
        from lecture_study.config import AppConfig
        rid=start_recording(self.db,self.sid,48000)
        append_pcm(self.db,rid,0,0,12000,bytes(24000))
        path=recording_path(self.db,rid)
        with patch("lecture_study.lifecycle.shutil.rmtree",side_effect=OSError("busy")):
            life.delete_audio(self.db,self.sid)
        self.assertTrue(path.is_file())
        self.assertEqual(self.db.execute("SELECT count(*) FROM file_cleanup").fetchone()[0],1)
        app=create_app(AppConfig(self.root/"data",self.root/"runtime"))
        self.assertFalse(path.exists())
        self.assertEqual(app.state.db.execute("SELECT count(*) FROM file_cleanup").fetchone()[0],0)
        app.state.db.close()
