import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import signal
import subprocess
import tarfile
import tempfile
import threading
import time
from pathlib import Path
from urllib.request import urlopen

MANIFEST=Path(__file__).parent.parent/'runtime-manifest.json'
_verified=set()


def manifest():
    return json.loads(MANIFEST.read_text())


def matches(path,item):
    if not path.is_file() or path.stat().st_size!=item['bytes']: return False
    stamp=(str(path),path.stat().st_mtime_ns,path.stat().st_size,item['sha256'])
    if stamp not in _verified:
        with path.open('rb') as handle:
            if hashlib.file_digest(handle,'sha256').hexdigest()!=item['sha256']: return False
        _verified.add(stamp)
    return True


def check_cancel(cancel):
    if cancel and cancel.is_set(): raise InterruptedError('런타임 준비 취소')


def download_verified(item,target,progress=None,cancel=None):
    target.parent.mkdir(parents=True,exist_ok=True)
    if matches(target,item): return target
    temporary=target.with_suffix(target.suffix+'.part');temporary.unlink(missing_ok=True)
    digest=hashlib.sha256();size=0
    try:
        with urlopen(item['url'],timeout=20) as response,temporary.open('wb') as output:
            while chunk:=response.read(1024*1024):
                check_cancel(cancel);size+=len(chunk)
                if size>item['bytes']: raise ValueError('다운로드 파일 용량이 일치하지 않습니다')
                digest.update(chunk);output.write(chunk)
                if progress: progress({'stage':'download','completed':size,'total':item['bytes'],'file':target.name})
            output.flush();os.fsync(output.fileno())
        check_cancel(cancel)
        if size!=item['bytes'] or digest.hexdigest()!=item['sha256']: raise ValueError('다운로드 파일 해시·용량 검증 실패')
        temporary.replace(target);return target
    finally: temporary.unlink(missing_ok=True)


def component_status(component,destination):
    spec=manifest();item=spec['components'][component];root=Path(destination)
    checks=[];activity_ready=False;activity_name='bin/whisper-vad-speech-segments'
    if component=='ocr': checks=[matches(root/spec['assets'][key]['path'],spec['assets'][key]) for key in item['assets']]
    elif component=='ollama':
        checks=[matches(root/'ollama'/name,values) for name,values in item['files'].items()]
        checks.extend((root/'ollama'/name).is_symlink() and os.readlink(root/'ollama'/name)==target for name,target in item['symlinks'].items())
        checks.append(matches(root/'ollama/LICENSE',spec['assets']['ollama_license']))
    else:
        receipt=root/'asr/receipt.json'
        if receipt.is_file():
            try:
                installed=json.loads(receipt.read_text());checks=[installed['version']==item['version']]
                checks.extend(matches(root/'asr'/name,values) for name,values in installed['files'].items()if name!=activity_name)
                activity_ready=activity_name in installed['files'] and matches(root/'asr'/activity_name,installed['files'][activity_name])
                checks.append(set(installed['files'])>={'bin/whisper-cli','bin/ffmpeg','bin/ffprobe','sources/whisper.cpp/LICENSE','sources/ffmpeg/COPYING.LGPLv2.1'})
            except (OSError,ValueError,KeyError,TypeError): checks=[False]
        else: checks=[matches(root/name,values) for name,values in item['reference_build'].items()]
        checks.extend(matches(root/spec['assets'][key]['path'],spec['assets'][key]) for key in ('turbo','vad','whisper_notice','vad_notice'))
    return ({'voice_activity_ready':activity_ready}if component=='asr'else {})|{'label':item['label'],'version':item['version'],'ready':bool(checks) and all(checks),'bytes':sum(spec['assets'][key]['bytes'] for key in item['assets']),'error_code':None if checks and all(checks) else 'missing_or_hash_mismatch'}


def probe_runtime(config):
    components={key:component_status(key,config.runtime_dir) for key in manifest()['components']}
    try: parser_ready=importlib.metadata.version('liteparse')=='2.16.0'
    except importlib.metadata.PackageNotFoundError: parser_ready=False
    components['parser']={'label':'PDF·이미지 추출 · LiteParse','ready':parser_ready,'version':'2.16.0','bytes':0,'error_code':None if parser_ready else 'package_missing'}
    ready=all(c['ready'] for c in components.values())
    return {'ready':ready,'components':components,'error_code':None if ready else 'runtime_incomplete','platform':platform.system()+'/'+platform.machine(),'directory':str(config.runtime_dir.resolve())}


def unpack(archive,destination,strip_root=False):
    destination.mkdir(parents=True,exist_ok=True)
    with tarfile.open(archive) as tar:
        tar.extractall(destination,filter='data')
    if strip_root:
        contents=list(destination.iterdir())
        if len(contents)!=1 or not contents[0].is_dir(): raise ValueError('소스 archive 루트가 유효하지 않습니다')
        top=contents[0]
        for path in top.iterdir(): path.rename(destination/path.name)
        top.rmdir()


