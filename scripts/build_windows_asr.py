"""Rebuild only the pinned static CPU ASR engines, retaining verified FFmpeg files."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lecture_study.runtime import manifest,download_verified
from lecture_study.windows_runtime import CPU_DISPATCH,CPU_FILES,verified_engine


def build_whisper(source,stage,asr,cmake):
    project=stage/'project';project.mkdir(parents=True)
    (project/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.21)\nproject(SolasiAsr LANGUAGES C CXX)\n'
        'set(CMAKE_MSVC_RUNTIME_LIBRARY MultiThreaded)\n'
        'add_subdirectory("'+source.as_posix()+'" whisper)\n'
        'add_executable(WindowsCpu "'+(ROOT/'windows/WindowsCpu.cpp').as_posix()+'")\n',encoding='utf-8')
    (asr/'bin').mkdir(parents=True,exist_ok=True);configurations={}
    for flavor in ('baseline','avx2'):
        enabled='ON'if flavor=='avx2'else'OFF';build=stage/flavor
        flags=['-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded','-DCMAKE_POLICY_DEFAULT_CMP0091=NEW',
               '-DBUILD_SHARED_LIBS=OFF','-DGGML_BACKEND_DL=OFF','-DGGML_NATIVE=OFF',
               *['-DGGML_'+name+'='+enabled for name in ('SSE42','AVX','AVX2','FMA','F16C','BMI2')],
               *['-DGGML_'+name+'=OFF'for name in ('AVX512','AVX_VNNI','AVX512_VBMI','AVX512_VNNI','AVX512_BF16','OPENMP','METAL','BLAS','CUDA','VULKAN')],
               '-DWHISPER_BUILD_EXAMPLES=ON','-DWHISPER_BUILD_SERVER=OFF','-DWHISPER_BUILD_TESTS=OFF','-DWHISPER_BUILD_IS_DEV=OFF']
        configurations[flavor]=flags
        subprocess.run([str(cmake),'-S',str(project),'-B',str(build),'-A','x64',*flags],check=True)
        targets=['whisper-cli','whisper-vad-speech-segments']+(['WindowsCpu']if flavor=='baseline'else[])
        subprocess.run([str(cmake),'--build',str(build),'--config','Release','--target',*targets,'--parallel','4'],check=True)
        for name in targets:
            candidates=list(build.glob('**/'+name+'.exe'))
            if len(candidates)!=1:raise ValueError('전사 엔진 출력이 모호합니다: '+name)
            suffix='-avx2'if flavor=='avx2'else''
            shutil.copy2(candidates[0],asr/'bin'/(name+suffix+'.exe'))
    checked=subprocess.run([str(asr/'bin/WindowsCpu.exe'),'--self-check'],capture_output=True,check=True,timeout=10)
    if json.loads(checked.stdout)!={'self_check':True}:raise ValueError('CPU 기능 검사 자체 검증 실패')
    return {'cpu_dispatch':CPU_DISPATCH,'cpu_build_flags':configurations,
            'cpu_probe_source_sha256':hashlib.sha256((ROOT/'windows/WindowsCpu.cpp').read_bytes()).hexdigest()}


def build(base_asr,destination,cache,cmake='cmake'):
    if os.name!='nt'or platform.machine().lower()not in ('amd64','x86_64'):raise ValueError('Windows x64 빌드 PC에서 실행하세요')
    if destination.exists()or destination.is_symlink():raise FileExistsError('새 ASR 엔진 출력 폴더를 지정하세요')
    destination=destination.resolve();base_asr=base_asr.resolve();cache=cache.resolve();spec=manifest()
    if base_asr.name!='asr':raise ValueError('기존 runtime/asr 디렉터리를 지정하세요')
    required=['bin/'+name+'.exe'for name in ('whisper-cli','whisper-vad-speech-segments','ffmpeg','ffprobe')]
    _,original=verified_engine(base_asr.parent,'asr',required)
    if original.get('version')!=spec['components']['asr']['version']:raise ValueError('기존 ASR 엔진 버전이 다릅니다')
    cache.mkdir(parents=True,exist_ok=True);destination.parent.mkdir(parents=True,exist_ok=True)
    archive=cache/'whisper-source.tar.gz';download_verified(spec['assets']['whisper_source'],archive)
    from scripts.freeze_windows_app import copy_engine
    from scripts.build_windows_runtime import write_receipt
    with tempfile.TemporaryDirectory(prefix='.asr-build-',dir=destination.parent)as folder:
        stage=Path(folder)
        with tarfile.open(archive)as package:package.extractall(stage/'source',filter='data')
        sources=list((stage/'source').iterdir())
        if len(sources)!=1 or not sources[0].is_dir():raise ValueError('Whisper source root 오류')
        output=stage/'asr';copy_engine(base_asr,output)
        provenance={key:value for key,value in original.items()if key not in ('platform','version','files')}
        provenance.update(build_whisper(sources[0],stage/'build',output,cmake))
        provenance['whisper_source_sha256']=spec['assets']['whisper_source']['sha256']
        record=write_receipt(output,spec['components']['asr']['version'],**provenance)
        verified_engine(stage,'asr',required+list(CPU_FILES))
        output.rename(destination)
    return record


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-asr',type=Path,required=True,help='Existing receipt-verified runtime/asr directory')
    parser.add_argument('--destination',type=Path,required=True,help='New ASR directory; never overwrites the baseline')
    parser.add_argument('--cache',type=Path,required=True)
    parser.add_argument('--cmake',default='cmake');args=parser.parse_args()
    try:build(args.base_asr,args.destination.absolute(),args.cache.absolute(),args.cmake)
    except (OSError,ValueError,subprocess.SubprocessError,tarfile.TarError)as error:parser.exit(1,str(error)+'\n')
    print(args.destination.absolute())


if __name__=='__main__':main()
