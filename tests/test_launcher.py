import hashlib
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from lecture_study.runtime import download_verified,probe_runtime
from lecture_study.launcher import bind_listener
from lecture_study.config import AppConfig

class LauncherTests(unittest.TestCase):
    def test_hash_and_partial_download_are_not_ready(self):
        import io
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'model.bin';target.write_bytes(b'old')
            item={'url':'https://example.test/asset','bytes':4,'sha256':hashlib.sha256(b'good').hexdigest()}
            with patch('lecture_study.runtime.urlopen',return_value=io.BytesIO(b'bad')):
                with self.assertRaises(ValueError): download_verified(item,target)
            self.assertEqual(target.read_bytes(),b'old');self.assertFalse(target.with_suffix('.bin.part').exists())
            with patch('lecture_study.runtime.urlopen',return_value=io.BytesIO(b'good')):
                download_verified(item,target)
            self.assertEqual(target.read_bytes(),b'good')
            state=probe_runtime(AppConfig(Path(folder),Path(folder)/'runtime'))
            self.assertFalse(state['components']['asr']['ready']);self.assertIsNotNone(state['error_code'])

    def test_port_collision_uses_another_loopback_listener(self):
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1',0));occupied.listen();wanted=occupied.getsockname()[1]
            listener=bind_listener(wanted)
            try:
                self.assertNotEqual(listener.getsockname()[1],wanted);self.assertEqual(listener.getsockname()[0],'127.0.0.1')
            finally:listener.close()

    def test_recording_and_db_persist_after_launcher_restart(self):
        from lecture_study.db import open_db,create_session
        from lecture_study.audio import start_recording,append_pcm,recording_path,get_recording,recover_recordings
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);db=open_db(path);sid=create_session(db,'lecture','재시작',None,None).id
            rid=start_recording(db,sid,48000);append_pcm(db,rid,0,0,480,b'\x00\x01'*480);original=recording_path(db,rid).read_bytes();db.close()
            db=open_db(path)
            try:
                recover_recordings(db);self.assertEqual(get_recording(db,rid)['status'],'interrupted');self.assertEqual(recording_path(db,rid).read_bytes(),original)
            finally:db.close()

    def test_cancel_keeps_existing_file_and_unsafe_archive_is_rejected(self):
        import io,threading,tarfile
        from lecture_study.runtime import unpack,publish_directory
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);target=root/'asset';target.write_bytes(b'previous');cancel=threading.Event();cancel.set()
            item={'url':'https://example.test/asset','bytes':4,'sha256':hashlib.sha256(b'good').hexdigest()}
            with patch('lecture_study.runtime.urlopen',return_value=io.BytesIO(b'good')):
                with self.assertRaises(InterruptedError):download_verified(item,target,cancel=cancel)
            self.assertEqual(target.read_bytes(),b'previous')
            archive=root/'unsafe.tar';info=tarfile.TarInfo('../../escaped');info.size=4
            with tarfile.open(archive,'w') as tar:tar.addfile(info,io.BytesIO(b'evil'))
            with self.assertRaises(tarfile.FilterError):unpack(archive,root/'stage')
            self.assertFalse((root.parent/'escaped').exists())
            old=root/'engine';old.mkdir();(old/'kept').write_text('old');missing=root/'missing'
            with self.assertRaises(FileNotFoundError):publish_directory(missing,old)
            self.assertEqual((old/'kept').read_text(),'old')

    def test_global_job_migration_keeps_existing_artifact_and_references(self):
        from lecture_study.db import open_db,create_session
        from lecture_study.jobs import submit_job
        from lecture_study.answers import save_artifact,get_artifact
        from lecture_study.models import Evidence
        from lecture_study.materials import save_note
        with tempfile.TemporaryDirectory() as folder:
            db=open_db(Path(folder));sid=create_session(db,'lecture','보존',None,None).id;ref=save_note(db,sid,'원문');job=submit_job(db,sid,'ai',{})
            result=save_artifact(db,job['id'],{'answer':'보존'},[Evidence(ref=ref,text='원문',label='노트')],{'kind':'answer','provider':'ollama','model':'test','cutoff_ms':None,'retrieval_mode':'keyword'})
            from tests.legacy import legacy_fixture
            legacy_fixture(db,12);db.close();db=open_db(Path(folder))
            try:
                self.assertEqual(get_artifact(db,result.id)['body']['answer'],'보존');self.assertEqual(db.execute('PRAGMA foreign_keys').fetchone()[0],1);self.assertIsNone(db.execute('PRAGMA foreign_key_check').fetchone())
                self.assertIsNone(submit_job(db,None,'runtime',{'component':'ocr'})['session_id'])
            finally:db.close()

    def test_second_app_cannot_interrupt_active_recording(self):
        from lecture_study.server import create_app
        from lecture_study.db import create_session
        from lecture_study.audio import start_recording,append_pcm,get_recording
        with tempfile.TemporaryDirectory() as folder:
            config=AppConfig(Path(folder),Path(folder)/'runtime');app=create_app(config)
            try:
                sid=create_session(app.state.db,'lecture','동시 실행',None,None).id;rid=start_recording(app.state.db,sid,48000)
                with self.assertRaisesRegex(ValueError,'이미 실행'):create_app(config)
                self.assertEqual(get_recording(app.state.db,rid)['status'],'recording');append_pcm(app.state.db,rid,0,0,480,b'\0\1'*480)
            finally:app.state.db.close();app.state.instance_lock.close()
            restarted=create_app(config)
            try:self.assertEqual(get_recording(restarted.state.db,rid)['status'],'interrupted')
            finally:restarted.state.db.close();restarted.state.instance_lock.close()

