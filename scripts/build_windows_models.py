#!/usr/bin/env python3
"""Build static pinned CPU workers; no models or installer tools are downloaded."""
import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
REVISION = '620d2225cc436ab0b001e3200e590e3b286ef9ab'
SOURCE_URL = 'https://codeload.github.com/ggml-org/llama.cpp/tar.gz/'+REVISION
SOURCE_SHA256 = '1d4a987d9bd048f6e93107e838026438df70fbde237fc0c69c63d600512b4bd9'
EMBEDDING_ENGINE = 'llama.cpp-b11669/ollama-embeddinggemma-v1'
GENERATION_ENGINE = 'llama.cpp-b11669/windows-cpu-qwen35-v1/chat-template-no-thinking-v1'


def build_workers(source,stage,bundle,cmake):
    from lecture_study.windows_runtime import CPU_DISPATCH
    (bundle/'lib').mkdir(parents=True);configurations={}
    for flavor in ('baseline','avx2'):
        output=stage/flavor
        flags=['-DLLAMA_SOURCE='+str(source),'-DCMAKE_BUILD_TYPE=Release',
               '-DCMAKE_POLICY_DEFAULT_CMP0091=NEW','-DSOLASI_CPU_AVX2='+('ON'if flavor=='avx2'else'OFF')]
        configurations[flavor]=flags
        subprocess.run([str(cmake),'-S',str(ROOT/'windows'),'-B',str(output),'-A','x64',*flags],check=True)
        targets=['ModelWorker','EmbeddingWorker']+(['WindowsCpu']if flavor=='baseline'else[])
        subprocess.run([str(cmake),'--build',str(output),'--config','Release','--target',*targets,'--parallel','4'],check=True)
        for name in targets:
            candidates=list(output.glob('**/'+name+'.exe'))
            if len(candidates)!=1:raise ValueError('Missing or ambiguous native worker '+name)
            suffix='-avx2'if flavor=='avx2'else''
            shutil.copy2(candidates[0],bundle/(name+suffix+'.exe'))
    return {'cpu_dispatch':CPU_DISPATCH,'cpu_build_flags':configurations}


def build(archive, destination, *, cmake='cmake'):
    with archive.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != SOURCE_SHA256:
            raise ValueError('SHA256 mismatch for pinned llama.cpp source')
    if os.name != 'nt' or platform.machine().lower() not in ('amd64', 'x86_64'):
        raise ValueError('Build the Windows x64 package on Windows x64')
    if destination.exists() or destination.is_symlink(): raise FileExistsError('Destination already exists')
    destination=destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.models-build-', dir=destination.parent) as folder:
        stage = Path(folder)
        with tarfile.open(archive) as package: package.extractall(stage, filter='data')
        source = stage/('llama.cpp-'+REVISION)
        output = stage/'build';bundle=stage/'engines'
        cpu=build_workers(source,output,bundle,cmake)
        # Static CPU-only build has no backend or VC runtime DLL dependency.
        shutil.copyfile(source/'LICENSE', bundle/'LICENSE.llama.cpp')
        shutil.copyfile(ROOT/'docs/licenses/ollama-MIT.txt', bundle/'LICENSE.ollama')
        notices = (output/'baseline/vendor-licenses.txt').read_text(encoding='utf-8')
        for name, marker in (('stb/stb_image.h', '/*\n------------------------------------------------------------------------------\nThis software'),
                             ('miniaudio/miniaudio.h', '/*\nThis software is available')):
            text = (source/'vendor'/name).read_text(encoding='utf-8')
            start = text.rfind(marker)
            if start < 0: raise ValueError('Pinned vendor license marker missing: '+name)
            notices += '\n\n'+name+'\n'+text[start:]
        subprocess_header = (source/'vendor/sheredom/subprocess.h').read_text(encoding='utf-8')
        notices += '\n\nsheredom/subprocess.h\n'+subprocess_header.split('#ifndef', 1)[0]
        mit_permission = 'Permission is hereby granted'+(source/'LICENSE').read_text(encoding='utf-8').split('Permission is hereby granted', 1)[1]
        notices += '\n\nnlohmann/json: Copyright 2013-2025 Niels Lohmann, MIT license.\n'+mit_permission
        (bundle/'LICENSE.third-party').write_text(notices, encoding='utf-8')
        files = {}
        for path in bundle.rglob('*'):
            if not path.is_file(): continue
            with path.open('rb') as stream: checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
            files[path.relative_to(bundle).as_posix()] = {'bytes': path.stat().st_size, 'sha256': checksum}
        record = {'engine': EMBEDDING_ENGINE, 'generation_engine': GENERATION_ENGINE,
                  'revision': REVISION, 'architecture': 'x64', 'source_sha256': SOURCE_SHA256, 'files': files,**cpu,
                  'sources': {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
                              ('windows/ModelWorker.cpp', 'windows/NativePlatform.hpp', 'windows/CMakeLists.txt','windows/WindowsCpu.cpp',
                               'macos/EmbeddingWorker.cpp', 'macos/EmbeddingCompat.hpp', 'macos/EmbeddingProtocol.hpp')}}
        (bundle/'receipt.json').write_text(json.dumps(record, indent=2)+'\n', encoding='utf-8')
        from lecture_study.windows_models import WindowsModels
        from lecture_study.windows_runtime import cpu_supports_avx2
        WindowsModels(stage/'runtime',stage/'cache',engine_dir=bundle).check_embedding_engine()
        checked=subprocess.run([str(bundle/'WindowsCpu.exe'),'--self-check'],capture_output=True,check=True,timeout=10)
        if json.loads(checked.stdout)!={'self_check':True}:raise ValueError('Native CPU guard self-check failed')
        workers=['ModelWorker.exe']+(['ModelWorker-avx2.exe']if cpu_supports_avx2(bundle/'WindowsCpu.exe')else[])
        import struct
        for worker in workers:
            checked = subprocess.run([str(bundle/worker), str(bundle/'lib'), '--check'], capture_output=True, check=True,timeout=15)
            if len(checked.stdout) < 4: raise ValueError('Native check response missing')
            size, = struct.unpack('>I', checked.stdout[:4])
            reply = json.loads(checked.stdout[4:])
            if size != len(checked.stdout)-4 or reply != {'ok': True, 'result': {'engine': GENERATION_ENGINE}}:
                raise ValueError('Native check response mismatch')
        os.rename(bundle, destination)
        return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True, type=Path, help='Pinned source archive: '+SOURCE_URL)
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--cmake', default='cmake')
    args = parser.parse_args()
    try: build(args.archive.resolve(), args.destination.absolute(), cmake=args.cmake)
    except (OSError, ValueError, subprocess.SubprocessError, tarfile.TarError) as error: parser.exit(1, str(error)+'\n')
    print(args.destination.absolute())


if __name__ == '__main__': main()
