"""Verified model files executed by owned processes, never model listeners."""
import asyncio
import hashlib
import json
import os
import re
import tempfile
import time
import httpx
from pathlib import Path
import struct
import sys

from .model_assets import installed_asset, ensure_mlx_view
from .mlx_direct import ENGINE_ID, SUPPORTED_MODELS

EMBEDDING_ENGINE = 'llama.cpp-b11669/ollama-embeddinggemma-v1'
EMBEDDING_FORMAT = EMBEDDING_ENGINE+'/mean/l2/768/search-v1/chunk512-v1'
EMBEDDING_ASSET = 'd1a9ad04c64272d78aab43641947f5cb18eec9e8cbf13d26223caeae2432d112'
EMBEDDING_WEIGHT = '0800cbac9c2064dde519420e75e512a83cb360de3ad5df176185dc69652fc515'


def model_identity(model, digest):
    engine = EMBEDDING_FORMAT if model.split(':')[0] == 'embeddinggemma' else SUPPORTED_MODELS[model]['engine']
    return hashlib.sha256(json.dumps([model.split(':')[0]+':latest' if model == 'embeddinggemma' else model,digest,engine]).encode()).hexdigest()


class EmbeddingInputTooLong(ValueError):
    pass


async def read_result(reader, limit=8*1024*1024):
    try:
        length, = struct.unpack('>I', await reader.readexactly(4))
        if not 0 < length <= limit: raise ValueError('직접 실행 응답 크기 오류')
        reply = json.loads(await reader.readexactly(length))
        if not isinstance(reply,dict): raise ValueError('직접 실행 응답 형식 오류')
        return reply
    except (asyncio.IncompleteReadError,UnicodeError,json.JSONDecodeError):
        raise ValueError('직접 실행 모델 응답이 중단되었습니다') from None


