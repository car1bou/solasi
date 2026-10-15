import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
from lecture_study.db import open_db,create_session
from lecture_study import audio


class AudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = open_db(self.root)
        self.addCleanup(self.db.close)
        self.session_id = create_session(self.db,"lecture","녹음",None,None).id

    def test_duplicate_gap_and_failed_write(self):
        ident = audio.start_recording(self.db,self.session_id,48000)
        payload = b"\x01\x00"*12000
        first = audio.append_pcm(self.db,ident,0,0,12000,payload)
        duplicate = audio.append_pcm(self.db,ident,0,0,12000,payload)
        self.assertEqual(first["seq"],duplicate["seq"])
        with self.assertRaises(ValueError):
            audio.append_pcm(self.db,ident,0,0,12000,b"\x02\x00"*12000)
        with self.assertRaises(ValueError):
            audio.append_pcm(self.db,ident,1,12000,12000,b"bad")
        second = audio.append_pcm(self.db,ident,2,24000,12000,payload)
        self.assertEqual(second["stored_frames"],24000)
        row = audio.get_recording(self.db,ident)
        self.assertEqual(row["gaps"],[{"start_frame":12000,"end_frame":24000}])
        with wave.open(str(audio.recording_path(self.db,ident)),"rb") as wav:
            self.assertEqual(wav.getnframes(),24000)
            self.assertEqual(wav.getframerate(),48000)
        acknowledgements = []
        with patch("lecture_study.audio.write_pcm",side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                acknowledgements.append(audio.append_pcm(self.db,ident,3,36000,12000,payload))
        self.assertEqual(acknowledgements,[])
        self.assertEqual(audio.get_recording(self.db,ident)["stored_frames"],24000)
        job = audio.stop_recording(self.db,ident)
        self.assertEqual(job["kind"],"transcribe")
        self.assertEqual(audio.get_recording(self.db,ident)["status"],"stopped")

    def test_invalid_metadata_and_interrupted_tail(self):
        for rate in (7999,192001,True):
            with self.assertRaises(ValueError):
                audio.start_recording(self.db,self.session_id,rate)
        ident = audio.start_recording(self.db,self.session_id,44100)
        with self.assertRaises(ValueError):
            audio.start_recording(self.db,self.session_id,44100)
        for seq,first,count,payload in [(-1,0,1,b"\0\0"),(0,-1,1,b"\0\0"),(0,0,44101,b"\0\0"*44101),(0,0,0,b"")]:
            with self.assertRaises(ValueError):
                audio.append_pcm(self.db,ident,seq,first,count,payload)
        audio.append_pcm(self.db,ident,0,0,11025,b"\0\0"*11025)
        audio.stop_recording(self.db,ident,end_frame=22050,interrupted=True)
        row = audio.get_recording(self.db,ident)
        self.assertEqual(row["gaps"],[{"start_frame":11025,"end_frame":22050}])
        self.assertEqual(row["status"],"interrupted")
        with self.assertRaises(ValueError):
            audio.append_pcm(self.db,ident,1,11025,11025,b"\0\0"*11025)

    def test_interrupted_tail_extends_timeline_but_not_stored_audio(self):
        ident=audio.start_recording(self.db,self.session_id,48000)
        audio.append_pcm(self.db,ident,0,0,12000,b"\0\0"*12000)
        audio.stop_recording(self.db,ident,end_frame=48000,interrupted=True)
        row=audio.get_recording(self.db,ident)
        self.assertEqual(row['source_frames'],48000)
        self.assertEqual(row['stored_frames'],12000)
        with wave.open(str(audio.recording_path(self.db,ident))) as wav:self.assertEqual(wav.getnframes(),12000)
        next_id=audio.start_recording(self.db,self.session_id,48000)
        self.assertGreaterEqual(audio.get_recording(self.db,next_id)['offset_ms'],1000)

    def test_late_stop_extends_disconnect_gap_with_same_job(self):
        ident=audio.start_recording(self.db,self.session_id,48000)
        audio.append_pcm(self.db,ident,0,0,12000,b"\0\0"*12000)
        job=audio.stop_recording(self.db,ident,interrupted=True,error='연결 끊김')
        final=audio.stop_recording(self.db,ident,end_frame=24000,interrupted=True,error='전송 중단')
        self.assertEqual(final['id'],job['id'])
        row=audio.get_recording(self.db,ident)
        self.assertEqual(row['source_frames'],24000)
        self.assertEqual(row['gaps'],[{'start_frame':12000,'end_frame':24000}])
        self.assertEqual(row['error'],'전송 중단')
        with wave.open(str(audio.recording_path(self.db,ident))) as wav:self.assertEqual(wav.getnframes(),12000)
        audio.stop_recording(self.db,ident,end_frame=18000)
        self.assertEqual(audio.get_recording(self.db,ident)['source_frames'],24000)
        with self.assertRaises(ValueError):audio.stop_recording(self.db,ident,end_frame=True)

    def test_unacknowledged_file_tail_is_repaired_on_restart(self):
        ident = audio.start_recording(self.db,self.session_id,48000)
        audio.append_pcm(self.db,ident,0,0,12000,b"\0\0"*12000)
        with audio.recording_path(self.db,ident).open("ab") as handle:
            handle.write(b"\1\0"*12000)
        audio.recover_recordings(self.db)
        row = audio.get_recording(self.db,ident)
        self.assertEqual(row["status"],"interrupted")
        self.assertEqual(audio.recording_path(self.db,ident).stat().st_size,44+24000)
        with wave.open(str(audio.recording_path(self.db,ident)),"rb") as wav:
            self.assertEqual(wav.getnframes(),12000)

    def test_live_offset_follows_imported_audio_end(self):
        from lecture_study.db import new_id,now
        imported=new_id()
        with self.db:self.db.execute("INSERT INTO recordings(id,session_id,kind,sample_rate,status,started_at,offset_ms,source_frames) VALUES (?,?,'file',16000,'stopped',?,0,?)",(imported,self.session_id,now(),16000*3600))
        live=audio.start_recording(self.db,self.session_id,48000)
        self.assertGreaterEqual(audio.get_recording(self.db,live)['offset_ms'],3600000)


class WindowTests(unittest.TestCase):
    def test_probe_window_is_shared_and_keeps_all_frames(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        import lecture_study.transcription as transcription
        from lecture_study.db import open_db,create_session
        from lecture_study.audio import start_recording,append_pcm,stop_recording
        with tempfile.TemporaryDirectory() as folder:
            db=open_db(Path(folder))
            try:
                self.assertEqual(transcription.CHUNK_SECONDS,30)
                sid=create_session(db,'lecture','경계 검증',None,None).id;rid=start_recording(db,sid,48000)
                with patch.object(transcription,'CHUNK_SECONDS',30):
                    for n in range(35):append_pcm(db,rid,n,n*48000,48000,b'\x00\x01'*48000)
                    stop_recording(db,rid);chunks=transcription.plan_chunks(db,rid,True)
                self.assertEqual([(r['start_frame'],r['end_frame']) for r in chunks],[(0,30*48000),(30*48000,35*48000)])
            finally:db.close()


if __name__=="__main__":
    unittest.main()
