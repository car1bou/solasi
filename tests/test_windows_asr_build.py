import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class WindowsAsrBuildTests(unittest.TestCase):
    def test_static_baseline_and_avx2_builds_keep_distinct_binaries_and_baseline_probe(self):
        from scripts.build_windows_asr import build_whisper
        with tempfile.TemporaryDirectory()as folder:
            root=Path(folder);commands=[]
            def run(command,**options):
                command=list(map(str,command));commands.append(command)
                if '--build'in command:
                    output=Path(command[command.index('--build')+1])/'bin/Release';output.mkdir(parents=True)
                    for name in command[command.index('--target')+1:command.index('--parallel')]:
                        (output/(name+'.exe')).write_bytes((output.parent.parent.name+':'+name).encode())
                return SimpleNamespace(stdout=b'{"self_check":true}')
            with patch('scripts.build_windows_asr.subprocess.run',side_effect=run):
                result=build_whisper(root/'source',root/'build',root/'asr','cmake')
            self.assertEqual(result['cpu_dispatch'],'avx2-fma-f16c-v1')
            configurations=[command for command in commands if '-S'in command]
            self.assertEqual(len(configurations),2)
            self.assertTrue(all('-DWHISPER_BUILD_EXAMPLES=ON'in command for command in configurations))
            self.assertIn('-DGGML_AVX2=OFF',configurations[0]);self.assertIn('-DGGML_SSE42=OFF',configurations[0]);self.assertIn('-DGGML_BMI2=OFF',configurations[0])
            self.assertIn('-DGGML_AVX2=ON',configurations[1]);self.assertIn('-DGGML_NATIVE=OFF',configurations[1]);self.assertIn('-DBUILD_SHARED_LIBS=OFF',configurations[1]);self.assertIn('-DGGML_BACKEND_DL=OFF',configurations[1])
            for name in ('whisper-cli','whisper-vad-speech-segments'):
                self.assertEqual((root/'asr/bin'/(name+'.exe')).read_bytes(),('baseline:'+name).encode())
                self.assertEqual((root/'asr/bin'/(name+'-avx2.exe')).read_bytes(),('avx2:'+name).encode())
            self.assertEqual((root/'asr/bin/WindowsCpu.exe').read_bytes(),b'baseline:WindowsCpu')
            self.assertTrue(any(command[-1]=='--self-check'for command in commands))


if __name__=='__main__':unittest.main()
