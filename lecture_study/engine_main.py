"""Bundled engine: pipe transport by default, explicit owned child commands only."""
import json
import os
from pathlib import Path
import sys


def main():
    import multiprocessing
    multiprocessing.freeze_support()
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',DO_NOT_TRACK='1')
    command = sys.argv[1] if len(sys.argv)>1 else ''
    if command == '--self-check':
        import importlib.metadata
        from lecture_study.runtime import manifest
        from lecture_study.mlx_direct import VERSIONS
        import liteparse
        print(json.dumps({'frozen':bool(getattr(sys,'frozen',False)),
                          'versions':{name:importlib.metadata.version(name) for name in (*VERSIONS,'liteparse','mlx-audio')},
                          'runtime_manifest':manifest()['version'] if 'version' in manifest() else 'present'}))
    elif command == 'material-worker':
        from lecture_study.material_worker import main as run
        sys.argv.pop(1);run()
    elif command == 'qwen-worker':
        from lecture_study.qwen_asr import worker
        if len(sys.argv)!=5:raise ValueError('Qwen 작업 인자 오류')
        worker(*(Path(value) for value in sys.argv[2:]))
    elif command == 'model-worker':
        from lecture_study.model_worker import main as run
        sys.argv.pop(1);run()
    else:
        from lecture_study.native_worker import main as run
        run()


if __name__=='__main__':main()
