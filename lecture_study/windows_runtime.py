"""Windows executables are private, receipt-verified build artifacts, never PATH tools."""
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

CPU_DISPATCH='avx2-fma-f16c-v1'
CPU_FILES={'bin/WindowsCpu.exe',*[f'bin/{name}{suffix}.exe'for name in ('whisper-cli','whisper-vad-speech-segments')for suffix in ('','-avx2')]}


def engine_root(destination, component):
    base = Path(sys.executable).parent/'engines' if getattr(sys,'frozen',False) else Path(destination)
    return base/component


def verified_engine(destination, component, required):
    from .runtime import matches
    root = engine_root(destination, component)
    try:
        receipt = root/'receipt.json'
        if receipt.stat().st_size > 1024*1024:raise ValueError('엔진 검증 기록이 너무 큽니다')
        record = json.loads(receipt.read_bytes())
        files = record['files']
        if record.get('platform') != 'win32-x64' or not isinstance(files,dict) or not 1 <= len(files) <= 2048:
            raise ValueError('Windows 엔진 검증 기록을 확인하세요')
        if not set(required).issubset(files):raise ValueError('필요한 Windows 엔진 파일이 없습니다')
        if component=='asr'and 'cpu_dispatch'in record:
            if record['cpu_dispatch']!=CPU_DISPATCH or not CPU_FILES.issubset(files):raise ValueError('Windows CPU 전사 엔진 구성을 확인하세요')
        for name, item in files.items():
            if (not isinstance(name,str) or not name or '\\' in name or ':' in name or
                    str(PurePosixPath(name)) != name or PurePosixPath(name).is_absolute() or
                    '..' in PurePosixPath(name).parts):
                raise ValueError('Windows 엔진 파일 경로 오류')
            path=root/name
            if (not path.resolve().is_relative_to(root.resolve()) or path.is_symlink() or
                    type(item.get('bytes')) is not int or item['bytes']<=0 or
                    not re.fullmatch(r'[a-f0-9]{64}',item.get('sha256','')) or not matches(path,item)):
                raise ValueError('Windows 엔진 파일 검증 실패')
        for path in root.rglob('*'):
            if path.suffix.lower() in ('.dll','.exe') and path.relative_to(root).as_posix() not in files:
                raise ValueError('검증하지 않은 Windows 실행 파일이 있습니다')
        return root, record
    except (OSError,KeyError,TypeError,AttributeError,json.JSONDecodeError):
        raise ValueError('Windows 내장 엔진과 파일 검증 기록을 준비하세요') from None


def cpu_supports_avx2(verified_probe):
    try:
        result=subprocess.run([str(verified_probe)],capture_output=True,check=True,timeout=5,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if len(result.stdout)>4096:raise ValueError('Windows CPU 검사 응답 크기 오류')
        capabilities=json.loads(result.stdout)
        if type(capabilities.get('version'))is not int or capabilities['version']!=1 or type(capabilities.get('avx2_compatible'))is not bool:raise ValueError('Windows CPU 검사 응답 오류')
        return capabilities['avx2_compatible']
    except (OSError,subprocess.SubprocessError,ValueError,TypeError,AttributeError):raise ValueError('Windows CPU 실행 기능을 확인할 수 없습니다')from None


def asr_binary(destination,name):
    root,record=verified_engine(destination,'asr',['bin/'+name+'.exe'])
    suffix=''
    if record.get('cpu_dispatch')==CPU_DISPATCH and name in ('whisper-cli','whisper-vad-speech-segments'):
        if cpu_supports_avx2(root/'bin/WindowsCpu.exe'):suffix='-avx2'
    return root/'bin'/(name+suffix+'.exe')


def status(component,destination):
    from .runtime import manifest,matches
    spec=manifest();item=spec['components'][component]
    if component=='ollama':
        return {'label':item['label'],'version':item['version'],'ready':False,'bytes':0,'error_code':'embedded_engine_only'}
    keys=('turbo','vad','whisper_notice','vad_notice') if component=='asr' else tuple(item['assets'])
    required=['bin/'+name+'.exe' for name in ('whisper-cli','ffmpeg','ffprobe')] if component=='asr' else ['bin/tesseract.exe']
    try:
        _,record=verified_engine(destination,component,required)
        binaries=True
        if record.get('version')!=item['version']:raise ValueError('Windows 엔진 버전이 다릅니다')
    except ValueError:
        binaries=False;record={}
    ready=binaries and all(matches(Path(destination)/spec['assets'][key]['path'],spec['assets'][key]) for key in keys)
    return {'label':item['label'],'version':item['version'],'ready':ready,
            'bytes':sum(spec['assets'][key]['bytes'] for key in keys),
            'error_code':None if ready else 'missing_or_hash_mismatch',
            **({'voice_activity_ready':binaries and 'bin/whisper-vad-speech-segments.exe' in record.get('files',{})} if component=='asr' else {})}


def prepare(component,destination,progress=None,cancel=None):
    from .runtime import manifest,download_verified,check_cancel
    if component not in ('asr','ocr'):raise ValueError('Windows 앱은 내장 실행 엔진을 사용합니다')
    required=['bin/'+name+'.exe' for name in ('whisper-cli','whisper-vad-speech-segments','ffmpeg','ffprobe')] if component=='asr' else ['bin/tesseract.exe']
    verified_engine(destination,component,required)
    spec=manifest()
    keys=('turbo','vad','whisper_notice','vad_notice') if component=='asr' else spec['components']['ocr']['assets']
    for key in keys:
        check_cancel(cancel)
        asset=spec['assets'][key]
        download_verified(asset,Path(destination)/asset['path'],progress,cancel)
    result=status(component,destination)
    if not result['ready']:raise ValueError('Windows 엔진·모델 준비 후 검증 실패')
    return result
