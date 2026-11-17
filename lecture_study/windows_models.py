"""Pinned CPU models executed by owned native workers, without a model listener."""
import asyncio
import hashlib
import json
import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import httpx

from .direct_models import DirectModels, model_identity as embedding_identity
from .model_assets import _rename_exclusive
from .windows_runtime import CPU_DISPATCH,cpu_supports_avx2

ENGINE_ID = 'llama.cpp-b11669/windows-cpu-qwen35-v1/chat-template-no-thinking-v1'
CONTEXT_LIMIT = 8192
CPU_WORKERS={'WindowsCpu.exe',*[name+suffix+'.exe'for name in ('ModelWorker','EmbeddingWorker')for suffix in ('','-avx2')]}
_GGUF_BASE = 'https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/e87f176479d0855a907a41277aca2f8ee7a09523/'
_QWEN_BASE = 'https://huggingface.co/Qwen/Qwen3.5-4B/resolve/851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a/'
# Publisher LFS hashes, checked 2026-10-27; the license hash is from those pinned bytes.
WINDOWS_FILES = {
    'model.gguf': {'url': _GGUF_BASE+'Qwen3.5-4B-Q4_K_M.gguf', 'bytes': 2740937888,
                   'sha256': '00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4'},
    'mmproj.gguf': {'url': _GGUF_BASE+'mmproj-F16.gguf', 'bytes': 672423616,
                    'sha256': 'cd88edcf8d031894960bb0c9c5b9b7e1fea6ebee02b9f7ce925a00d12891f864'},
    'tokenizer.json': {'url': _QWEN_BASE+'tokenizer.json', 'bytes': 12807982,
                       'sha256': '5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42'},
    'LICENSE': {'url': _QWEN_BASE+'LICENSE', 'bytes': 11544,
                'sha256': 'bbedc3fda3305820b977265f01b8619d87570a6739de3a5582c3464840f1e57a'},
}


