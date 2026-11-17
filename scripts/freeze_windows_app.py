"""Freeze GUI and console worker into one private dependency tree on Windows x64."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path,PurePosixPath
import platform
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]


def copy_engine(source,destination):
    record=json.loads((source/'receipt.json').read_bytes());files=record['files']
    if not isinstance(files,dict) or not 1<=len(files)<=2048:raise ValueError('엔진 파일 목록 오류')
    for name,item in files.items():
        if (not name or '\\' in name or ':' in name or PurePosixPath(name).is_absolute() or
                '..' in PurePosixPath(name).parts or str(PurePosixPath(name))!=name):raise ValueError('엔진 파일 경로 오류')
        path=source/name
        if not path.resolve().is_relative_to(source.resolve()) or path.is_symlink() or not path.is_file():raise ValueError('엔진 파일 경로 오류')
        with path.open('rb') as stream:checksum=hashlib.file_digest(stream,'sha256').hexdigest()
        if path.stat().st_size!=item['bytes'] or checksum!=item['sha256']:raise ValueError('엔진 해시 검증 실패')
    for path in source.rglob('*'):
        if path.suffix.lower() in ('.exe','.dll') and path.relative_to(source).as_posix() not in files:raise ValueError('검증하지 않은 실행 파일이 있습니다')
    if destination.exists():raise FileExistsError('엔진 출력 폴더가 이미 있습니다')
    destination.mkdir(parents=True)
    for name in files:
        target=destination/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source/name,target)
    if (source/'lib').is_dir():(destination/'lib').mkdir(exist_ok=True)
    shutil.copy2(source/'receipt.json',destination/'receipt.json')


def freeze(runtime,models,destination):
    if os.name!='nt' or platform.machine().lower() not in ('amd64','x86_64'):raise ValueError('Windows x64에서 빌드하세요')
    if sys.version_info[:2]!=(3,12):raise ValueError('고정 Windows 빌드는 Python 3.12를 사용합니다')
    if importlib.metadata.version('pyinstaller')!='6.22.3':raise ValueError('PyInstaller 6.22.3이 필요합니다')
    if destination.exists() or destination.is_symlink():raise FileExistsError('새 앱 출력 폴더를 지정하세요')
    destination=destination.resolve()
    if not (ROOT/'frontend/dist/index.html').is_file():raise ValueError('기존 화면을 먼저 빌드하세요')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.freeze-windows-',dir=destination.parent) as temporary:
        stage=Path(temporary)
        spec=stage/'Solasi.spec'
        spec.write_text('''from PyInstaller.utils.hooks import collect_all,copy_metadata
datas=[('''+repr(str(ROOT/'lecture_study/schema.sql'))+''','lecture_study'),('''+repr(str(ROOT/'runtime-manifest.json'))+''','.'),('''+repr(str(ROOT/'frontend/dist'))+''','frontend/dist')]
binaries=[];hiddenimports=['keyring.backends.Windows','lecture_study.windows_app','lecture_study.engine_main']
for package in ('webview','pythonnet','clr_loader','sounddevice','_sounddevice_data','liteparse','pypdfium2','pypdfium2_raw','PIL','tokenizers'):
    data,binary,hidden=collect_all(package);datas+=data;binaries+=binary;hiddenimports+=hidden
for package in ('pywebview','pythonnet','sounddevice','pypdfium2','pillow','liteparse'):
    datas+=copy_metadata(package)
a=Analysis(['''+repr(str(ROOT/'lecture_study/windows_entry.py'))+'''],pathex=['''+repr(str(ROOT))+'''],binaries=binaries,datas=datas,hiddenimports=hiddenimports,excludes=['torch','tensorflow','mlx','mlx_vlm','mlx_audio','PyQt5','PyQt6','PySide2','PySide6','pytest'])
pyz=PYZ(a.pure)
gui=EXE(pyz,a.scripts,[],exclude_binaries=True,name='Solasi',console=False,icon='''+repr(str(ROOT/'frontend/dist/solasi-icon.png'))+''')
worker=EXE(pyz,a.scripts,[],exclude_binaries=True,name='solasi-worker',console=True)
app=COLLECT(gui,worker,a.binaries,a.datas,name='Solasi')
''',encoding='utf-8')
        subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--distpath',str(stage/'dist'),'--workpath',str(stage/'work'),str(spec)],cwd=ROOT,check=True)
        output=stage/'dist/Solasi'
        copy_engine(models,output/'engines')
        for component in ('asr','ocr'):copy_engine(runtime/component,output/'engines'/component)
        installer=runtime/'webview/MicrosoftEdgeWebView2RuntimeInstallerX64.exe'
        if not installer.is_file():raise ValueError('Microsoft 서명을 검증한 WebView2 설치 파일이 필요합니다')
        (output/'setup').mkdir();shutil.copy2(installer,output/'setup'/installer.name)
        subprocess.run([str(output/'solasi-worker.exe'),'--self-check'],check=True,capture_output=True)
        files={}
        for path in sorted(output.rglob('*')):
            if path.is_file():
                with path.open('rb') as stream:checksum=hashlib.file_digest(stream,'sha256').hexdigest()
                files[path.relative_to(output).as_posix()]={'bytes':path.stat().st_size,'sha256':checksum}
        (output/'bundle-manifest.json').write_text(json.dumps({'format':1,'platform':'win32-x64','files':files},indent=2)+'\n',encoding='utf-8')
        shutil.copy2(ROOT/'windows/Install-Solasi.ps1',output/'Install-Solasi.ps1')
        output.rename(destination)
    return destination


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-dir',type=Path,required=True)
    parser.add_argument('--model-engines',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args()
    try:print(freeze(args.runtime_dir.resolve(),args.model_engines.resolve(),args.destination.absolute()))
    except (OSError,ValueError,KeyError,subprocess.SubprocessError) as error:parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()