def build_command(argv,cwd,log,cancel):
    env=os.environ|{'GIT_CEILING_DIRECTORIES':str(cwd.parent.resolve())}
    with log.open('ab') as output:
        process=subprocess.Popen(list(map(str,argv)),cwd=cwd,env=env,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
        started=time.monotonic()
        try:
            while process.poll() is None:
                check_cancel(cancel)
                if time.monotonic()-started>1800: raise ValueError('엔진 빌드 제한 시간 초과')
                time.sleep(.2)
            if process.returncode: raise ValueError('엔진 빌드 실패 · Apple Command Line Tools와 빌드 로그를 확인하세요')
        finally:
            if process.poll() is None:
                os.killpg(process.pid,signal.SIGTERM)
                try:process.wait(timeout=3)
                except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()


def publish_directory(stage,target):
    backup=target.with_name(target.name+'.previous')
    if backup.exists(): raise ValueError('이전 준비 복구 폴더를 확인하세요')
    if target.exists(): target.rename(backup)
    try: stage.rename(target)
    except BaseException:
        if backup.exists():backup.rename(target)
        raise
    if backup.exists():shutil.rmtree(backup)


def prepare_runtime(component,destination,progress=None,cancel=None):
    spec=manifest()
    if component not in spec['components']: raise ValueError('준비할 엔진을 선택하세요')
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    target=destination/spec['components'][component]['install_dir'];backup=target.with_name(target.name+'.previous')
    if backup.exists():
        if target.exists() and component_status(component,destination)['ready']:shutil.rmtree(backup)
        else:
            if target.exists():shutil.rmtree(target)
            backup.rename(target)
    status=component_status(component,destination)
    if status['ready']and (component!='asr'or status['voice_activity_ready']):return status
    if component!='ocr' and (platform.system()!='Darwin' or platform.machine()!='arm64'): raise ValueError('현재 엔진 자동 준비는 Apple Silicon macOS용입니다')
    if component=='asr' and subprocess.run(['/usr/bin/xcode-select','-p'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode: raise ValueError('Apple Command Line Tools 설치 후 전사 엔진 준비를 다시 실행하세요')
    item=spec['components'][component]
    with tempfile.TemporaryDirectory(prefix='.prepare-',dir=destination) as folder:
        stage=Path(folder);output=stage/item['install_dir']
        for key in item['assets']:
            asset=spec['assets'][key]
            # Engine/model files stay private; originals are never inputs to preparation.
            target=destination/asset['path'] if asset['path'].startswith(('downloads/','models/')) else stage/asset['path']
            existing=destination/asset['path']
            if target!=existing and matches(existing,asset):target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(existing,target)
            else:download_verified(asset,target,progress,cancel)
        if component=='ollama':
            license=(stage/'ollama/LICENSE').read_bytes();unpack(destination/spec['assets']['ollama']['path'],output);(output/'LICENSE').write_bytes(license)
        elif component=='asr':
            output.mkdir();sources=output/'sources';bin_dir=output/'bin';bin_dir.mkdir()
            unpack(destination/spec['assets']['whisper_source']['path'],sources/'whisper.cpp',True)
            unpack(destination/spec['assets']['ffmpeg_source']['path'],sources/'ffmpeg',True)
            unpack(destination/spec['assets']['cmake']['path'],output/'cmake',True)
            cmake=output/'cmake/CMake.app/Contents/bin/cmake';build=output/'build/whisper';log=destination/'prepare-asr.log'
            if progress:progress({'stage':'build','file':'whisper.cpp','completed':0,'total':2})
            build_command([cmake,'-S',sources/'whisper.cpp','-B',build,'-DCMAKE_BUILD_TYPE=Release','-DWHISPER_BUILD_IS_DEV=OFF','-DWHISPER_BUILD_TESTS=OFF','-DWHISPER_BUILD_SERVER=OFF','-DBUILD_SHARED_LIBS=OFF','-DGGML_OPENMP=OFF','-DGGML_METAL=ON','-DGGML_METAL_EMBED_LIBRARY=ON'],output,log,cancel)
            build_command([cmake,'--build',build,'--target','whisper-cli','whisper-vad-speech-segments','--parallel','4'],output,log,cancel)
            for name in ('whisper-cli','whisper-vad-speech-segments'):shutil.copy2(build/'bin'/name,bin_dir/name)
            if progress:progress({'stage':'build','file':'FFmpeg','completed':1,'total':2})
            ff=sources/'ffmpeg';prefix=output/'ffmpeg'
            build_command([ff/'configure','--prefix='+str(prefix),'--disable-doc','--disable-debug','--disable-ffplay','--disable-autodetect'],ff,log,cancel)
            build_command(['/usr/bin/make','-j4'],ff,log,cancel);build_command(['/usr/bin/make','install'],ff,log,cancel)
            for name in ('ffmpeg','ffprobe'):shutil.copy2(prefix/'bin'/name,bin_dir/name)
            for name,args in (('whisper-cli',['--version']),('ffmpeg',['-version']),('ffprobe',['-version'])):build_command([bin_dir/name,*args],output,log,cancel)
            files={}
            for name in ('bin/whisper-cli','bin/whisper-vad-speech-segments','bin/ffmpeg','bin/ffprobe','sources/whisper.cpp/LICENSE','sources/ffmpeg/COPYING.LGPLv2.1'):
                path=output/name
                with path.open('rb') as handle:files[name]={'bytes':path.stat().st_size,'sha256':hashlib.file_digest(handle,'sha256').hexdigest()}
            (output/'receipt.json').write_text(json.dumps({'version':item['version'],'files':files},indent=2))
        check_cancel(cancel)
        if component!='asr' and not component_status(component,stage)['ready']:raise ValueError('새 엔진 파일 검증 실패 · 기존 설치 유지')
        publish_directory(output,destination/item['install_dir'])
    result=component_status(component,destination)
    if not result['ready']:raise ValueError('런타임 준비 후 검증 실패')
    return result
