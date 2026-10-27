import asyncio
import hashlib
import json
import os
import platform
import socket
from pathlib import Path
import httpx
from .providers import checked_body,local_url
from .runtime import component_status

VERSION='0.40.3'
CATALOG={
    'qwen3.5:4b':{'license':'Apache-2.0','runners':{'mlx':{'bytes':3973456016,'digest':'7f3251fa6878a78a606bcb3c074283306e5ad2ea411a7774a9dd98a4bc7f2d13'},'llamacpp':{'bytes':3324175492,'digest':'d8b0f5e9760cd1682034f292d7ef72ec46f432149be0df7574bf2d6e92e38c04'}}},
    'embeddinggemma-2:270m-mxfp8-text':{'license':'Apache-2.0','runners':{'mlx':{'bytes':442218503,'digest':'47c561d1a77f8f4ec4f855a7704db5a893e0c51c368cec31eddeae758943b6f6'}}},
    'embeddinggemma':{'license':'Gemma Terms','runners':{'ggml':{'bytes':621875917,'digest':'85462619ee721b466c5927d109d4cb765861907d5417b9109caebc4e614679f1'}}},
}


def catalog():
    runners=('mlx','llamacpp','ggml') if platform.system()=='Darwin' and platform.machine()=='arm64' else ('llamacpp','ggml')
    result=[]
    for model,entry in CATALOG.items():
        runner=next((r for r in runners if r in entry['runners']),None)
        if runner:result.append({'model':model,'license':entry['license'],'license_url':'https://ai.google.dev/gemma/terms' if model=='embeddinggemma' else 'https://www.apache.org/licenses/LICENSE-2.0','runner':runner,**entry['runners'][runner]})
    return result


class OwnedOllama:
    def __init__(self,runtime):
        self.runtime=runtime;self.process=None;self.url=None;self.lock=asyncio.Lock();self.pull_task=None;self.progress={'status':'idle'}

    async def start(self):
        async with self.lock:
            if self.process is not None and self.process.returncode is None: return self.url
            binary=self.runtime/'ollama'/('ollama.exe' if os.name=='nt' else 'ollama')
            if not binary.is_file() or not (await asyncio.to_thread(component_status,'ollama',self.runtime))['ready']: raise ValueError('앱 Ollama 엔진 준비·파일 검증이 필요합니다')
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            models=self.runtime/'ollama-models';models.mkdir(parents=True,exist_ok=True)
            env={key:value for key,value in os.environ.items() if not key.startswith('OLLAMA_')}
            env.update(OLLAMA_HOST=f'127.0.0.1:{port}',OLLAMA_MODELS=str(models.resolve()),OLLAMA_NO_CLOUD='1',OLLAMA_NUM_PARALLEL='1',OLLAMA_DEBUG_LOG_REQUESTS='false',OLLAMA_NOHISTORY='1')
            # Ollama serve still uses its standard ~/.ollama identity; never inspect or replace that key.
            self.process=await asyncio.create_subprocess_exec(str(binary),'serve',env=env,stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL,cwd=self.runtime)
            url=f'http://127.0.0.1:{port}'
            async with httpx.AsyncClient(timeout=1,trust_env=False) as client:
                for _ in range(100):
                    if self.process.returncode is not None: break
                    try:
                        body=checked_body(await client.get(url+'/api/version'))
                        if body.get('version')!=VERSION:
                            await self.stop();raise ValueError('앱 Ollama 엔진 버전이 일치하지 않습니다')
                        self.url=url;return url
                    except httpx.HTTPError: await asyncio.sleep(.1)
            await self.stop()
            raise ValueError('앱 Ollama 엔진 시작 실패')

    async def stop(self):
        if self.pull_task and not self.pull_task.done():
            self.pull_task.cancel();await asyncio.gather(self.pull_task,return_exceptions=True)
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try: await asyncio.wait_for(self.process.wait(),5)
            except asyncio.TimeoutError: self.process.kill();await self.process.wait()
        self.process=None;self.url=None

    async def pull(self,model,runner):
        if model not in CATALOG or runner not in CATALOG[model]['runners']: raise ValueError('준비할 모델을 확인하세요')
        if self.url is None: raise ValueError('앱 로컬 엔진을 먼저 시작하세요')
        expected=CATALOG[model]['runners'][runner];self.progress={'status':'running','model':model,'runner':runner,'completed':0,'total':expected['bytes']}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(180,connect=15),trust_env=False) as client:
                name,tag=(model.split(':',1)+['latest'])[:2] if ':' in model else (model,'latest')
                response=await client.get('https://registry.ollama.ai/v2/library/'+name+'/manifests/'+tag,headers={'Accept':'application/vnd.ollama.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json'})
                manifest=checked_body(response)
                digests=[entry.get('digest','').removeprefix('sha256:') for entry in manifest.get('manifests',[])]+[hashlib.sha256(response.content).hexdigest()]
                if expected['digest'] not in digests: raise ValueError('모델 배포가 변경되었습니다. 다운로드 정보를 갱신해야 합니다')
                async with client.stream('POST',self.url+'/api/pull',json={'model':model,'runner':runner,'stream':True}) as result:
                    if result.status_code>=400: raise ValueError('모델 다운로드 연결 실패 · HTTP '+str(result.status_code))
                    async for line in result.aiter_lines():
                        if not line: continue
                        row=json.loads(line)
                        if row.get('error'): raise ValueError('모델 다운로드 실패 · 저장 공간·네트워크를 확인하고 재시도하세요')
                        self.progress.update(stage=row.get('status','다운로드 중'),completed=row.get('completed',0),total=row.get('total',expected['bytes']))
                body=checked_body(await client.get(self.url+'/api/tags'))
                actual=next((r for r in body.get('models',[]) if r.get('name') in (model,model+':latest')),None)
                if not actual or actual.get('digest')!=expected['digest'] or actual.get('remote_model') or actual.get('remote_host'): raise ValueError('다운로드 모델의 digest가 일치하지 않습니다')
            self.progress={'status':'done','model':model,'runner':runner,'digest':expected['digest']}
        except asyncio.CancelledError:
            self.progress={'status':'cancelled','model':model};raise
        except (httpx.HTTPError,ValueError,KeyError,TypeError) as exc:
            self.progress={'status':'failed','model':model,'error':str(exc) if isinstance(exc,ValueError) else '모델 다운로드 연결 실패'}

    def begin_pull(self,model,runner):
        if self.pull_task and not self.pull_task.done(): raise ValueError('다른 모델 다운로드가 진행 중입니다')
        if self.url is None: raise ValueError('앱 로컬 엔진을 먼저 시작하세요')
        if model not in CATALOG or runner not in CATALOG[model]['runners']: raise ValueError('준비할 모델을 확인하세요')
        self.progress={'status':'queued','model':model};self.pull_task=asyncio.create_task(self.pull(model,runner))
        return self.progress


async def installed_models(url):
    url=local_url(url)
    try:
        async with httpx.AsyncClient(timeout=5,trust_env=False) as client:
            version=checked_body(await client.get(url+'/api/version'))
            body=checked_body(await client.get(url+'/api/tags'))
        return {'connected':True,'version':version.get('version'),'models':[{'name':row.get('name'),'digest':row.get('digest'),'size':row.get('size')} for row in body.get('models',[]) if isinstance(row,dict) and not row.get('remote_model') and not row.get('remote_host') and not row.get('name','').endswith(':cloud')]}
    except httpx.HTTPError: raise ValueError('Ollama에 연결할 수 없습니다. 엔진·주소를 확인하세요') from None
