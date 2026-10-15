import hashlib,json,os,tempfile,unittest,wave
from pathlib import Path
from unittest.mock import AsyncMock,patch

class QwenValidationTests(unittest.TestCase):
    def test_digital_silence_never_loads_a_model_or_creates_a_phrase(self):
        from lecture_study import qwen_asr as qwen
        with tempfile.TemporaryDirectory()as temp,patch.object(qwen,'verify_files'),patch.object(qwen,'read_pcm',return_value=bytes(32000)),patch.object(qwen.importlib.metadata,'version',side_effect=AssertionError('silent audio must not load dependencies')):
            output=Path(temp)/'result.json';qwen.worker(Path('/model'),Path('/clip'),output)
            result=json.loads(output.read_text());self.assertEqual(result['text'],'');self.assertEqual(result['generation_tokens'],0);self.assertTrue(result['skipped_digital_silence'])
    def test_only_pinned_loader_files_are_accepted_before_model_loading(self):
        from lecture_study import qwen_asr as qwen
        with tempfile.TemporaryDirectory()as temp:
            root=Path(temp);content=b'{"model_type":"qwen3_asr"}';(root/'config.json').write_bytes(content)
            pinned={'config.json':{'bytes':len(content),'sha256':hashlib.sha256(content).hexdigest()}}
            with patch.object(qwen,'FILES',pinned):
                qwen.verify_files(root)
                (root/'tokenizer.json').write_text('{}')
                with self.assertRaises(ValueError):qwen.verify_files(root)
                (root/'tokenizer.json').unlink();(root/'config.json').write_text('{"auto_map":{}}')
                with self.assertRaises(ValueError):qwen.verify_files(root)
    def test_worker_rejects_non_mono_pcm_and_truncated_audio(self):
        from lecture_study import qwen_asr as qwen
        with tempfile.TemporaryDirectory()as temp:
            path=Path(temp)/'input.wav'
            with wave.open(str(path),'wb')as handle:handle.setnchannels(2);handle.setsampwidth(2);handle.setframerate(16000);handle.writeframes(b'\0\1'*16000)
            with self.assertRaises(ValueError):qwen.read_pcm(path)
            with wave.open(str(path),'wb')as handle:handle.setnchannels(1);handle.setsampwidth(2);handle.setframerate(16000);handle.writeframes(b'\0\1'*16000)
            self.assertEqual(len(qwen.read_pcm(path)),32000)
            path.write_bytes(path.read_bytes()[:-2])
            with self.assertRaises(ValueError):qwen.read_pcm(path)
    def test_offline_policy_is_set_before_dependencies_or_model_can_load(self):
        from lecture_study import qwen_asr as qwen
        with patch.dict(os.environ,{'HF_HUB_OFFLINE':'0','TRANSFORMERS_OFFLINE':'0'}),patch.object(qwen,'verify_files'),patch.object(qwen,'read_pcm',return_value=b'\0\1'),patch.object(qwen.importlib.metadata,'version',return_value='unsupported'):
            with self.assertRaisesRegex(ValueError,'버전'):qwen.worker(Path('/model'),Path('/clip'),Path('/output'))
            self.assertEqual(os.environ['HF_HUB_OFFLINE'],'1');self.assertEqual(os.environ['TRANSFORMERS_OFFLINE'],'1');self.assertEqual(os.environ['HF_HUB_DISABLE_TELEMETRY'],'1')

class QwenResultTests(unittest.IsolatedAsyncioTestCase):
    async def test_truncated_or_invalid_worker_output_is_not_saved_as_a_candidate(self):
        from lecture_study import qwen_asr as qwen
        async def native(argv,**kwargs):
            if '-I'in argv:Path(argv[-1]).write_text(json.dumps({'text':'잘린 후보','generation_tokens':1024,'mlx_peak_bytes':1,'process_peak_rss_bytes':1}))
            return b''
        with patch('lecture_study.transcription.engine_paths',return_value=(Path('/fake/ffmpeg'),None,None)),patch('lecture_study.transcription.command',new=AsyncMock(side_effect=native)):
            with self.assertRaisesRegex(ValueError,'상한'):await qwen.transcribe(Path('/fake/input.wav'),Path('/fake/runtime'))
