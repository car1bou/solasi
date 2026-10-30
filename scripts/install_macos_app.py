"""Install a bundled Mac app, preserving its vault and model locations."""
import argparse
import ctypes
from datetime import datetime
import json
import hashlib
import os
from pathlib import Path
import platform
import plistlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid


BUNDLE_ID = "local.solasi.launcher"


def rename_exclusive(source: Path, destination: Path):
    """Rename on the same volume without replacing a path created concurrently."""
    rename = ctypes.CDLL(None, use_errno=True).renamex_np
    rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(os.fsencode(source), os.fsencode(destination), 0x00000004) != 0:  # RENAME_EXCL
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(destination))


def read_existing_settings(target: Path):
    if target.is_symlink() or not target.is_dir():
        raise ValueError("교체 대상은 심볼릭 링크가 아닌 기존 Solasi.app이어야 합니다")
    contents = target / "Contents"
    with (contents / "Info.plist").open("rb") as handle:
        info = plistlib.load(handle)
    if not isinstance(info, dict) or info.get("CFBundleIdentifier") != BUNDLE_ID or info.get("CFBundleExecutable") != "Solasi":
        raise ValueError("다른 앱은 덮어쓰지 않습니다. Solasi 설치 위치를 확인하세요")
    settings = json.loads((contents / "Resources/launch.json").read_text(encoding="utf-8"))
    if not isinstance(settings, dict):
        raise ValueError("기존 앱의 실행 설정을 확인할 수 없습니다")
    for key in ("data", "runtime"):
        if not isinstance(settings.get(key), str) or not Path(settings[key]).is_absolute():
            raise ValueError(f"기존 앱의 실행 설정을 확인할 수 없습니다: {key}")
    if 'port' in settings and (type(settings["port"]) is not int or not 1 <= settings["port"] <= 65535):
        raise ValueError("기존 앱의 포트 설정을 확인할 수 없습니다")
    return settings


def verify_engine(root):
    manifest=json.loads((root/'bundle-manifest.json').read_text())
    if manifest.get('format')!=1 or not isinstance(manifest.get('files'),dict) or 'solasi-engine' not in manifest['files']:
        raise ValueError('내장 엔진 빌드 기록이 없습니다')
    for name,item in manifest['files'].items():
        path=root/name
        if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():raise ValueError('내장 엔진 파일 경로 오류')
        with path.open('rb') as handle: digest=hashlib.file_digest(handle,'sha256').hexdigest()
        if path.stat().st_size!=item['bytes'] or digest!=item['sha256']:raise ValueError('내장 엔진 파일 해시 오류: '+name)
    for path in root.rglob('*'):
        if path.is_symlink() and not path.resolve().is_relative_to(root.resolve()):raise ValueError('내장 엔진의 외부 파일 연결 오류')
    return manifest


