"""Read existing model assets without asking a model server to open them."""
import hashlib
import json
import ctypes
import errno
import os
import shutil
import sys
import tempfile
import re
import struct
from pathlib import Path, PurePosixPath

MAX_JSON = 64 * 1024 * 1024
MAX_HEADER = 1024 * 1024


def _json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError('중복 모델 메타데이터 키')
            result[key] = value
        return result
    try: return json.loads(data, object_pairs_hook=unique)
    except (UnicodeError, json.JSONDecodeError): raise ValueError('모델 JSON 형식 오류') from None


def _safe_name(name):
    if not isinstance(name, str) or not name or '\\' in name: raise ValueError('모델 파일 이름 오류')
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or str(path) != name: raise ValueError('모델 파일 경로 오류')
    return name


def _blob(root, entry):
    digest = entry.get('digest', '')
    if not isinstance(digest, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
        raise ValueError('모델 digest 형식 오류')
    size = entry.get('size')
    if type(size) is not int or not 0 < size <= 64 * 1024**3: raise ValueError('모델 크기 오류')
    path = root/'blobs'/digest.replace(':', '-')
    if not path.resolve().is_relative_to(root/'blobs') or not path.is_file():
        raise ValueError('모델 blob 위치 또는 파일 없음')
    if path.stat().st_size != size: raise ValueError('모델 blob 크기가 다릅니다')
    with path.open('rb') as handle: actual = hashlib.file_digest(handle, 'sha256').hexdigest()
    if actual != digest[7:]: raise ValueError('모델 blob 해시가 다릅니다')
    return path


def _tensor_header(path):
    with path.open('rb') as handle:
        prefix = handle.read(8)
        if len(prefix) != 8: raise ValueError('tensor header 없음')
        length, = struct.unpack('<Q', prefix)
        if not 2 <= length <= MAX_HEADER or length + 8 > path.stat().st_size:
            raise ValueError('tensor header 크기 오류')
        header = _json(handle.read(length))
    if not isinstance(header, dict): raise ValueError('tensor header 형식 오류')
    data_size = path.stat().st_size - length - 8
    tensors = {}
    for key, value in header.items():
        if key == '__metadata__': continue
        if not isinstance(value, dict): raise ValueError('tensor 항목 형식 오류')
        offsets = value.get('data_offsets')
        shape = value.get('shape')
        if (not isinstance(offsets, list) or len(offsets) != 2 or
                any(type(n) is not int for n in offsets) or not 0 <= offsets[0] <= offsets[1] <= data_size or
                not isinstance(shape, list) or any(type(n) is not int or n < 0 for n in shape)):
            raise ValueError('tensor 범위 오류')
        tensors[key] = value
    if not tensors: raise ValueError('tensor 없음')
    return tensors


def installed_asset(models_dir: Path, model: str) -> dict:
    if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*(?::[A-Za-z0-9][A-Za-z0-9_.-]*)?', model):
        raise ValueError('설치된 로컬 모델 이름을 확인하세요')
    name, tag = model.split(':', 1) if ':' in model else (model, 'latest')
    root = models_dir.resolve()
    manifest = root/'manifests/registry.ollama.ai/library'/name/tag
    if (not manifest.resolve().is_relative_to(root/'manifests') or not manifest.is_file() or
            manifest.stat().st_size > MAX_JSON): raise ValueError('설치 모델 manifest 없음 또는 크기 오류')
    raw = manifest.read_bytes()
    value = _json(raw)
    if not isinstance(value, dict) or value.get('schemaVersion') != 2: raise ValueError('모델 manifest 형식 오류')
    layers = value.get('layers')
    if not isinstance(layers, list) or not 1 <= len(layers) <= 10000: raise ValueError('모델 layer 형식 오류')
    config = value.get('config')
    if not isinstance(config, dict): raise ValueError('모델 config 없음')
    _blob(root, config)
    files, names, keys, formats = [], set(), set(), set()
    for entry in layers:
        if not isinstance(entry, dict): raise ValueError('모델 layer 형식 오류')
        path = _blob(root, entry)
        kind = entry.get('mediaType', '').removeprefix('application/vnd.ollama.image.')
        if kind not in ('json', 'tensor', 'model'): continue
        filename = entry.get('name')
        if kind != 'model':
            _safe_name(filename)
            if filename in names: raise ValueError('중복 모델 파일 이름')
            names.add(filename)
        row = {**entry, 'path': path, 'kind': kind}
        if kind == 'json':
            if entry['size'] > MAX_JSON: raise ValueError('모델 JSON 크기 오류')
            if not filename.endswith('.json'): raise ValueError('모델 JSON 확장자 오류')
            _json(path.read_bytes())
        elif kind == 'tensor':
            row['tensors'] = _tensor_header(path)
            if keys.intersection(row['tensors']): raise ValueError('중복 tensor 키')
            keys.update(row['tensors'])
            formats.add('safetensors')
        else:
            with path.open('rb') as handle: prefix = handle.read(8)
            if prefix != b'GGUF' + struct.pack('<I', 3): raise ValueError('지원하지 않는 모델 형식')
            formats.add('gguf')
        files.append(row)
    if len(formats) != 1: raise ValueError('모델 가중치 형식을 확인하세요')
    return {'model': name+':'+tag, 'digest': hashlib.sha256(raw).hexdigest(),
            'format': formats.pop(), 'files': files}


def _rename_exclusive(source: Path, destination: Path):
    if os.name == 'nt':
        os.rename(source, destination)
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == 'darwin':
        rename = libc.renamex_np
        rename.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
        args = (os.fsencode(source), os.fsencode(destination), 4)  # RENAME_EXCL
    elif hasattr(libc, 'renameat2'):
        rename = libc.renameat2
        rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
        args = (-100, os.fsencode(source), -100, os.fsencode(destination), 1)  # RENAME_NOREPLACE
    else:
        raise OSError(errno.ENOSYS, 'Exclusive model-cache publication is unsupported')
    rename.restype = ctypes.c_int
    if rename(*args):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(destination))


