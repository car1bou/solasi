"""Build a self-contained arm64 engine; models and user data are not copied."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def deployment_target(root):
    versions=['13.3']
    for path in root.rglob('*'):
        if not path.is_file() or path.is_symlink():continue
        with path.open('rb') as handle:magic=handle.read(4)
        if magic not in (b'\xcf\xfa\xed\xfe',b'\xfe\xed\xfa\xcf',b'\xca\xfe\xba\xbe',b'\xbe\xba\xfe\xca'):continue
        output=subprocess.run(['/usr/bin/otool','-l',str(path)],capture_output=True,text=True,check=True).stdout
        found=re.findall(r'\bminos (\d+\.\d+(?:\.\d+)?)',output)+re.findall(r'LC_VERSION_MIN_MACOSX\s+cmdsize \d+\s+version (\d+\.\d+(?:\.\d+)?)',output)
        if not found:raise ValueError('macOS 배포 대상이 없는 실행 파일: '+str(path))
        versions+=found
    return max(versions,key=lambda value:tuple(map(int,value.split('.'))))


def copy_verified_files(source, destination, receipt):
    for name, item in receipt['files'].items():
        if not isinstance(name,str) or not name or Path(name).is_absolute() or '..' in Path(name).parts or str(Path(name))!=name:
            raise ValueError('엔진 파일 이름 오류')
        path=source/name
        if not path.resolve().is_relative_to(source.resolve()) or not path.is_file():raise ValueError('엔진 파일 경로 오류')
        with path.open('rb') as handle: digest=hashlib.file_digest(handle,'sha256').hexdigest()
        if path.stat().st_size!=item['bytes'] or digest!=item['sha256']:raise ValueError('엔진 파일 해시 불일치: '+name)
        target=destination/name
        if not target.resolve().is_relative_to(destination.resolve()):raise ValueError('엔진 출력 경로 오류')
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-dir',type=Path,required=True)
    parser.add_argument('--embedding-engine',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args()
    target=args.destination.absolute();runtime=args.runtime_dir.resolve();embedding=args.embedding_engine.resolve()
    if platform.system()!='Darwin' or platform.machine()!='arm64':parser.error('Apple Silicon Mac에서 빌드하세요')
    if target.exists() or target.is_symlink():parser.error('새 빌드 폴더를 지정하세요. 기존 앱은 덮어쓰지 않습니다')
    if importlib.metadata.version('pyinstaller')!='6.22.3':parser.error('PyInstaller 6.22.3이 필요합니다')
    target.parent.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ,PYINSTALLER_CONFIG_DIR=str(target.parent/'pyinstaller-cache'),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONDONTWRITEBYTECODE='1')
    with tempfile.TemporaryDirectory(prefix='freeze-',dir=target.parent) as folder:
        stage=Path(folder)
        command=[sys.executable,'-m','PyInstaller','--noconfirm','--onedir','--name','solasi-engine',
                 '--distpath',str(stage/'dist'),'--workpath',str(stage/'work'),'--specpath',str(stage),
                 '--paths',str(ROOT),'--add-data',str(ROOT/'lecture_study/schema.sql')+':lecture_study',
                 '--add-data',str(ROOT/'runtime-manifest.json')+':.',
                 '--exclude-module','torch','--exclude-module','tensorflow','--exclude-module','torchaudio',
                 '--exclude-module','torchvision','--exclude-module','pytest']
        for package in ('mlx','mlx_vlm','mlx_lm','mlx_audio','transformers','tokenizers','llguidance','liteparse','keyring'):
            command+=['--collect-all',package]
        for package in ('mlx-vlm','mlx-metal','mlx-audio','llguidance','liteparse','keyring'):
            command+=['--recursive-copy-metadata',package]
        command.append(str(ROOT/'lecture_study/engine_main.py'))
        subprocess.run(command,cwd=ROOT,env=env,check=True)
        output=stage/'dist/solasi-engine';engines=output/'engines';engines.mkdir()
        asr_receipt=json.loads((runtime/'asr/receipt.json').read_text())
        copy_verified_files(runtime/'asr',engines/'asr',asr_receipt)
        (engines/'asr/receipt.json').write_text(json.dumps(asr_receipt,indent=2))
        embedding_receipt=json.loads((embedding/'receipt.json').read_text())
        copy_verified_files(embedding,engines,embedding_receipt)
        for source in (embedding/'lib').iterdir():
            if source.is_symlink():
                if not source.resolve().is_relative_to(embedding/'lib'):raise ValueError('임베딩 라이브러리 연결 오류')
                (engines/'lib'/source.name).symlink_to(os.readlink(source))
        for name in ('receipt.json','LICENSE.llama.cpp','LICENSE.ollama'):shutil.copy2(embedding/name,engines/name)
        subprocess.run(['/usr/bin/xcrun','swiftc','-O','-target','arm64-apple-macosx13.3','-module-cache-path',str(stage/'swift-cache'),str(ROOT/'macos/MaterialMetadata.swift'),'-o',str(output/'MaterialMetadata')],check=True)
        subprocess.run(['/usr/bin/xcrun','swiftc','-O','-target','arm64-apple-macosx13.3','-module-cache-path',str(stage/'swift-cache'),str(ROOT/'macos/HandwritingRecognition.swift'),'-o',str(output/'HandwritingRecognition')],check=True)
        versions={distribution.metadata['Name']:distribution.version for distribution in importlib.metadata.distributions()}
        files={}
        for path in sorted(output.rglob('*')):
            if path.is_file() and not path.is_symlink():
                with path.open('rb') as handle:digest=hashlib.file_digest(handle,'sha256').hexdigest()
                files[str(path.relative_to(output))]={'bytes':path.stat().st_size,'sha256':digest}
        (output/'bundle-manifest.json').write_text(json.dumps({'format':1,'architecture':'arm64','minimum_macos':deployment_target(output),'versions':versions,'files':files},indent=2))
        output.rename(target)
    print(target)


if __name__=='__main__':main()
