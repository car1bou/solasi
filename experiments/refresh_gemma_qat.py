"""Reconstruct official corrected QAT files from verified headers and cached tensors, then verify full SHA."""
import argparse,asyncio,hashlib,json,shutil
from pathlib import Path
import httpx
from lecture_study.local_models import OwnedOllama
ROOT=Path(__file__).resolve().parents[1];RUNTIME=ROOT/'.local-state/runtime'
OLD={'e2b':{'main':'3646b4c147cd235a44d91df1546d3b7d8e29b547dbe4e1f80856419aa455e6fd','projector':'58c187648007cab392bd5678b87e862c3e8794017deb945feea2cf256195e96a'},'e4b':{'main':'e8b6a059ba86947a44ace84d6e5679795bc41862c25c30513142588f0e9dba1d','projector':'c6398448d84a4836fdedf58f9775979e69ae0cc4dfdf4d697b5597693a555b12'}}
async def main(variant,comparison,output):
 details=json.loads(comparison.read_text());files={};proof=[];blobs=RUNTIME/'ollama-models/blobs'
 assert shutil.disk_usage(blobs).free>sum(details[k]['latest_file_size'] for k in ('main','projector'))+2*1024**3
 for kind in ('main','projector'):
  item=details[kind];assert item['descriptor_bytes_identical'] and item['tensor_descriptors_identical']
  digest=item['expected_official_full_file_sha256'];target=blobs/('sha256-'+digest)
  if not target.exists():
   matches=[p for p in blobs.glob('sha256-'+OLD[variant][kind]+'*') if len(p.name)==71];assert len(matches)==1
   source=matches[0];assert source.stat().st_size==item['old_file_size']
   header=RUNTIME/'gguf-headers'/(variant+'-'+kind+'-'+item['latest_header_sha256']+'.bin');header.parent.mkdir(parents=True,exist_ok=True)
   if not header.exists():
    original_header=Path(item['latest_header_path'])
    if original_header.exists():data=original_header.read_bytes()
    else:
     async with httpx.AsyncClient(timeout=120,follow_redirects=True,trust_env=False) as client:
      response=await client.get(item['url'],headers={'Range':'bytes=0-'+str(item['latest']['data_start']-1)});response.raise_for_status();assert response.status_code==206;data=response.content
    assert len(data)==item['latest']['data_start'] and hashlib.sha256(data).hexdigest()==item['latest_header_sha256'];header.write_bytes(data)
   data=header.read_bytes();assert len(data)==item['latest']['data_start'] and hashlib.sha256(data).hexdigest()==item['latest_header_sha256']
   partial=target.with_name(target.name+'-rebuilding');assert not partial.exists();hasher=hashlib.sha256()
   with source.open('rb') as original,partial.open('xb') as rebuilt:
    rebuilt.write(data);hasher.update(data);original.seek(item['old']['data_start'])
    while chunk:=original.read(16*1024**2):rebuilt.write(chunk);hasher.update(chunk)
   if hasher.hexdigest()!=digest or partial.stat().st_size!=item['latest_file_size']:
    partial.unlink();raise ValueError('Reconstruction differs from the official file; do not use')
   partial.replace(target)
  with target.open('rb') as handle:assert hashlib.file_digest(handle,'sha256').hexdigest()==digest
  files['model.gguf' if kind=='main' else 'mmproj.gguf']='sha256:'+digest
  proof.append({k:item[k] for k in ('url','official_revision','latest_file_size','expected_official_full_file_sha256','latest_header_sha256')}|{'kind':kind,'full_file_sha256_matches':True})
 name='lecture-study-gemma4-'+variant+'-qat:validated';manager=OwnedOllama(RUNTIME)
 try:
  url=await manager.start()
  async with httpx.AsyncClient(base_url=url,timeout=180,trust_env=False) as client:
   r=await client.post('/api/create',json={'model':name,'files':files,'stream':False});r.raise_for_status();assert r.json().get('status')=='success',r.text
   r=await client.get('/api/tags');r.raise_for_status();actual=next(m for m in r.json()['models'] if m['name']==name)
   r=await client.post('/api/show',json={'model':name});r.raise_for_status()
  report={'model':name,'digest':actual['digest'],'size':actual['size'],'license':'Apache-2.0','runner':'llamacpp','files':proof,'capabilities':r.json().get('capabilities'),'comparison':str(comparison)};output.write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False),flush=True)
 finally:await manager.stop()
if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('variant',choices=['e2b','e4b']);parser.add_argument('comparison',type=Path);parser.add_argument('--output',required=True,type=Path);args=parser.parse_args();asyncio.run(main(args.variant,args.comparison,args.output))
