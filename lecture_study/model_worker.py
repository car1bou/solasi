"""A single owned generation process; stdout is a bounded result frame."""
import importlib.metadata
import json
import os
from pathlib import Path
import struct
import sys

MAX_INPUT = 10 * 1024 * 1024
MAX_OUTPUT = 8 * 1024 * 1024


def main():
    output = os.fdopen(os.dup(sys.stdout.fileno()), 'wb', buffering=0)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    try:
        from .mlx_direct import generate, VERSIONS, ENGINE_ID
        if '--check' in sys.argv:
            versions = {key: importlib.metadata.version(key) for key in VERSIONS}
            if versions != VERSIONS: raise ValueError('검증된 직접 실행 엔진 버전이 아닙니다')
            result = {'engine':ENGINE_ID}
        else:
            prefix = sys.stdin.buffer.read(4)
            if len(prefix) != 4: raise ValueError('모델 요청 헤더 없음')
            size, = struct.unpack('>I', prefix)
            if not 0 < size <= MAX_INPUT: raise ValueError('모델 입력 크기 오류')
            raw = sys.stdin.buffer.read(size)
            if len(raw) != size: raise ValueError('모델 입력이 중단되었습니다')
            request = json.loads(raw)
            result = generate(Path(request['view']), request['messages'], [Path(path) for path in request['images']], request['schema'], request['output_limit'], request['context_limit'])
        reply = {'ok':True,'result':result}
    except Exception as exc:
        reply = {'ok':False,'error':str(exc)[:500] if isinstance(exc,(ValueError,importlib.metadata.PackageNotFoundError)) else '직접 실행 모델 처리 실패'}
    encoded = json.dumps(reply,ensure_ascii=False).encode()
    if len(encoded) > MAX_OUTPUT: encoded = b'{"ok":false,"error":"Model response too large"}'
    output.write(struct.pack('>I',len(encoded))+encoded)
    output.close()


if __name__ == '__main__': main()
