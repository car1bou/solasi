#!/usr/bin/env python3
"""Build a separate, read-only WebKit draft exporter. Never replaces the installed app."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import plistlib
import re
import subprocess
from urllib.parse import urlsplit


def checked_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
            or parsed.username is not None or parsed.password is not None
            or parsed.port is None or not 1 <= parsed.port <= 65535 or parsed.path not in ("", "/")
            or "?" in value or "#" in value or value.strip() != value):
        raise ValueError("Use the exact previous http://127.0.0.1:<port> origin")
    return f"http://127.0.0.1:{parsed.port}"


def build_helper(directory: Path, bundle_id: str) -> Path:
    if bundle_id != "local.solasi.launcher" and not re.fullmatch(r"local\.solasi\.migration-fixture-[a-f0-9]+", bundle_id):
        raise ValueError("Only the legacy Solasi or isolated fixture bundle ID is supported")
    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    contents = directory / "SolasiLegacyDraftExport.app" / "Contents"
    executable = contents / "MacOS" / "LegacyDraftExport"
    executable.parent.mkdir(parents=True)
    (contents / "Info.plist").write_bytes(plistlib.dumps({
        "CFBundleIdentifier": bundle_id,
        "CFBundleExecutable": executable.name,
        "CFBundlePackageType": "APPL",
        "CFBundleName": "Solasi Legacy Draft Export",
        "CFBundleVersion": "1",
        "LSUIElement": True,
    }))
    source = Path(__file__).resolve().parents[1] / "macos" / "LegacyDraftExport.swift"
    snapshot = directory / "LegacyDraftExport.swift"
    snapshot.write_bytes(source.read_bytes())
    subprocess.run([
        "xcrun", "swiftc", "-parse-as-library", "-target", "arm64-apple-macosx13.0",
        "-module-cache-path", str(directory.parent / "swift-cache"), str(snapshot), "-o", str(executable),
    ], check=True)
    subprocess.run(["codesign", "--force", "--sign", "-", "--timestamp=none", str(contents.parent)], check=True)
    return executable


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--vault-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--build-dir", required=True, type=Path)
    parser.add_argument("--bundle-id", default="local.solasi.launcher")
    parser.add_argument("--quiescent", action="store_true", help="All live inputs are preserved and every old Solasi window is closed")
    parser.add_argument("--build-only", action="store_true", help="Build without opening any WebKit data store")
    args = parser.parse_args()
    try:
        origin = checked_origin(args.origin)
        if not re.fullmatch(r"[a-f0-9]{32}", args.vault_id):
            raise ValueError("vault-id must be the verified 32-character lowercase hex vault identity")
        if not args.quiescent and not args.build_only:
            raise ValueError("Preserve live inputs, quit the old app, then explicitly pass --quiescent")
        if args.output.exists():
            raise ValueError("Export output already exists; choose a new directory")
        executable = build_helper(args.build_dir.resolve(), args.bundle_id)
    except ValueError as error:
        parser.error(str(error))
    command = [str(executable), "--origin", origin, "--vault-id", args.vault_id, "--output", str(args.output.resolve()), "--quiescent"]
    if args.build_only:
        print(json.dumps({"executable": str(executable), "command": command}, ensure_ascii=False))
    else:
        subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
