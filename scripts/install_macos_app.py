"""Build a local Mac app using the existing checkout, Python and models."""
import argparse
import ctypes
from datetime import datetime
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
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
    for key in ("python", "source", "data", "runtime"):
        if not isinstance(settings.get(key), str) or not Path(settings[key]).is_absolute():
            raise ValueError(f"기존 앱의 실행 설정을 확인할 수 없습니다: {key}")
    if type(settings.get("port")) is not int or not 1 <= settings["port"] <= 65535:
        raise ValueError("기존 앱의 포트 설정을 확인할 수 없습니다")
    return settings


def main():
    parser = argparse.ArgumentParser(description="Solasi Mac 실행 앱 설치")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--runtime-dir", type=Path)
    parser.add_argument("--destination", type=Path, default=Path.home() / "Applications/Solasi.app")
    parser.add_argument("--port", type=int)
    parser.add_argument("--replace", action="store_true", help="기존 Solasi 앱과 실행 설정을 백업하고 교체")
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    if platform.system() != "Darwin" or sys.version_info < (3, 12):
        parser.error("macOS에서 앱 의존성을 설치한 Python 3.12 이상으로 실행하세요")
    if args.port is not None and not 1 <= args.port <= 65535:
        parser.error("앱 초안 저장소를 유지하려면 포트 1–65535를 지정하세요")
    target = args.destination.expanduser().absolute()
    if target.suffix != ".app" or target.is_symlink():
        parser.error("설치 위치는 심볼릭 링크가 아닌 .app 경로여야 합니다")
    existing_identity = None
    existing_settings = None
    if target.exists():
        if not args.replace:
            parser.error("앱이 이미 있습니다. 기존 Solasi를 교체하려면 --replace를 사용하세요")
        try:
            existing_settings = read_existing_settings(target)
            settings = {**existing_settings, "source": str(source)}
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
        if args.port is not None and args.port != settings["port"]:
            parser.error("--replace는 기존 포트를 보존합니다. --port를 생략하거나 같은 값을 지정하세요")
    else:
        if args.replace:
            parser.error("--replace 대상 앱이 없습니다")
        if args.data_dir is None or args.runtime_dir is None:
            parser.error("처음 설치할 때는 --data-dir와 --runtime-dir가 필요합니다")
        settings = {"python": sys.executable, "source": str(source), "data": str(args.data_dir.expanduser().resolve()), "runtime": str(args.runtime_dir.expanduser().resolve()), "port": args.port if args.port is not None else 62434}
    for path in (Path(settings["python"]), Path(settings["source"]) / "frontend/dist/index.html", source / "macos/Solasi.icns", Path(settings["data"]), Path(settings["runtime"])):
        if not path.exists():
            parser.error(f"필요한 파일이나 폴더가 없습니다: {path}")
    subprocess.run([settings["python"], "-c", "import fastapi, uvicorn, lecture_study"], cwd=settings["source"], env={**os.environ, "PYTHONPATH": settings["source"], "PYTHONDONTWRITEBYTECODE": "1"}, check=True)
    architecture = platform.machine()
    if architecture not in ("arm64", "x86_64"):
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
        with (contents / "Info.plist").open("wb") as handle:
            plistlib.dump({"CFBundleExecutable": "Solasi", "CFBundleIdentifier": BUNDLE_ID, "CFBundleName": "Solasi", "CFBundleDisplayName": "Solasi", "CFBundlePackageType": "APPL", "CFBundleIconFile": "Solasi.icns", "CFBundleShortVersionString": "0.2.1", "CFBundleVersion": "9", "LSMinimumSystemVersion": "13.0", "NSHighResolutionCapable": True, "NSMicrophoneUsageDescription": "수업과 회의를 녹음하여 이 Mac에 원음과 전사를 저장합니다.", "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True}}, handle)
        subprocess.run(["/usr/bin/xcrun", "swiftc", "-O", "-target", f"{architecture}-apple-macosx13.0", "-module-cache-path", str(Path(folder) / "module-cache"), str(source / "macos/Solasi.swift"), "-o", str(binary)], check=True)
        subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(bundle)], check=True)
        subprocess.run(["/usr/bin/codesign", "--verify", "--strict", "--verbose=2", str(bundle)], check=True)
        if existing_identity is not None:
            stat = target.stat()
            if target.is_symlink() or (stat.st_dev, stat.st_ino) != existing_identity or read_existing_settings(target) != existing_settings:
                parser.error("빌드 중 기존 앱이 변경되었습니다. 교체하지 않습니다")
            running = subprocess.run(["/usr/sbin/lsof", "-t", "-a", "-d", "txt", "--", str(target / "Contents/MacOS/Solasi")], capture_output=True, text=True)
            if running.returncode not in (0, 1) or running.stdout.strip():
                parser.error("기존 앱이 실행되었거나 실행 여부를 확인할 수 없습니다. 앱을 종료한 뒤 다시 교체하세요")
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
    print("더블클릭하면 Solasi 앱 창으로 열립니다. 창을 닫아도 서버는 유지되며, 종료는 Dock의 Solasi → 종료 또는 ⌘Q입니다.")


if __name__ == "__main__":
    main()
