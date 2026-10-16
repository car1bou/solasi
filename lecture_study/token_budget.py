"""Verified local text tokenizer; other models retain the byte upper bound."""
import hashlib,json,re
from functools import lru_cache
from pathlib import Path
from tokenizers import Tokenizer


def local_profile(config,runtime):
    if config.provider=='local':return direct_profile(config,runtime)
    if config.provider!='ollama' or config.model!='qwen3.5:4b' or runtime is None:return None
    from .local_models import CATALOG
    digest=CATALOG[config.model]['runners']['mlx']['digest'];root=Path(runtime)/'ollama-models/blobs'
    try:
        raw=(root/('sha256-'+digest)).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=digest:return None
        manifest=json.loads(raw);selected=json.loads((root.parent/'manifests/registry.ollama.ai/library/qwen3.5/4b').read_bytes())
        # Ollama adds distribution/index layers when it saves a selected tag.
        selected['layers']=[l for l in selected['layers']if l.get('mediaType')not in ('application/vnd.ollama.manifest.list.v2+json','application/vnd.docker.distribution.manifest.v2+json')]
        if selected!=manifest:return None
        layer=next(l for l in manifest['layers']if l.get('name')=='tokenizer.json')
        checksum=layer['digest'].removeprefix('sha256:')
        if not re.fullmatch('[0-9a-f]{64}',checksum):return None
        path=root/('sha256-'+checksum)
        if not path.is_file():return None
        return {'path':str(path.resolve()),'sha256':checksum,'model':config.model,'model_digest':digest}
    except (OSError,ValueError,KeyError,TypeError,AttributeError,StopIteration):return None


@lru_cache(maxsize=2)
def tokenizer(path,checksum,size,mtime):
    raw=Path(path).read_bytes()
    if len(raw)>32*1024*1024 or hashlib.sha256(raw).hexdigest()!=checksum:raise ValueError('요약 토크나이저가 변경되었습니다. 모델을 확인한 뒤 새 작업을 요청하세요')
    try:return Tokenizer.from_str(raw.decode())
    except Exception:raise ValueError('요약 토크나이저를 읽을 수 없습니다') from None


def input_bound(config,messages,schema,profile):
    if config.provider not in ('ollama','local') or config.model!=profile['model']:raise ValueError('요약 모델과 토크나이저가 일치하지 않습니다')
    try:stat=Path(profile['path']).stat();model=tokenizer(profile['path'],profile['sha256'],stat.st_size,stat.st_mtime_ns)
    except OSError:raise ValueError('요약 토크나이저를 찾을 수 없습니다') from None
    # shortcut: verified Qwen text chat reserves 200 template tokens; render templates before adding tools or custom models.
    return sum(len(model.encode(m['content'],add_special_tokens=False).ids)for m in messages)+len(model.encode(json.dumps(schema),add_special_tokens=False).ids)+200


def direct_profile(config,runtime):
    if runtime is None:return None
    from .direct_models import model_identity
    from .mlx_direct import SUPPORTED_MODELS
    from .local_models import CATALOG
    if config.model!='qwen3.5:4b' or config.model not in SUPPORTED_MODELS:return None
    try:
        name,tag=config.model.split(':',1);root=Path(runtime)/'ollama-models'
        manifest=root/'manifests/registry.ollama.ai/library'/name/tag
        if manifest.stat().st_size>64*1024*1024:return None
        raw=manifest.read_bytes()
        digest=hashlib.sha256(raw).hexdigest()
        if digest not in (SUPPORTED_MODELS[config.model]['asset_digest'],CATALOG[config.model]['runners']['mlx']['digest']):return None
        layer=next(row for row in json.loads(raw)['layers']if row.get('name')=='tokenizer.json')
        checksum=layer['digest'].removeprefix('sha256:')
        if not re.fullmatch('[0-9a-f]{64}',checksum):return None
        path=root/'blobs'/('sha256-'+checksum)
        if not path.is_file() or not path.resolve().is_relative_to((root/'blobs').resolve()):return None
        return {'path':str(path.resolve()),'sha256':checksum,'model':config.model,'model_digest':model_identity(config.model,digest)}
    except(OSError,ValueError,KeyError,TypeError,StopIteration):return None