def validate_draft_migration(data, backup, origin=None):
    if backup is None or not backup.is_dir() or origin is None:
        raise ValueError('기존 화면의 모든 초안·편집 입력을 백업하고 가져온 뒤 --draft-backup을 지정하세요')
    try:
        from lecture_study.legacy_drafts import verify_import
        with sqlite3.connect((data/'app.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
            digest=verify_import(db,backup,origin)
    except (sqlite3.Error,KeyError,TypeError):raise ValueError('검증된 초안 이전 결과가 없습니다') from None
    return digest


def main():
    parser = argparse.ArgumentParser(description="Solasi Mac 실행 앱 설치")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--runtime-dir", type=Path)
    parser.add_argument("--destination", type=Path, default=Path.home() / "Applications/Solasi.app")
    parser.add_argument("--engine", type=Path, required=True, help="freeze_macos_engine.py의 검증된 결과 폴더")
    parser.add_argument("--draft-backup", type=Path, help="이전 보관함에 가져오기를 마친 전체 초안 백업")
    parser.add_argument("--validation", action="store_true", help="별도 앱 식별자로 검증용 앱 생성")
    parser.add_argument("--replace", action="store_true", help="기존 Solasi 앱과 실행 설정을 백업하고 교체")
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    if platform.system() != "Darwin" or sys.version_info < (3, 12):
        parser.error("macOS에서 앱 의존성을 설치한 Python 3.12 이상으로 실행하세요")
    target = args.destination.expanduser().absolute()
    if target.suffix != ".app" or target.is_symlink():
        parser.error("설치 위치는 심볼릭 링크가 아닌 .app 경로여야 합니다")
    existing_identity = None
    existing_settings = None
    if target.exists():
        if args.validation:parser.error('검증 앱은 새 경로에 생성하세요')
        if not args.replace:
            parser.error("앱이 이미 있습니다. 기존 Solasi를 교체하려면 --replace를 사용하세요")
        try:
            existing_settings = read_existing_settings(target)
            settings = {key:existing_settings[key] for key in ('data','runtime')}
            if 'port' in existing_settings:validate_draft_migration(Path(settings['data']),args.draft_backup,f"http://127.0.0.1:{existing_settings['port']}")
            stat = target.stat()
            existing_identity = (stat.st_dev, stat.st_ino)
        except (OSError, ValueError, TypeError, plistlib.InvalidFileException) as exc:
            parser.error(str(exc))
        # Permission services can hold a read handle after the app quits; only executable mappings count.
        running = subprocess.run(["/usr/sbin/lsof", "-t", "-a", "-d", "txt", "--", str(target / "Contents/MacOS/Solasi")], capture_output=True, text=True)
        if running.returncode not in (0, 1):
            parser.error("기존 앱의 실행 여부를 확인할 수 없습니다. 앱을 종료하고 다시 실행하세요")
        if running.stdout.strip():
            parser.error("기존 Solasi가 실행 중입니다. 녹음·작업을 마치고 ⌘Q로 종료한 뒤 교체하세요")
        for flag, value, key in (("--data-dir", args.data_dir, "data"), ("--runtime-dir", args.runtime_dir, "runtime")):
            if value is not None and value.expanduser().resolve() != Path(settings[key]).resolve():
                parser.error(f"--replace는 기존 {key} 경로를 보존합니다. {flag}를 생략하거나 같은 경로를 지정하세요")
    else:
        if args.replace:
            parser.error("--replace 대상 앱이 없습니다")
        if args.data_dir is None or args.runtime_dir is None:
            parser.error("처음 설치할 때는 --data-dir와 --runtime-dir가 필요합니다")
        settings = {"data": str(args.data_dir.expanduser().resolve()), "runtime": str(args.runtime_dir.expanduser().resolve())}
    engine=args.engine.expanduser().resolve()
    for path in (engine/'solasi-engine',source / "frontend/dist/index.html", source / "macos/Solasi.icns", Path(settings["data"]), Path(settings["runtime"])):
        if not path.exists():
            parser.error(f"필요한 파일이나 폴더가 없습니다: {path}")
    engine_manifest=verify_engine(engine)
    minimum_macos=engine_manifest['minimum_macos']
    import re
    if not isinstance(minimum_macos,str) or not re.fullmatch(r'\d+\.\d+(\.\d+)?',minimum_macos):parser.error('내장 엔진의 macOS 최소 버전 오류')
    if tuple(map(int,platform.mac_ver()[0].split('.')))<tuple(map(int,minimum_macos.split('.'))):parser.error('이 엔진에는 macOS '+minimum_macos+' 이상이 필요합니다')
    subprocess.run([str(engine/'solasi-engine'),'--self-check'],cwd=engine,env={key:value for key,value in os.environ.items() if key not in ('PYTHONPATH','PYTHONHOME')},check=True)
    architecture = platform.machine()
    if architecture != "arm64":
        parser.error(f"지원하지 않는 Mac 아키텍처입니다: {architecture}")
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    with tempfile.TemporaryDirectory(prefix=".solasi-build-", dir=target.parent) as folder:
        bundle = Path(folder) / "Solasi.app"
        contents = bundle / "Contents"
        resources = contents / "Resources"
        binary = contents / "MacOS/Solasi"
        resources.mkdir(parents=True)
        binary.parent.mkdir()
        (resources / "launch.json").write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")
        shutil.copyfile(source / "macos/Solasi.icns", resources / "Solasi.icns")
        shutil.copytree(engine,resources/'engine',symlinks=True)
        shutil.copytree(source/'frontend/dist',resources/'frontend')
        with (contents / "Info.plist").open("wb") as handle:
            name='Solasi Internal Validation' if args.validation else 'Solasi'
            plistlib.dump({"CFBundleExecutable": "Solasi", "CFBundleIdentifier": 'local.solasi.internal-validation' if args.validation else BUNDLE_ID, "CFBundleName": name, "CFBundleDisplayName": name, "CFBundlePackageType": "APPL", "CFBundleIconFile": "Solasi.icns", "CFBundleShortVersionString": "0.3.35", "CFBundleVersion": "45", "LSMinimumSystemVersion": minimum_macos, "NSHighResolutionCapable": True, "NSMicrophoneUsageDescription": "수업과 회의를 녹음하여 이 Mac에 원음과 전사를 저장합니다.","CFBundleURLTypes":[{"CFBundleURLName":"Solasi 원음","CFBundleURLSchemes":["solasi"]}]}, handle)
        swift=['WorkerBridge.swift','AppResources.swift','AudioCapture.swift','AudioPlayback.swift','Solasi.swift']
        subprocess.run(["/usr/bin/xcrun", "swiftc", "-O", "-target", f"{architecture}-apple-macosx{minimum_macos}", "-module-cache-path", str(Path(folder) / "module-cache"), *[str(source/'macos'/name) for name in swift], "-o", str(binary)], check=True)
        subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(bundle)], check=True)
        subprocess.run(["/usr/bin/codesign", "--verify", "--strict", "--verbose=2", str(bundle)], check=True)
        if existing_identity is not None:
            stat = target.stat()
            if target.is_symlink() or (stat.st_dev, stat.st_ino) != existing_identity or read_existing_settings(target) != existing_settings:
                parser.error("빌드 중 기존 앱이 변경되었습니다. 교체하지 않습니다")
            running = subprocess.run(["/usr/sbin/lsof", "-t", "-a", "-d", "txt", "--", str(target / "Contents/MacOS/Solasi")], capture_output=True, text=True)
            if running.returncode not in (0, 1) or running.stdout.strip():
                parser.error("기존 앱이 실행되었거나 실행 여부를 확인할 수 없습니다. 앱을 종료한 뒤 다시 교체하세요")
            if 'port' in existing_settings:validate_draft_migration(Path(settings['data']),args.draft_backup,f"http://127.0.0.1:{existing_settings['port']}")
            backup = target.with_name(f".{target.name}.backup-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}")
            rename_exclusive(target, backup)
        try:
            rename_exclusive(bundle, target)
        except BaseException:
            if backup is not None:
                try:
                    rename_exclusive(backup, target)
                except OSError:
                    print(f"기존 앱 백업은 보존했습니다: {backup}", file=sys.stderr)
            raise
    print(f"설치 완료: {target}")
    if backup is not None:
        print(f"기존 앱 백업: {backup}")
    print("더블클릭하면 앱 내부에서 실행합니다. 종료는 Dock의 Solasi → 종료 또는 ⌘Q입니다.")


if __name__ == "__main__":
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    main()
