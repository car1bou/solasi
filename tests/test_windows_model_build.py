import hashlib
import io
import json
import os
from pathlib import Path
import struct
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class WindowsModelBuildTests(unittest.TestCase):
    def test_build_receipts_both_static_worker_variants_and_uses_baseline_probe(self):
        from scripts import build_windows_models as builder
        with tempfile.TemporaryDirectory()as folder:
            root=Path(folder);archive=root/'source.tar.gz';commands=[]
            source_files={'LICENSE':'Permission is hereby granted fixture terms',
                'vendor/stb/stb_image.h':'/*\n------------------------------------------------------------------------------\nThis software fixture',
                'vendor/miniaudio/miniaudio.h':'/*\nThis software is available fixture',
                'vendor/sheredom/subprocess.h':'/* fixture license */\n#ifndef fixture'}
            with tarfile.open(archive,'w:gz')as package:
                for name,body in source_files.items():
                    data=body.encode();item=tarfile.TarInfo('llama.cpp-'+builder.REVISION+'/'+name);item.size=len(data);package.addfile(item,io.BytesIO(data))
            digest=hashlib.sha256(archive.read_bytes()).hexdigest()
            def run(command,**options):
                command=list(map(str,command));commands.append(command)
                if '--build'in command:
                    output=Path(command[command.index('--build')+1]);(output/'bin/Release').mkdir(parents=True)
                    (output/'vendor-licenses.txt').write_text('fixture third-party terms',encoding='utf-8')
                    for name in command[command.index('--target')+1:command.index('--parallel')]:
                        (output/'bin/Release'/(name+'.exe')).write_bytes((output.name+':'+name).encode())
                if command[0].endswith('WindowsCpu.exe'):
                    stdout=b'{"self_check":true}'if command[-1]=='--self-check'else b'{"version":1,"avx2_compatible":true}'
                else:
                    body=json.dumps({'ok':True,'result':{'engine':builder.GENERATION_ENGINE}}).encode();stdout=struct.pack('>I',len(body))+body
                return SimpleNamespace(stdout=stdout)
            with patch.object(builder,'SOURCE_SHA256',digest),patch.object(builder,'os',SimpleNamespace(name='nt',rename=os.rename)),patch.object(builder.platform,'machine',return_value='AMD64'),patch.object(builder.subprocess,'run',side_effect=run):
                record=builder.build(archive,root/'engines')
            self.assertEqual(record.get('cpu_dispatch'),'avx2-fma-f16c-v1')
            configurations=[command for command in commands if '-S'in command]
            self.assertEqual(len(configurations),2)
            self.assertIn('-DSOLASI_CPU_AVX2=OFF',configurations[0]);self.assertIn('-DSOLASI_CPU_AVX2=ON',configurations[1])
            for name in ('ModelWorker','EmbeddingWorker'):
                self.assertEqual((root/'engines'/(name+'.exe')).read_bytes(),('baseline:'+name).encode())
                self.assertEqual((root/'engines'/(name+'-avx2.exe')).read_bytes(),('avx2:'+name).encode())
            self.assertEqual((root/'engines/WindowsCpu.exe').read_bytes(),b'baseline:WindowsCpu')
            self.assertIn('windows/WindowsCpu.cpp',record['sources'])
            for name,item in record['files'].items():
                data=(root/'engines'/name).read_bytes();self.assertEqual(item,{'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
            checks=[Path(command[0]).name for command in commands if command[-1]=='--check']
            self.assertEqual(checks,['ModelWorker.exe','ModelWorker-avx2.exe'])


if __name__=='__main__':unittest.main()
