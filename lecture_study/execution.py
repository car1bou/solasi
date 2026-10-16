"""Explicit child entry points shared by development and the bundled app."""
import sys

MODULES = {'material-worker':'lecture_study.material_worker',
           'qwen-worker':'lecture_study.qwen_asr', 'model-worker':'lecture_study.model_worker'}


def worker_command(kind, arguments):
    if kind not in MODULES: raise ValueError('지원하지 않는 내부 작업입니다')
    prefix = [sys.executable, kind] if getattr(sys,'frozen',False) else [sys.executable,'-m',MODULES[kind]]
    return prefix+list(map(str,arguments))