class DirectModels:
    def __init__(self, runtime, cache_dir, *, python=None, engine_dir=None):
        self.runtime = Path(runtime)
        self.cache_dir = Path(cache_dir)
        self.python = str(python or sys.executable)
        self.engine_dir = Path(engine_dir) if engine_dir else Path(sys.executable).parent/'engines' if getattr(sys,'frozen',False) else self.runtime/'direct-engines'
        self.lock = asyncio.Lock()
        self.asset_lock = asyncio.Lock()
        self.assets = {}
        self.processes = set()
        self.pull_task = None
        self.progress = {'status':'idle'}
        self.url = None
        self.process = None
        self._engine_checked = False
        self._embedding_receipt = None
        self._embedding = None

    def _generation_command(self):
        return [self.python, 'model-worker'] if getattr(sys,'frozen',False) else [self.python,'-m','lecture_study.model_worker']

    def _stamp(self, model):
        name, tag = model.split(':',1) if ':' in model else (model,'latest')
        root = (self.runtime/'ollama-models').resolve()
        manifest = root/'manifests/registry.ollama.ai/library'/name/tag
        if manifest.stat().st_size > 64*1024*1024: raise ValueError('모델 manifest 크기 오류')
        value = json.loads(manifest.read_bytes())
        paths = [manifest] + [root/'blobs'/row['digest'].replace(':','-') for row in [value['config'],*value['layers']]]
        return tuple((str(path.resolve()), *(getattr(path.stat(),field) for field in ('st_ino','st_size','st_mtime_ns','st_ctime_ns'))) for path in paths)

    def validate_asset(self, model, asset):
        from .local_models import CATALOG
        expected = SUPPORTED_MODELS[model]['asset_digest'] if model in SUPPORTED_MODELS else EMBEDDING_ASSET
        runner = 'mlx' if model in SUPPORTED_MODELS else 'ggml'
        if asset['digest'] not in (expected,CATALOG[model]['runners'][runner]['digest']):raise ValueError('검증한 설치 모델과 파일이 다릅니다')
        if asset['format']!=('safetensors' if runner=='mlx' else 'gguf'):raise ValueError('검증한 모델 형식이 아닙니다')
        if model == 'embeddinggemma' and not any(entry['digest']=='sha256:'+EMBEDDING_WEIGHT for entry in asset['files']):raise ValueError('검증한 임베딩 가중치가 아닙니다')

    async def asset(self, model):
        model = 'embeddinggemma' if model == 'embeddinggemma:latest' else model
        if model not in SUPPORTED_MODELS and model != 'embeddinggemma': raise ValueError('직접 실행이 검증되지 않은 모델입니다')
        async with self.asset_lock:
            try:
                stamp = await asyncio.to_thread(self._stamp,model)
                if model in self.assets and self.assets[model][0] == stamp: return self.assets[model][1]
                asset = await asyncio.to_thread(installed_asset,self.runtime/'ollama-models',model)
                self.validate_asset(model,asset)
                if await asyncio.to_thread(self._stamp,model) != stamp: raise ValueError('모델 파일이 변경되었습니다')
                self.assets[model] = stamp, asset
                return asset
            except (OSError,KeyError,TypeError,json.JSONDecodeError):
                raise ValueError('검증된 직접 실행 모델 파일을 준비하세요') from None

    async def view(self, model):
        asset = await self.asset(model)
        async with self.asset_lock:
            return await asyncio.to_thread(ensure_mlx_view, asset, self.cache_dir/asset['digest'])

    async def _spawn(self, command):
        env = dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',TOKENIZERS_PARALLELISM='false')
        try:process = await asyncio.create_subprocess_exec(*command,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,env=env)
        except OSError:raise ValueError('직접 실행 엔진을 시작할 수 없습니다') from None
        self.processes.add(process)
        return process

    async def _close(self, process):
        async def reap():
            try:
                if process.returncode is not None:return
                try:process.terminate()
                except ProcessLookupError:pass
                try:await asyncio.wait_for(process.wait(),2)
                except TimeoutError:
                    try:process.kill()
                    except ProcessLookupError:pass
                    await process.wait()
            finally:self.processes.discard(process)
        cleanup=asyncio.create_task(reap());cancelled=False
        while not cleanup.done():
            try:await asyncio.shield(cleanup)
            except asyncio.CancelledError:cancelled=True
        await cleanup
        if cancelled:raise asyncio.CancelledError

    async def _call(self, payload=None, *, check=False):
        process = await self._spawn(self._generation_command()+(['--check'] if check else []))
        try:
            if payload is not None:
                encoded = json.dumps(payload,ensure_ascii=False).encode()
                if len(encoded)>10*1024*1024: raise ValueError('직접 실행 입력이 너무 큽니다')
                process.stdin.write(struct.pack('>I',len(encoded))+encoded)
                await process.stdin.drain()
            process.stdin.close()
            result = await asyncio.wait_for(read_result(process.stdout),180)
            await asyncio.wait_for(process.wait(),5)
            if process.returncode or result.get('ok') is not True: raise ValueError(result.get('error','직접 실행 모델 처리 실패'))
            return result['result']
        except TimeoutError: raise ValueError('직접 실행 모델 제한 시간 초과') from None
        finally: await self._close(process)

    def check_embedding_engine(self):
        try:
            receipt=self.engine_dir/'receipt.json'
            if receipt.stat().st_size>65536:raise ValueError('임베딩 엔진 기록 크기 오류')
            record=json.loads(receipt.read_bytes())
            if record['engine']!=EMBEDDING_ENGINE or record['revision']!='620d2225cc436ab0b001e3200e590e3b286ef9ab' or record['architecture']!='arm64':raise ValueError('검증한 임베딩 엔진이 아닙니다')
            files=record['files']
            if not isinstance(files,dict) or 'EmbeddingWorker' not in files or len(files)>32:raise ValueError('임베딩 엔진 파일 목록 오류')
            stamp=[]
            for name,expected in files.items():
                path=self.engine_dir/name
                if not path.resolve().is_relative_to(self.engine_dir.resolve()) or not path.is_file():raise ValueError('임베딩 엔진 경로 오류')
                info=path.stat();stamp.append((name,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns))
                if info.st_size!=expected['bytes']:raise ValueError('임베딩 엔진 크기 오류')
            verified={str((self.engine_dir/name).resolve()) for name in files}
            for path in (self.engine_dir/'lib').iterdir():
                if str(path.resolve()) not in verified or not path.is_file():raise ValueError('검증하지 않은 임베딩 라이브러리 연결')
                stamp.append((path.name,str(path.resolve()),os.readlink(path) if path.is_symlink() else None))
            signature=(hashlib.sha256(receipt.read_bytes()).hexdigest(),tuple(stamp))
            if self._embedding_receipt==signature:return
            for name,expected in files.items():
                with (self.engine_dir/name).open('rb') as handle:
                    if hashlib.file_digest(handle,'sha256').hexdigest()!=expected['sha256']:raise ValueError('임베딩 엔진 파일이 변경되었습니다')
            self._embedding_receipt=signature
        except (OSError,KeyError,TypeError,json.JSONDecodeError):raise ValueError('직접 임베딩 엔진과 검증 기록을 준비하세요') from None

    async def status(self, model):
        asset = await self.asset(model)
        if model.split(':')[0] == 'embeddinggemma':
            await asyncio.to_thread(self.check_embedding_engine)
            return {'accessible':True,'vision':False,'completion':False,'embedding':True,'digest':model_identity(model,asset['digest']),'context_limit':2048}
        if not self._engine_checked:
            result = await self._call(check=True)
            if result.get('engine') != ENGINE_ID: raise ValueError('검증된 직접 실행 엔진이 아닙니다')
            self._engine_checked = True
        return {'accessible':True,'vision':SUPPORTED_MODELS[model]['vision'],'completion':True,'embedding':False,'digest':model_identity(model,asset['digest']),'context_limit':SUPPORTED_MODELS[model]['context_tokens']}

    async def generate(self, config, messages, images, schema, *, output_limit, before_local=None, expected_digest=None):
        started=time.perf_counter()
        async with self.lock:
            acquired=time.perf_counter()
            await self._release_embedding()
            if before_local: await before_local()
            admitted=time.perf_counter()
            status = await self.status(config.model)
            if expected_digest is not None and status['digest'] != expected_digest: raise ValueError('직접 실행 모델이 변경되었습니다. 새 작업을 요청하세요')
            view = await self.view(config.model)
            prepared=time.perf_counter()
            if before_local: await before_local()
            late_wait=time.perf_counter()-prepared
            result = await self._call({'view':str(view),'messages':messages,'images':[str(path) for path in images],'schema':schema,'output_limit':output_limit,'context_limit':min(config.context_limit,status['context_limit'])})
            completed=time.perf_counter()
            if (await self.status(config.model))['digest']!=status['digest']: raise ValueError('생성 중 직접 실행 모델이 변경되었습니다')
            result.setdefault('usage',{}).setdefault('timings_ms',{}).update(lock_wait_ms=(acquired-started)*1000,transcription_wait_ms=(admitted-acquired+late_wait)*1000,asset_prepare_ms=(prepared-admitted)*1000,worker_roundtrip_ms=(completed-prepared-late_wait)*1000,total_ms=(time.perf_counter()-started)*1000)
            return result

    async def _release_embedding(self, owner=None):
        if self._embedding is None or owner is not None and self._embedding[0] is not owner:return
        _,process=self._embedding
        self._embedding=None
        await self._close(process)

    async def release_embedding(self, owner):
        if self._embedding is None or self._embedding[0] is not owner:return
        async with self.lock:await self._release_embedding(owner)

    async def embed(self, model, text, *, before_local=None,timings=None,owner=None):
        if not isinstance(text,str) or not text or len(text.encode())>100000: raise EmbeddingInputTooLong('임베딩 입력 한도')
        started=time.perf_counter()
        async with self.lock:
            acquired=time.perf_counter()
            process=None
            try:
                if owner is None or self._embedding is not None and self._embedding[0] is not owner:await self._release_embedding()
                if before_local:await before_local()
                admitted=time.perf_counter()
                status=await self.status(model)
                identity=(status['digest'],self._embedding_receipt)
                if owner is not None:
                    if owner.identity is not None and owner.identity!=identity:raise ValueError('색인 중 임베딩 모델·엔진이 변경되었습니다. 재색인하세요')
                    owner.identity=identity
                asset=await self.asset(model)
                path=next(entry['path'] for entry in asset['files'] if entry['kind']=='model')
                prepared=time.perf_counter()
                if before_local:await before_local()
                late_wait=time.perf_counter()-prepared
                reused=owner is not None and self._embedding is not None
                if reused:
                    process=self._embedding[1]
                    if process.returncode is not None:raise ValueError('임베딩 엔진이 종료되었습니다. 재색인하세요')
                else:
                    process=await self._spawn([str(self.engine_dir/'EmbeddingWorker'),str(path),str(self.engine_dir/'lib')])
                    if owner is not None:self._embedding=(owner,process)
                    ready=await asyncio.wait_for(read_result(process.stdout),60)
                    if any(ready.get(key)!=value for key,value in {'ready':True,'dim':768,'pooling':'mean','context_tokens':2048,'engine':EMBEDDING_ENGINE}.items()): raise ValueError('직접 임베딩 엔진 정보가 다릅니다')
                loaded=time.perf_counter()
                data=text.encode();process.stdin.write(struct.pack('>I',len(data))+data);await process.stdin.drain()
                reply=await asyncio.wait_for(read_result(process.stdout),60)
                if reply.get('error'):
                    if reply['error'].get('code')=='context_limit' and reply.get('fatal') is False: raise EmbeddingInputTooLong('임베딩 문맥 한도')
                    raise ValueError('직접 임베딩 처리 실패')
                from .retrieval import vector
                values=vector(reply.get('vector'))
                if len(values)!=768: raise ValueError('직접 임베딩 차원이 다릅니다')
                if ((await self.status(model))['digest'],self._embedding_receipt)!=identity:raise ValueError('임베딩 실행 중 모델·엔진이 변경되었습니다')
                if timings is not None:
                    timings.update(lock_wait_ms=(acquired-started)*1000,transcription_wait_ms=(admitted-acquired+late_wait)*1000,asset_prepare_ms=(prepared-admitted)*1000,worker_start_load_ms=(loaded-prepared-late_wait)*1000,inference_roundtrip_ms=(time.perf_counter()-loaded)*1000,total_before_cleanup_ms=(time.perf_counter()-started)*1000,worker_reused=reused)
                return list(values)
            except EmbeddingInputTooLong:raise
            except BaseException as exc:
                if owner is not None:await self._release_embedding(owner)
                if isinstance(exc,TimeoutError):raise ValueError('직접 임베딩 제한 시간 초과') from None
                raise
            finally:
                if owner is None and process is not None:await self._close(process)

    async def available(self):
        from .local_models import catalog
        rows=[]
        for entry in catalog():
            try:
                name,tag=entry['model'].split(':',1) if ':' in entry['model'] else (entry['model'],'latest')
                if not (self.runtime/'ollama-models/manifests/registry.ollama.ai/library'/name/tag).is_file():continue
                try:status=await self.status(entry['model']);rows.append({'name':entry['model'],'digest':status['digest'],'size':entry['bytes'],'usable':True,**status})
                except ValueError as exc:rows.append({'name':entry['model'],'size':entry['bytes'],'usable':False,'error':str(exc)})
            except OSError:continue
        return {'connected':any(row['usable'] for row in rows),'managed_connected':False,'models':rows,'catalog':self.catalog(),'download':self.progress,'model_directory':str(self.runtime/'ollama-models'),'engine':'direct'}

    def catalog(self):
        from .local_models import catalog
        return [entry|{'verified':entry['model'] in SUPPORTED_MODELS or entry['model']=='embeddinggemma','downloadable':entry['model'] in SUPPORTED_MODELS or entry['model']=='embeddinggemma'} for entry in catalog()]

    def begin_pull(self, model, runner):
        if self.pull_task and not self.pull_task.done():raise ValueError('다른 모델 다운로드가 진행 중입니다')
        if not any(row['model']==model and row['runner']==runner and row['downloadable'] for row in self.catalog()):raise ValueError('직접 실행을 검증한 모델을 선택하세요')
        self.progress={'status':'queued','model':model}
        self.pull_task=asyncio.create_task(self.pull(model,runner))
        return self.progress

    async def pull(self, model, runner, *, client=None):
        from .local_models import CATALOG
        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def connection():
            if client is not None:yield client
            else:
                async with httpx.AsyncClient(follow_redirects=True,trust_env=False,timeout=httpx.Timeout(180,connect=15)) as owned:yield owned
        if model not in SUPPORTED_MODELS and model!='embeddinggemma':raise ValueError('직접 실행을 검증한 모델을 선택하세요')
        expected=CATALOG[model]['runners'].get(runner)
        if expected is None:raise ValueError('검증한 모델 형식을 선택하세요')
        self.progress={'status':'running','model':model,'completed':0,'total':expected['bytes']}
        root=self.runtime/'ollama-models';name,tag=model.split(':',1) if ':' in model else (model,'latest')
        base='https://registry.ollama.ai/v2/library/'+name
        partial=None
        try:
            async with connection() as transport:
                raw=bytearray()
                async with transport.stream('GET',base+'/manifests/sha256:'+expected['digest']) as response:
                    response.raise_for_status()
                    async for block in response.aiter_bytes():
                        if len(raw)+len(block)>64*1024*1024:raise ValueError('모델 manifest가 너무 큽니다')
                        raw.extend(block)
                if hashlib.sha256(raw).hexdigest()!=expected['digest']:raise ValueError('모델 배포 digest가 다릅니다')
                manifest=json.loads(raw)
                entries={entry['digest']:entry for entry in [manifest['config'],*manifest['layers']]}
                (root/'blobs').mkdir(parents=True,exist_ok=True)
                for digest,entry in entries.items():
                    size=entry['size']
                    if not re.fullmatch(r'sha256:[0-9a-f]{64}',digest) or type(size)is not int or not 0<size<=64*1024**3:raise ValueError('모델 blob 정보 오류')
                    target=root/'blobs'/digest.replace(':','-')
                    if target.exists():
                        from .model_assets import _blob
                        await asyncio.to_thread(_blob,root.resolve(),entry)
                        self.progress['completed']+=size
                        continue
                    handle=tempfile.NamedTemporaryFile(dir=root/'blobs',prefix='.download-',delete=False)
                    partial=Path(handle.name);written=0;checksum=hashlib.sha256()
                    with handle:
                        async with transport.stream('GET',base+'/blobs/'+digest) as response:
                            response.raise_for_status()
                            async for block in response.aiter_bytes(256*1024):
                                if written+len(block)>size:raise ValueError('모델 blob 크기 초과')
                                handle.write(block);checksum.update(block);written+=len(block);self.progress['completed']+=len(block)
                        handle.flush();os.fsync(handle.fileno())
                    if written!=size or checksum.hexdigest()!=digest[7:]:raise ValueError('모델 blob 검증 실패')
                    try:os.link(partial,target)
                    except FileExistsError:
                        from .model_assets import _blob
                        await asyncio.to_thread(_blob,root.resolve(),entry)
                    partial.unlink();partial=None
                target=root/'manifests/registry.ollama.ai/library'/name/tag
                target.parent.mkdir(parents=True,exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=target.parent,prefix='download-',delete=False) as handle:
                    partial=Path(handle.name);handle.write(raw);handle.flush();os.fsync(handle.fileno())
                asset=await asyncio.to_thread(installed_asset,root,name+':'+partial.name)
                self.validate_asset(model,asset)
                os.replace(partial,target);partial=None
                self.assets.pop(model,None)
                self.progress={'status':'done','model':model,'runner':runner,'digest':model_identity(model,asset['digest'])}
        except asyncio.CancelledError:self.progress={'status':'cancelled','model':model};raise
        except (OSError,ValueError,KeyError,TypeError,httpx.HTTPError):self.progress={'status':'failed','model':model,'error':'모델 파일 검증·다운로드에 실패했습니다. 기존 파일은 보존됩니다'}
        finally:
            if partial is not None:partial.unlink(missing_ok=True)

    async def stop(self):
        if self.pull_task and not self.pull_task.done():self.pull_task.cancel();await asyncio.gather(self.pull_task,return_exceptions=True)
        self._embedding=None
        await asyncio.gather(*(self._close(process) for process in list(self.processes)))


class DirectEmbeddings:
    def __init__(self, manager, before_request, *, reuse=False):
        self.manager,self.before_request=manager,before_request
        self.reuse=reuse
        self.identity=None

    async def close(self):await self.manager.release_embedding(self)

    async def status(self, model):
        status=await self.manager.status(model)
        if self.identity is not None and (status['digest'],self.manager._embedding_receipt)!=self.identity:
            await self.close()
            raise ValueError('색인 중 임베딩 모델·엔진이 변경되었습니다. 재색인하세요')
        return status

    async def embed(self, model, text):
        return await self.manager.embed(model,text,before_local=self.before_request,**({'owner':self}if self.reuse else {}))