def bundle_digest():
    return hashlib.sha256(json.dumps(WINDOWS_FILES, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def model_identity(model, digest):
    if model.split(':')[0] == 'embeddinggemma': return embedding_identity(model, digest)
    return hashlib.sha256(json.dumps([model, digest, ENGINE_ID]).encode()).hexdigest()


def bundle_directory(runtime):
    return Path(runtime)/'windows-models'/bundle_digest()


def bundle_files(runtime, *, verify=True):
    return _bundle_files(bundle_directory(runtime), verify=verify)


def _bundle_files(root, *, verify=True):
    if root.is_symlink(): raise ValueError('모델 폴더 경로가 변경되었습니다')
    files = []
    kinds = {'model.gguf': 'model', 'mmproj.gguf': 'projector', 'tokenizer.json': 'json', 'LICENSE': 'license'}
    for name, expected in WINDOWS_FILES.items():
        path = root/name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()) or path.stat().st_size != expected['bytes']:
            raise ValueError('검증된 Windows 모델 파일을 준비하세요')
        if verify:
            with path.open('rb') as handle:
                if hashlib.file_digest(handle, 'sha256').hexdigest() != expected['sha256']: raise ValueError('Windows 모델 파일 검증 실패')
            if name.endswith('.gguf'):
                with path.open('rb') as handle:
                    if handle.read(8) != b'GGUF\x03\0\0\0': raise ValueError('지원하지 않는 GGUF 형식')
        files.append({'path': path, 'kind': kinds[name], 'digest': 'sha256:'+expected['sha256'], 'size': expected['bytes']})
    return files


def tokenizer_profile(runtime):
    try:
        files = bundle_files(runtime, verify=False)
        path = next(row['path'] for row in files if row['kind'] == 'json')
        expected = WINDOWS_FILES['tokenizer.json']['sha256']
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected: return None
        return {'path': str(path.resolve()), 'sha256': expected, 'model': 'qwen3.5:4b',
                'model_digest': model_identity('qwen3.5:4b', bundle_digest())}
    except (OSError, ValueError): return None


class WindowsModels(DirectModels):
    embedding_architecture = 'x64'
    embedding_worker = 'EmbeddingWorker.exe'
    generation_timeout = 900

    def check_embedding_engine(self):
        super().check_embedding_engine()
        try:
            record=json.loads((self.engine_dir/'receipt.json').read_bytes());files=record['files']
            if 'cpu_dispatch'in record and (record['cpu_dispatch']!=CPU_DISPATCH or not CPU_WORKERS.issubset(files)):
                raise ValueError('Windows CPU 모델 엔진 구성을 확인하세요')
            if any((self.engine_dir/name).is_symlink()for name in files):raise ValueError('Windows 모델 엔진 경로 오류')
            for path in [*self.engine_dir.iterdir(),*(self.engine_dir/'lib').rglob('*')]:
                if path.suffix.lower()in ('.exe','.dll')and path.relative_to(self.engine_dir).as_posix()not in files:
                    raise ValueError('검증하지 않은 Windows 모델 실행 파일이 있습니다')
        except (OSError,KeyError,TypeError,json.JSONDecodeError):raise ValueError('Windows 모델 엔진과 검증 기록을 준비하세요')from None

    def _worker(self,name):
        self.check_embedding_engine()
        record=json.loads((self.engine_dir/'receipt.json').read_bytes())
        if name=='ModelWorker'and (record.get('generation_engine')!=ENGINE_ID or 'ModelWorker.exe'not in record['files']):
            raise ValueError('검증한 Windows 생성 엔진이 아닙니다')
        suffix='-avx2'if record.get('cpu_dispatch')==CPU_DISPATCH and cpu_supports_avx2(self.engine_dir/'WindowsCpu.exe')else''
        return str(self.engine_dir/(name+suffix+'.exe'))

    def _generation_command(self):
        return [self._worker('ModelWorker'), str(self.engine_dir/'lib')]

    def _embedding_command(self,path):
        return [self._worker('EmbeddingWorker'),str(path),str(self.engine_dir/'lib')]

    async def asset(self, model):
        if model in ('embeddinggemma', 'embeddinggemma:latest'): return await super().asset(model)
        if model != 'qwen3.5:4b': raise ValueError('직접 실행이 검증되지 않은 모델입니다')
        async with self.asset_lock:
            try:
                files = bundle_files(self.runtime, verify=False)
                stamp = tuple((str(row['path']), *(getattr(row['path'].stat(), key) for key in ('st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))) for row in files)
                if model in self.assets and self.assets[model][0] == stamp: return self.assets[model][1]
                files = await asyncio.to_thread(bundle_files, self.runtime)
                asset = {'model': model, 'digest': bundle_digest(), 'format': 'gguf', 'files': files}
                self.assets[model] = stamp, asset
                return asset
            except OSError: raise ValueError('검증된 Windows 모델 파일을 준비하세요') from None

    async def view(self, model):
        await self.asset(model)
        return bundle_directory(self.runtime)

    async def status(self, model):
        if model in ('embeddinggemma', 'embeddinggemma:latest'): return await super().status(model)
        asset = await self.asset(model)
        await asyncio.to_thread(self.check_embedding_engine)
        try:
            record = json.loads((self.engine_dir/'receipt.json').read_bytes())
            if record.get('generation_engine') != ENGINE_ID or 'ModelWorker.exe' not in record['files']:
                raise ValueError('검증한 Windows 생성 엔진이 아닙니다')
        except (OSError, KeyError, TypeError, json.JSONDecodeError): raise ValueError('Windows 생성 엔진과 검증 기록을 준비하세요') from None
        if not self._engine_checked:
            result = await self._call(check=True)
            if result.get('engine') != ENGINE_ID: raise ValueError('검증한 Windows 생성 엔진이 아닙니다')
            self._engine_checked = True
        return {'accessible': True, 'vision': True, 'completion': True, 'embedding': False,
                'digest': model_identity(model, asset['digest']), 'context_limit': CONTEXT_LIMIT}

    async def generate(self, config, messages, images, schema, *, output_limit, **kwargs):
        if type(output_limit) is not int or not 1 <= output_limit <= 4096: raise ValueError('출력 예산 오류')
        if (not isinstance(messages, list) or not messages or
                any(not isinstance(row, dict) or row.get('role') not in ('system', 'user', 'assistant') or
                    not isinstance(row.get('content'), str) for row in messages) or
                sum(len(row['content']) for row in messages) > 1_000_000): raise ValueError('모델 메시지 오류')
        if schema is not None and not isinstance(schema, dict): raise ValueError('출력 schema 오류')
        if len(images) > 4: raise ValueError('이미지는 최대 4개입니다')
        for path in images:
            path = Path(path)
            if not path.is_file() or path.stat().st_size > 20*1024**2: raise ValueError('이미지 파일 오류')
            with path.open('rb') as stream: signature = stream.read(8)
            if not (signature.startswith(b'\xff\xd8\xff') or signature == b'\x89PNG\r\n\x1a\n'): raise ValueError('PNG·JPEG 이미지만 지원합니다')
        return await super().generate(config, messages, images, schema, output_limit=output_limit, **kwargs)

    def catalog(self):
        from .local_models import CATALOG
        embedding = CATALOG['embeddinggemma']
        return [{'model': 'qwen3.5:4b', 'runner': 'llamacpp', 'license': 'Apache-2.0',
                 'license_url': 'https://www.apache.org/licenses/LICENSE-2.0',
                 'bytes': sum(row['bytes'] for row in WINDOWS_FILES.values()), 'digest': bundle_digest(),
                 'verified': True, 'downloadable': True},
                {'model': 'embeddinggemma', 'runner': 'ggml', 'license': embedding['license'],
                 'license_url': 'https://ai.google.dev/gemma/terms', **embedding['runners']['ggml'],
                 'verified': True, 'downloadable': True}]

    async def available(self):
        rows = []
        for entry in self.catalog():
            model = entry['model']
            installed = bundle_directory(self.runtime).exists() if model == 'qwen3.5:4b' else (self.runtime/'ollama-models/manifests/registry.ollama.ai/library/embeddinggemma/latest').is_file()
            if not installed: continue
            try:
                status = await self.status(model)
                rows.append({'name': model, 'size': entry['bytes'], 'usable': True, **status})
            except ValueError as exc: rows.append({'name': model, 'size': entry['bytes'], 'usable': False, 'error': str(exc)})
        return {'connected': any(row['usable'] for row in rows), 'managed_connected': False,
                'models': rows, 'catalog': self.catalog(), 'download': self.progress,
                'model_directory': str(self.runtime), 'engine': 'direct'}

    async def pull(self, model, runner, *, client=None):
        if model == 'embeddinggemma': return await super().pull(model, runner, client=client)
        if model != 'qwen3.5:4b' or runner != 'llamacpp': raise ValueError('검증한 Windows 모델을 선택하세요')
        @asynccontextmanager
        async def connection():
            if client is not None: yield client
            else:
                async with httpx.AsyncClient(follow_redirects=True, trust_env=False, timeout=httpx.Timeout(180, connect=15)) as owned: yield owned
        self.progress = {'status': 'running', 'model': model, 'completed': 0, 'total': sum(row['bytes'] for row in WINDOWS_FILES.values())}
        parent = self.runtime/'windows-models'; parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix='.download-', dir=parent))
        try:
            destination = bundle_directory(self.runtime)
            if destination.exists():
                await asyncio.to_thread(bundle_files, self.runtime)
            else:
                async with connection() as transport:
                    for name, item in WINDOWS_FILES.items():
                        checksum = hashlib.sha256(); size = 0
                        with (stage/name).open('wb') as output:
                            async with transport.stream('GET', item['url']) as response:
                                response.raise_for_status()
                                async for block in response.aiter_bytes(256*1024):
                                    size += len(block)
                                    if size > item['bytes']: raise ValueError('모델 파일 크기 초과')
                                    output.write(block); checksum.update(block); self.progress['completed'] += len(block)
                            output.flush(); os.fsync(output.fileno())
                        if size != item['bytes'] or checksum.hexdigest() != item['sha256']: raise ValueError('모델 파일 검증 실패')
                await asyncio.to_thread(_bundle_files, stage)
                try: _rename_exclusive(stage, destination)
                except FileExistsError: await asyncio.to_thread(bundle_files, self.runtime)
                self.assets.pop(model, None)
                await self.asset(model)
            self.progress = {'status': 'done', 'model': model, 'runner': runner, 'digest': model_identity(model, bundle_digest())}
        except asyncio.CancelledError:
            self.progress = {'status': 'cancelled', 'model': model}; raise
        except (OSError, ValueError, KeyError, TypeError, httpx.HTTPError):
            self.progress = {'status': 'failed', 'model': model, 'error': '모델 파일 검증·다운로드에 실패했습니다. 기존 파일은 보존됩니다'}
        finally:
            if stage.exists(): shutil.rmtree(stage)
