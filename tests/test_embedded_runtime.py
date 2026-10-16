import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lecture_study.execution import worker_command
from lecture_study.runtime import asr_binary
from scripts.freeze_macos_engine import copy_verified_files, deployment_target


class EmbeddedRuntimeTests(unittest.TestCase):
    def test_freeze_support_dispatches_before_app_start(self):
        from lecture_study.engine_main import main
        with patch('multiprocessing.freeze_support',side_effect=SystemExit(0)) as support,patch('lecture_study.native_worker.main') as app:
            with self.assertRaises(SystemExit):main()
            support.assert_called_once();app.assert_not_called()
    def test_minimum_os_includes_inference_library_requirement(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'engine').write_bytes(b'\xcf\xfa\xed\xfe')
            with patch('scripts.freeze_macos_engine.subprocess.run',return_value=SimpleNamespace(stdout='LC_BUILD_VERSION\n minos 26.2\n sdk 26.5')):
                self.assertEqual(deployment_target(root),'26.2')
    def test_bundle_receipt_cannot_write_outside_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';source.mkdir();destination=root/'bundle'
            payload=source/'payload';payload.write_bytes(b'original')
            item={'bytes':8,'sha256':hashlib.sha256(b'original').hexdigest()}
            for name in ('../source/payload','/absolute','./payload','a/../payload',''):
                with self.assertRaises(ValueError):copy_verified_files(source,destination,{'files':{name:item}})
            self.assertEqual(payload.read_bytes(),b'original')
            destination.mkdir();(destination/'payload').symlink_to(payload)
            with self.assertRaises(ValueError):copy_verified_files(source,destination,{'files':{'payload':item}})
            (destination/'payload').unlink()
            copy_verified_files(source,destination,{'files':{'payload':item}})
            self.assertEqual((destination/'payload').read_bytes(),b'original')
    def test_frozen_subprocess_uses_owned_executable_only(self):
        with patch('sys.frozen',True,create=True),patch('sys.executable','/App/engine/solasi-engine'):
            self.assertEqual(worker_command('material-worker',['parse','a']),['/App/engine/solasi-engine','material-worker','parse','a'])
            self.assertEqual(worker_command('qwen-worker',[]),['/App/engine/solasi-engine','qwen-worker'])
            with self.assertRaises(ValueError):worker_command('shell',[])

    def test_bundled_binary_hash_and_no_external_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);engine=root/'engine';binary=engine/'engines/asr/bin/ffmpeg'
            binary.parent.mkdir(parents=True);binary.write_bytes(b'pinned')
            receipt={'version':'fixture','files':{'bin/ffmpeg':{'bytes':6,'sha256':hashlib.sha256(b'pinned').hexdigest()}}}
            (binary.parent.parent/'receipt.json').write_text(json.dumps(receipt))
            external=root/'old-runtime/ffmpeg/bin/ffmpeg';external.parent.mkdir(parents=True);external.write_bytes(b'old')
            with patch('sys.frozen',True,create=True),patch('sys.executable',str(engine/'solasi-engine')):
                self.assertEqual(asr_binary(root/'old-runtime','ffmpeg'),binary)
                binary.write_bytes(b'broken')
                with self.assertRaises(ValueError):asr_binary(root/'old-runtime','ffmpeg')
                binary.unlink()
                with self.assertRaises(ValueError):asr_binary(root/'old-runtime','ffmpeg')
                with self.assertRaises(ValueError):asr_binary(root/'old-runtime','../../bad')


class EmbeddedAudioImportTests(unittest.IsolatedAsyncioTestCase):
    async def test_audio_import_uses_verified_bundled_probe_without_external_fallback(self):
        import wave
        from unittest.mock import AsyncMock
        from lecture_study.db import open_db,create_session
        from lecture_study.transcription import register_audio
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);runtime=root/'runtime';engine=root/'engine'
            bundled=engine/'engines/asr/bin/ffprobe';bundled.parent.mkdir(parents=True)
            bundled.write_bytes(b'bundled')
            receipt={'files':{'bin/ffprobe':{'bytes':7,'sha256':hashlib.sha256(b'bundled').hexdigest()}}}
            (bundled.parent.parent/'receipt.json').write_text(json.dumps(receipt))
            external=runtime/'ffmpeg/bin/ffprobe';external.parent.mkdir(parents=True);external.write_bytes(b'external')
            source=root/'speech.wav'
            with wave.open(str(source),'wb') as output:
                output.setnchannels(1);output.setsampwidth(2);output.setframerate(16000);output.writeframes(b'\0\0'*16000)
            original=source.read_bytes()
            db=open_db(root/'data')
            try:
                session=create_session(db,'lecture','내장 오디오 가져오기',None,None)
                command=AsyncMock(return_value=json.dumps({'streams':[{'sample_rate':'16000','channels':1,'duration':'1.0'}]}))
                with patch('sys.frozen',True,create=True),patch('sys.executable',str(engine/'solasi-engine')),patch('lecture_study.transcription.command',command):
                    await register_audio(db,session.id,source,runtime)
                    self.assertEqual(command.call_args.args[0][0],bundled)
                    bundled.unlink();command.reset_mock()
                    with self.assertRaises(ValueError):await register_audio(db,session.id,source,runtime)
                    command.assert_not_called()
                    bundled.write_bytes(b'corrupt')
                    with self.assertRaises(ValueError):await register_audio(db,session.id,source,runtime)
                    command.assert_not_called()
                self.assertEqual(source.read_bytes(),original)
                self.assertEqual(external.read_bytes(),b'external')
            finally:db.close()


if __name__=='__main__':unittest.main()