class OptionalVadRuntimeTests(unittest.TestCase):
    def test_missing_or_corrupt_optional_vad_does_not_disable_verified_asr(self):
        from lecture_study.runtime import component_status,manifest
        with tempfile.TemporaryDirectory()as folder:
            root=Path(folder);files={}
            for name in ('bin/whisper-cli','bin/ffmpeg','bin/ffprobe','sources/whisper.cpp/LICENSE','sources/ffmpeg/COPYING.LGPLv2.1'):
                path=root/'asr'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'core');files[name]={'bytes':4,'sha256':hashlib.sha256(b'core').hexdigest()}
            receipt={'version':manifest()['components']['asr']['version'],'files':files};(root/'asr/receipt.json').write_text(json.dumps(receipt))
            real_matches=__import__('lecture_study.runtime',fromlist=['matches']).matches
            def checked(path,item):return real_matches(path,item)if str(path).startswith(str(root/'asr'))else True
            with patch('lecture_study.runtime.matches',side_effect=checked):
                state=component_status('asr',root);self.assertTrue(state['ready']);self.assertFalse(state['voice_activity_ready'])
                optional='bin/whisper-vad-speech-segments';files[optional]={'bytes':3,'sha256':hashlib.sha256(b'vad').hexdigest()};(root/'asr/receipt.json').write_text(json.dumps(receipt));(root/'asr'/optional).write_bytes(b'bad')
                state=component_status('asr',root);self.assertTrue(state['ready']);self.assertFalse(state['voice_activity_ready'])
                (root/'asr'/optional).write_bytes(b'vad');self.assertTrue(component_status('asr',root)['voice_activity_ready'])
                (root/'asr/bin/whisper-cli').write_bytes(b'bad!');self.assertFalse(component_status('asr',root)['ready'])
    def test_ready_old_asr_is_not_an_early_return_when_auxiliary_upgrade_is_needed(self):
        from lecture_study.runtime import prepare_runtime
        with tempfile.TemporaryDirectory()as folder,patch('lecture_study.runtime.component_status',return_value={'ready':True,'voice_activity_ready':False}),patch('lecture_study.runtime.platform.system',return_value='Other'):
            with self.assertRaisesRegex(ValueError,'Apple Silicon'):prepare_runtime('asr',folder)
