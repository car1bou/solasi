import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lecture_study.runtime import asr_binary, ocr_binary, component_status, manifest, prepare_runtime


DISPATCH='avx2-fma-f16c-v1'
DISPATCH_FILES=['bin/WindowsCpu.exe','bin/whisper-cli.exe','bin/whisper-vad-speech-segments.exe',
                'bin/whisper-cli-avx2.exe','bin/whisper-vad-speech-segments-avx2.exe']


class WindowsRuntimeTests(unittest.TestCase):
    def test_manifest_labels_do_not_depend_on_windows_locale(self):
        source=Path(__file__).parents[1]/'runtime-manifest.json'
        contents=source.read_bytes()
        def locale_read(path,encoding=None):return contents.decode(encoding or 'cp949')
        with patch.object(Path,'read_text',locale_read):
            self.assertIn('한국어',manifest()['components']['ocr']['label'])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def engine(self, component, names):
        root = self.root/component
        files = {}
        for name in names:
            path = root/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(name.encode())
            files[name] = {'bytes':path.stat().st_size, 'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        (root/'receipt.json').write_text(json.dumps({'platform':'win32-x64','version':manifest()['components'][component]['version'],'files':files}))
        return root, files

    def test_windows_binary_suffix_and_private_dll_verification(self):
        with patch('sys.platform','win32'):
            root, _ = self.engine('asr', ['bin/ffmpeg.exe','bin/avcodec.dll'])
            self.assertEqual(asr_binary(self.root,'ffmpeg'),root/'bin/ffmpeg.exe')
            (root/'bin/avcodec.dll').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'검증|파일|엔진'):
                asr_binary(self.root,'ffmpeg')

    def dispatch_engine(self):
        root,files=self.engine('asr',DISPATCH_FILES)
        record=json.loads((root/'receipt.json').read_bytes());record['cpu_dispatch']=DISPATCH
        (root/'receipt.json').write_text(json.dumps(record),encoding='utf-8')
        return root,record

    def test_verified_cpu_probe_selects_avx2_or_baseline_whisper_and_vad(self):
        from types import SimpleNamespace
        root,_=self.dispatch_engine()
        for supported in (True,False):
            with self.subTest(avx2=supported),patch('sys.platform','win32'),patch('subprocess.run',return_value=SimpleNamespace(stdout=json.dumps({'version':1,'avx2_compatible':supported}).encode()))as probe:
                for name in ('whisper-cli','whisper-vad-speech-segments'):
                    self.assertEqual(asr_binary(self.root,name),root/'bin'/(name+('-avx2'if supported else'')+'.exe'))
                self.assertEqual(probe.call_args.args[0],[str(root/'bin/WindowsCpu.exe')])
                self.assertTrue(probe.call_args.kwargs['check']);self.assertEqual(probe.call_args.kwargs['timeout'],5)

    def test_unknown_or_incomplete_dispatch_never_executes_probe(self):
        root,record=self.dispatch_engine()
        with patch('sys.platform','win32'),patch('subprocess.run')as probe:
            for invalid in (record|{'cpu_dispatch':'unknown'},record|{'files':{name:item for name,item in record['files'].items()if name!='bin/whisper-cli-avx2.exe'}}):
                (root/'receipt.json').write_text(json.dumps(invalid),encoding='utf-8')
                with self.assertRaises(ValueError):asr_binary(self.root,'whisper-cli')
            probe.assert_not_called()

    def test_cpu_probe_tampering_and_malformed_response_do_not_select_accelerated_binary(self):
        from types import SimpleNamespace
        root,_=self.dispatch_engine()
        with patch('sys.platform','win32'),patch('subprocess.run',return_value=SimpleNamespace(stdout=b'{"version":1,"avx2_compatible":"true"}'))as probe:
            with self.assertRaises(ValueError):asr_binary(self.root,'whisper-cli')
            probe.reset_mock();(root/'bin/WindowsCpu.exe').write_bytes(b'tampered')
            with self.assertRaises(ValueError):asr_binary(self.root,'whisper-cli')
            probe.assert_not_called()

    def test_unlisted_dll_is_not_loaded_from_private_binary_directory(self):
        with patch('sys.platform','win32'):
            root, _ = self.engine('ocr',['bin/tesseract.exe'])
            self.assertEqual(ocr_binary(self.root),root/'bin/tesseract.exe')
            (root/'bin/unlisted.dll').write_bytes(b'unknown')
            with self.assertRaises(ValueError):ocr_binary(self.root)

    def test_receipt_cannot_escape_or_use_foreign_platform(self):
        with patch('sys.platform','win32'):
            root, files = self.engine('ocr',['bin/tesseract.exe'])
            for name in ('../outside','C:/outside','bin\\outside','bin/../outside'):
                (root/'receipt.json').write_text(json.dumps({'platform':'win32-x64','files':{name:next(iter(files.values()))}}))
                with self.assertRaises(ValueError):ocr_binary(self.root)
            (root/'receipt.json').write_text(json.dumps({'platform':'darwin-arm64','files':files}))
            with self.assertRaises(ValueError):ocr_binary(self.root)

    def test_frozen_binary_uses_bundle_not_external_runtime(self):
        with patch('sys.platform','win32'):
            root, _ = self.engine('asr',['bin/ffprobe.exe'])
            bundle=self.root/'app';(bundle/'engines').mkdir(parents=True)
            root.rename(bundle/'engines/asr')
            with patch('sys.frozen',True,create=True),patch('sys.executable',str(bundle/'Solasi.exe')):
                self.assertEqual(asr_binary(self.root/'external','ffprobe'),bundle/'engines/asr/bin/ffprobe.exe')

    def test_model_download_requires_bundled_engine_first(self):
        with patch('sys.platform','win32'),patch('lecture_study.runtime.download_verified') as download:
            with self.assertRaises(ValueError):prepare_runtime('asr',self.root)
            download.assert_not_called()

    def test_windows_status_is_not_ready_with_only_tessdata(self):
        with patch('sys.platform','win32'):
            self.assertFalse(component_status('ocr',self.root)['ready'])
            self.assertFalse(component_status('asr',self.root)['ready'])


if __name__=='__main__':unittest.main()
