#!/usr/bin/env python3
"""Build the pinned arm64 embedding worker without downloading model weights."""
import argparse
import hashlib
import io
import json
import platform
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = 'llama.cpp-b11669/ollama-embeddinggemma-v1'
REVISION = '620d2225cc436ab0b001e3200e590e3b286ef9ab'
ARCHIVE_SHA256 = 'dbed55493d72bc1ba2babc8770d669c2289b5bc4ee9fb2a4dfc158d45b7d13fd'
HEADERS = {
    'ggml-alloc.h': 'd114067f9099c4a0e2bbc0625c676d4894d9cf0ea27168ee072c7de0e71bb51d',
    'ggml-backend.h': '0e5e8e1f16d11ebbf501e38bc6705d79eee819b5f0b17476533f2100ed9674e2',
    'ggml-cpu.h': '316279e004cdeb8e6ef78599acb602bf79a8abdf897fed9fd1914808c1518c6e',
    'ggml-opt.h': '3586de1bc8a934b5c72339e2b6937b0641e8f149b512231e666f67de0736eea2',
    'ggml.h': '475beaa7e959be8c383279d9ce9d5191f37426e6b338270cfb12b26a798129d3',
    'gguf.h': 'e56714aab702e5ce62ee587a409643c08f7e93e8fbb77f48ef7cc85075f96fa4',
    'llama.h': '961430f89e2553dbcd99e3e6c59826af9ec143f05911520c74f804d986ff3cd2',
}
LIBRARIES = ['libllama.0.7.0.dylib', 'libggml.0.27.0.dylib', 'libggml-base.0.27.0.dylib',
             'libggml-cpu.0.27.0.dylib', 'libggml-blas.0.27.0.dylib',
             'libggml-metal.0.27.0.dylib', 'libggml-rpc.0.27.0.dylib']


def verified(path, expected, limit):
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError('Missing or oversized pinned asset: '+str(path))
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError('SHA256 mismatch: '+str(path))
    return data


def build(archive_path, header_path, destination):
    archive = verified(archive_path, ARCHIVE_SHA256, 13_000_000)
    headers = {name: verified(header_path/name, digest, 300_000) for name, digest in HEADERS.items()}
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise ValueError('The pinned engine requires an Apple Silicon Mac')
    if destination.exists() or destination.is_symlink():
        raise FileExistsError('Destination already exists; choose a new build folder')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir()
    libraries = destination/'lib'; libraries.mkdir()
    files = {}; sources = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as package:
        for name in LIBRARIES:
            member = package.getmember('llama-b11669/'+name)
            if not member.isfile() or not 0 < member.size < 32*1024*1024:
                raise ValueError('Unexpected pinned archive member')
            data = package.extractfile(member).read()
            (libraries/name).write_bytes(data)
            stem = name.split('.0.')[0]
            for alias in (stem+'.0.dylib', stem+'.dylib'):
                (libraries/alias).symlink_to(name)
        license_data = package.extractfile('llama-b11669/LICENSE').read()
    (destination/'LICENSE.llama.cpp').write_bytes(license_data)
    shutil.copyfile(ROOT/'docs/licenses/ollama-MIT.txt', destination/'LICENSE.ollama')
    with tempfile.TemporaryDirectory(prefix='embedding-build-', dir=destination.parent) as folder:
        staging = Path(folder)
        for name, data in headers.items(): (staging/name).write_bytes(data)
        for name in ('EmbeddingWorker.cpp', 'EmbeddingCompat.hpp', 'EmbeddingProtocol.hpp'):
            data = (ROOT/'macos'/name).read_bytes(); (staging/name).write_bytes(data)
            sources[name] = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
        command = ['clang++', '-std=c++17', '-O2', '-mmacosx-version-min=13.3', '-I', str(staging),
                   str(staging/'EmbeddingWorker.cpp'), '-L', str(libraries), '-lllama', '-lggml', '-lggml-base',
                   '-Wl,-rpath,@executable_path/lib', '-o', str(destination/'EmbeddingWorker')]
        subprocess.run(command, check=True)
    for path in [destination/'EmbeddingWorker', *[libraries/name for name in LIBRARIES]]:
        data = path.read_bytes()
        files[str(path.relative_to(destination))] = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
    receipt = {'engine': ENGINE, 'revision': REVISION, 'archive_sha256': ARCHIVE_SHA256,
               'architecture': 'arm64', 'minimum_macos': '13.3', 'files': files, 'sources': sources}
    (destination/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--headers', required=True, type=Path)
    parser.add_argument('--destination', required=True, type=Path)
    args = parser.parse_args()
    try:
        build(args.archive.resolve(), args.headers.resolve(), args.destination.absolute())
    except (OSError, ValueError, subprocess.CalledProcessError, tarfile.TarError, KeyError) as exc:
        parser.exit(1, str(exc)+'\n')
    print(args.destination.absolute()/'EmbeddingWorker')


if __name__ == '__main__': main()
