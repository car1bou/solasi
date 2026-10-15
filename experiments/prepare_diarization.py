"""Prepare the isolated Mac arm64 / Python3.12 diarization comparison (79MB).

Public fixed artifacts only; does not install into the app Python or bundle models.
"""
import hashlib,json,platform,subprocess,sys,urllib.request
from pathlib import Path
assert platform.system()=='Darwin'and platform.machine()=='arm64'and sys.version_info[:2]==(3,12),'Use Mac arm64 Python3.12'
root=Path(__file__).resolve().parents[1];folder=root/'.local-state/runtime/diarization-20261015';folder.mkdir(parents=True,exist_ok=True)
items=[
('segmentation.onnx','https://huggingface.co/csukuangfj/sherpa-onnx-pyannote-segmentation-3-0/resolve/9403a6902bb58e3d5ae8c7e77c3422de279db2e0/model.onnx',5992913,'220ad67ca923bef2fa91f2390c786097bf305bceb5e261d4af67b38e938e1079'),
('resnet34.onnx','https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/wespeaker_en_voxceleb_resnet34_LM.onnx',26530550,'e9848563da86f263117134dfd7ad63c92355b37de492b55e325400c9d9c39012'),
('camplusplus.onnx','https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/wespeaker_en_voxceleb_CAM%2B%2B.onnx',29292684,'c46fad10b5f81e1aa4a60c162714208577093655076c5450f8c469e522ec54ef'),
('sherpa_onnx-1.13.8-cp312-cp312-macosx_11_0_arm64.whl','https://files.pythonhosted.org/packages/78/6e/8d9b92e95896ec500084e706529f5637eff797246e74c498922f6aa13a53/sherpa_onnx-1.13.8-cp312-cp312-macosx_11_0_arm64.whl',2146858,'04b9268c348e9f4bd61315754ad06b02a3c185d3d7770acd8e2dcee9c2e039f9'),
('sherpa_onnx_core-1.13.8-py3-none-macosx_11_0_arm64.whl','https://files.pythonhosted.org/packages/8c/2a/2a47b423fe009bbbcb6d7eed7bcba755d6f9ae923b5664c7208128c32d06/sherpa_onnx_core-1.13.8-py3-none-macosx_11_0_arm64.whl',9552498,'9312bbd46c93e31cecd3abda9cc8e71881d86cc3da3c35c7445ab04025b9fc3e'),
('numpy-2.5.4-cp312-cp312-macosx_14_0_arm64.whl','https://files.pythonhosted.org/packages/31/2f/5ea3570fcb8ccd0882bea99436a513b2c85dad8f774a2057849130a8fb99/numpy-2.5.4-cp312-cp312-macosx_14_0_arm64.whl',5451717,'9cb18a327b49c5c337f972b03682f6a49855525faaf3c0d3e9c96cd0fd8880a8')]
manifest={'purpose':'Isolated local Korean diarization comparison, no Alt bundle copied; original app/model env untouched','ready':False,'hash_pinning':'Embedding hashes measured at first download from fixed Sherpa release assets; other hashes verified against upstream metadata','files':[]}
for name,url,size,expected in items:
 path=folder/name
 if not path.is_file():
  with urllib.request.urlopen(url,timeout=90)as response,path.with_suffix(path.suffix+'.partial').open('wb')as out:
   length=0
   while chunk:=response.read(1024**2):
    length+=len(chunk)
    if length>size:raise ValueError('Unexpected asset size: '+name)
    out.write(chunk)
  path.with_suffix(path.suffix+'.partial').replace(path)
 assert path.stat().st_size==size,name
 with path.open('rb')as handle:actual=hashlib.file_digest(handle,'sha256').hexdigest()
 if expected:assert actual==expected,name
 manifest['files'].append({'file':name,'url':url,'bytes':size,'sha256':actual,'upstream_sha256_available':name not in ('resnet34.onnx','camplusplus.onnx')});(folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2));print('Verified',name,size,flush=True)
for name,url in [('segmentation-LICENSE','https://huggingface.co/csukuangfj/sherpa-onnx-pyannote-segmentation-3-0/resolve/9403a6902bb58e3d5ae8c7e77c3422de279db2e0/LICENSE'),('wespeaker-pretrained.md','https://raw.githubusercontent.com/wenet-e2e/wespeaker/master/docs/pretrained.md'),('sherpa-LICENSE','https://raw.githubusercontent.com/k2-fsa/sherpa-onnx/master/LICENSE')]:
 with urllib.request.urlopen(url,timeout=30)as response:data=response.read(256*1024)
 (folder/name).write_bytes(data)
venv=root/'.local-state/runtime/diarization-eval-venv'
if not (venv/'bin/python').is_file():subprocess.run([sys.executable,'-m','venv',str(venv)],check=True)
subprocess.run([str(venv/'bin/python'),'-m','pip','install','--no-index','--no-deps',*[str(folder/name)for name,*_ in items if name.endswith('.whl')]],check=True)
subprocess.run([str(venv/'bin/python'),'-c','import sherpa_onnx,numpy;print(sherpa_onnx.__version__,numpy.__version__)'],check=True)
manifest['ready']=True;manifest['licenses']={'segmentation':'MIT','sherpa':'Apache-2.0','wespeaker_weights':'CC BY 4.0; see official pretrained model notice','numpy':'BSD-3-Clause'};(folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
