"""Build the pinned Windows CPU ASR/OCR engines. Run only on the build PC."""
import argparse
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lecture_study.runtime import manifest,download_verified

VCPKG_REVISION='0e5030f583a5427123cd3b714255e5ae62faa3ba'
FFMPEG={'url':'https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-09-30-13-08/ffmpeg-n9.0.2-17-g2a571b6068-win64-lgpl-shared-9.0.zip',
        'bytes':76972461,'sha256':'7157177b8a6cb2174c1650ba8c71b363f2c78cba5330f88c4c02cf5b2b880646'}
WEBVIEW_INSTALLER='https://go.microsoft.com/fwlink/p/?LinkId=2124703'


def webview_installer(target):
    target.parent.mkdir(parents=True,exist_ok=True)
    with urlopen(WEBVIEW_INSTALLER,timeout=60) as response,target.open('xb') as output:
        size=0
        while block:=response.read(1024*1024):
            size+=len(block)
            if size>512*1024**2:raise ValueError('WebView2 installer size limit')
            output.write(block)
    # Verify the vendor's Authenticode signature before adding the current Evergreen installer.
    script="$s=Get-AuthenticodeSignature -LiteralPath $env:SOLASI_WEBVIEW_INSTALLER; if($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation(,|$)'){throw 'Invalid Microsoft WebView2 signature'}"
    subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],check=True,
                   env=os.environ|{'SOLASI_WEBVIEW_INSTALLER':str(target)})


def extract_zip(archive,destination):
    with zipfile.ZipFile(archive) as package:
        names=set();total=0
        for item in package.infolist():
            name=item.orig_filename.rstrip('/');path=PurePosixPath(name)
            if (not name or '\\' in name or ':' in name or path.is_absolute() or '..' in path.parts or
                    str(path)!=name or name in names or stat.S_ISLNK(item.external_attr>>16)):
                raise ValueError('배포 ZIP 경로를 확인하세요')
            names.add(name);total+=item.file_size
            if total>1024**3 or item.file_size>256*1024**2:raise ValueError('배포 ZIP 크기를 확인하세요')
        package.extractall(destination)


def write_receipt(root,version,**provenance):
    files={}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():raise ValueError('배포 엔진에 심볼릭 링크를 넣을 수 없습니다')
        if path.is_file() and path.name!='receipt.json':
            with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
            files[path.relative_to(root).as_posix()]={'bytes':path.stat().st_size,'sha256':digest}
    record={'platform':'win32-x64','version':version,'files':files,**provenance}
    (root/'receipt.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    return record


def run(command,**options):subprocess.run(list(map(str,command)),check=True,**options)


def build(destination,cache,vcpkg,cmake):
    if os.name!='nt':raise ValueError('Windows x64 빌드 PC에서 실행하세요')
    if destination.exists() or destination.is_symlink():raise FileExistsError('새 엔진 출력 폴더를 지정하세요')
    cache.mkdir(parents=True,exist_ok=True);destination.parent.mkdir(parents=True,exist_ok=True)
    spec=manifest()
    whisper=cache/'whisper-source.tar.gz';download_verified(spec['assets']['whisper_source'],whisper)
    ffmpeg=cache/'ffmpeg-windows-lgpl.zip';download_verified(FFMPEG,ffmpeg)
    if not vcpkg.exists():
        vcpkg.mkdir(parents=True)
        run(['git','init',vcpkg]);run(['git','-C',vcpkg,'remote','add','origin','https://github.com/microsoft/vcpkg.git'])
        run(['git','-C',vcpkg,'fetch','--depth','1','origin',VCPKG_REVISION])
        run(['git','-C',vcpkg,'checkout','--detach',VCPKG_REVISION])
    revision=subprocess.run(['git','-C',str(vcpkg),'rev-parse','HEAD'],check=True,capture_output=True,text=True).stdout.strip()
    if revision!=VCPKG_REVISION:raise ValueError('고정된 vcpkg 버전이 아닙니다')
    if not (vcpkg/'vcpkg.exe').is_file():run([vcpkg/'bootstrap-vcpkg.bat','-disableMetrics'],cwd=vcpkg)
    run([vcpkg/'vcpkg.exe','install','tesseract:x64-windows-static','--disable-metrics'],cwd=vcpkg)
    with tempfile.TemporaryDirectory(prefix='.windows-runtime-',dir=destination.parent) as temporary:
        stage=Path(temporary);output=stage/'runtime';output.mkdir()
        with tarfile.open(whisper) as package:package.extractall(stage/'whisper',filter='data')
        sources=list((stage/'whisper').iterdir())
        if len(sources)!=1 or not sources[0].is_dir():raise ValueError('Whisper source root 오류')
        source=sources[0]
        asr=output/'asr';(asr/'bin').mkdir(parents=True)
        from scripts.build_windows_asr import build_whisper
        cpu=build_whisper(source,stage/'whisper-build',asr,cmake)
        extract_zip(ffmpeg,stage/'ffmpeg')
        ff_roots=list((stage/'ffmpeg').iterdir())
        if len(ff_roots)!=1:raise ValueError('FFmpeg root 오류')
        ff=ff_roots[0]
        for path in (ff/'bin').iterdir():
            if path.suffix.lower() in ('.exe','.dll'):shutil.copy2(path,asr/'bin'/path.name)
        for name in ('ffmpeg','ffprobe'):run([asr/'bin'/(name+'.exe'),'-version'],stdout=subprocess.DEVNULL)
        notices=asr/'notices';notices.mkdir()
        shutil.copy2(source/'LICENSE',notices/'LICENSE.whisper.cpp')
        for path in ff.iterdir():
            if path.is_file() and path.name.lower().startswith(('license','copying','readme')):shutil.copy2(path,notices/path.name)
        if (ff/'doc').is_dir():shutil.copytree(ff/'doc',notices/'ffmpeg')
        write_receipt(asr,spec['components']['asr']['version'],whisper_source_sha256=spec['assets']['whisper_source']['sha256'],ffmpeg=FFMPEG,**cpu)
        installed=vcpkg/'installed/x64-windows-static';tool=installed/'tools/tesseract/tesseract.exe'
        if not tool.is_file():raise ValueError('고정 vcpkg Tesseract 실행 파일이 없습니다')
        ocr=output/'ocr';(ocr/'bin').mkdir(parents=True)
        for path in tool.parent.iterdir():
            if path.is_file() and path.suffix.lower() in ('.exe','.dll'):shutil.copy2(path,ocr/'bin'/path.name)
        for path in (installed/'share').glob('*/copyright'):
            target=ocr/'notices'/path.parent.name;target.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target/'copyright')
        run([ocr/'bin/tesseract.exe','--version'],stdout=subprocess.DEVNULL)
        write_receipt(ocr,spec['components']['ocr']['version'],vcpkg_revision=revision)
        webview_installer(output/'webview/MicrosoftEdgeWebView2RuntimeInstallerX64.exe')
        output.rename(destination)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination',type=Path,required=True)
    parser.add_argument('--cache',type=Path,required=True)
    parser.add_argument('--vcpkg',type=Path,required=True)
    parser.add_argument('--cmake',default='cmake')
    args=parser.parse_args()
    try:build(args.destination.absolute(),args.cache.absolute(),args.vcpkg.absolute(),args.cmake)
    except (OSError,ValueError,subprocess.SubprocessError,tarfile.TarError,zipfile.BadZipFile) as error:parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()
