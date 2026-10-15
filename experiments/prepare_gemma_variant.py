"""Prepare a user-approved catalog model; official single-stream fallback for stalled GGUF pulls."""
import argparse,asyncio,hashlib,json,shutil,time
from pathlib import Path
import httpx
from lecture_study.local_models import OwnedOllama,CATALOG,installed_models
ROOT=Path(__file__).resolve().parents[1];RUNTIME=ROOT/'.local-state/runtime'
MODELS=('gemma4:e2b-it-qat','gemma4:e4b-it-qat','gemma4:12b')
async def main(name,direct=False):
 runner='mlx' if name=='gemma4:12b' else 'llamacpp';expected=CATALOG[name]['runners'][runner];output=ROOT/'docs/verification/gemma4-variant-downloads.json'
 assert shutil.disk_usage(RUNTIME).free>expected['bytes']+4*1024**3,'Need 4GiB working space after download'
 manager=OwnedOllama(RUNTIME);began=time.monotonic();verified=[]
 try:
  if direct:
   assert runner=='llamacpp'
   async with httpx.AsyncClient(timeout=httpx.Timeout(120,connect=20),follow_redirects=True,trust_env=False) as client:
    response=await client.get('https://registry.ollama.ai/v2/library/gemma4/manifests/'+name.split(':')[1]);response.raise_for_status();assert hashlib.sha256(response.content).hexdigest()==expected['digest']
    for layer in response.json()['layers']:
     if layer['size']<1024**3:continue
     digest=layer['digest'].split(':')[1];target=RUNTIME/'ollama-models/blobs'/('sha256-'+digest);partial=target.with_name(target.name+'-direct-partial')
     if target.exists():assert target.stat().st_size==layer['size'];continue
     offset=partial.stat().st_size if partial.exists() else 0
     assert 0<=offset<=layer['size']
     while offset<layer['size']:
      end=min(layer['size'],offset+64*1024**2)-1
      for attempt in range(3):
       try:
        async with client.stream('GET','https://registry.ollama.ai/v2/library/gemma4/blobs/'+layer['digest'],headers={'Range':f'bytes={offset}-{end}'}) as blob:
         blob.raise_for_status();assert blob.headers.get('content-range')==f'bytes {offset}-{end}/{layer["size"]}','Unexpected byte range'
         with partial.open('ab') as handle:
          async for chunk in blob.aiter_bytes(1024**2):handle.write(chunk)
        assert partial.stat().st_size==end+1;offset=end+1;break
       except (httpx.HTTPError,AssertionError):
        offset=partial.stat().st_size if partial.exists() else 0
        if attempt==2:raise
        end=min(layer['size'],offset+64*1024**2)-1;await asyncio.sleep(2)
      print(json.dumps({'model':name,'verified_transfer_bytes':offset,'total':layer['size']}),flush=True)
     with partial.open('rb') as handle:assert hashlib.file_digest(handle,'sha256').hexdigest()==digest
     partial.replace(target);verified.append(digest)
  url=await manager.start();task=asyncio.create_task(manager.pull(name,runner))
  while not task.done():
   await asyncio.wait({task},timeout=15);print(json.dumps({'model':name,'seconds':round(time.monotonic()-began),'progress':manager.progress},ensure_ascii=False),flush=True)
  await task;assert manager.progress['status']=='done',manager.progress
  actual=next(m for m in (await installed_models(url))['models'] if m['name']==name);assert actual['digest']==expected['digest']
  report=json.loads(output.read_text()) if output.exists() else {'models':[]};report['models']=[m for m in report['models'] if m['name']!=name]
  report['models'].append(actual|{'runner':runner,'license':'Apache-2.0','catalog_bytes':expected['bytes'],'seconds':time.monotonic()-began,'free_bytes_after':shutil.disk_usage(RUNTIME).free,'direct_official_blob_sha256_verified':verified});output.write_text(json.dumps(report,ensure_ascii=False,indent=2));print('Download verified '+name,flush=True)
 finally:await manager.stop()
if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('model',choices=MODELS);parser.add_argument('--direct',action='store_true');args=parser.parse_args();asyncio.run(main(args.model,args.direct))