class IncompleteModelView(ValueError):
    pass


def validate_mlx_view(asset: dict, destination: Path) -> Path:
    if destination.is_symlink(): raise ValueError('직접 실행 보기 경로가 변경되었습니다')
    index_path = destination/'model.safetensors.index.json'
    if index_path.is_symlink() or index_path.stat().st_size > MAX_JSON: raise ValueError('직접 실행 가중치 목록 오류')
    try: index = _json(index_path.read_bytes())
    except ValueError: raise IncompleteModelView('직접 실행 가중치 목록 작성이 중단되었습니다') from None
    weights = {key: f'model-{i:05d}.safetensors' for i, entry in enumerate(asset['files'])
               if entry['kind'] == 'tensor' for key in entry['tensors']}
    if index != {'weight_map': weights}: raise ValueError('직접 실행 가중치 목록이 변경되었습니다')
    expected = {entry['name'] for entry in asset['files'] if entry['kind'] == 'json'} | set(weights.values()) | {'model.safetensors.index.json'}
    if any(str(path.relative_to(destination)) not in expected for path in destination.rglob('*') if path.is_file() or path.is_symlink()):
        raise ValueError('직접 실행 보기에 추가 파일이 있습니다')
    for i, entry in enumerate(asset['files']):
        if entry['kind'] == 'json':
            target = destination/entry['name']
            if target.is_symlink() or not target.resolve().is_relative_to(destination.resolve()) or target.read_bytes() != entry['path'].read_bytes():
                raise ValueError('직접 실행 모델 보기 파일이 변경되었습니다')
        elif entry['kind'] == 'tensor':
            target = destination/f'model-{i:05d}.safetensors'
            if not target.is_symlink() or target.resolve() != entry['path'].resolve():
                raise ValueError('직접 실행 가중치 연결이 변경되었습니다')
    return destination


def prepare_mlx_view(asset: dict, destination: Path) -> Path:
    if asset['format'] != 'safetensors': raise ValueError('MLX tensor 모델이 아닙니다')
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.staging-'+destination.name+'-', dir=destination.parent))
    try:
        weights = {}
        for index, entry in enumerate(asset['files']):
            if entry['kind'] == 'json':
                path = staging/_safe_name(entry['name'])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(entry['path'].read_bytes())
            elif entry['kind'] == 'tensor':
                name = f'model-{index:05d}.safetensors'
                # Only read-only model loading uses this view; never save weights through it.
                (staging/name).symlink_to(entry['path'])
                weights.update({key: name for key in entry['tensors']})
        (staging/'model.safetensors.index.json').write_text(json.dumps({'weight_map': weights}))
        validate_mlx_view(asset, staging)
        _rename_exclusive(staging, destination)
    finally:
        if staging.exists(): shutil.rmtree(staging)
    return destination


def ensure_mlx_view(asset: dict, destination: Path) -> Path:
    try:
        return validate_mlx_view(asset, destination)
    except (FileNotFoundError, IncompleteModelView):
        if destination.is_dir():
            # Preserve app-owned partial views from older builds; source blobs stay untouched.
            preserved = Path(tempfile.mkdtemp(prefix='.incomplete-'+destination.name+'-', dir=destination.parent))
            try: _rename_exclusive(destination, preserved/'previous')
            except FileNotFoundError: preserved.rmdir()
    try:
        return prepare_mlx_view(asset, destination)
    except FileExistsError:
        return validate_mlx_view(asset, destination)
