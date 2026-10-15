"""Build a disposable app from the production Mac shell; never installs over Solasi.

python experiments/serve_native_validation.py build /tmp/solasi-native-qa --runtime PATH
Add --audio PATH --mode long for the existing long human audio capture fixture.
Only launching the resulting app starts its server. Model work still requires a UI click.
"""
import argparse
import asyncio
import builtins
import hashlib
import json
from pathlib import Path
import plistlib
import platform
import runpy
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def create_validation_app(folder, runtime, port, *, frontend=None, storage_fixture=None):
    from fastapi import HTTPException
    from pydantic import BaseModel
    from lecture_study import server
    from lecture_study.config import AppConfig
    from lecture_study.course_materials import document_metadata
    from lecture_study.db import new_id, now
    from lecture_study.materials import inspect_file, register_file
    from tests.fixtures import pdf_fixture

    folder = Path(folder).resolve()
    data = folder / 'data'
    if data.is_symlink():
        raise ValueError('QA data must stay inside the disposable folder')
    app = server.create_app(AppConfig(data, Path(runtime), port=port))
    app.routes[:] = [route for route in app.routes if route.name != 'frontend']
    info_path = folder / 'fixture-info.json'
    if info_path.exists():
        info = json.loads(info_path.read_text())
    else:
        original = folder / 'Native-QA.pdf'
        original.write_bytes(pdf_fixture())
        course_id = new_id()
        with app.state.db:
            app.state.db.execute('INSERT INTO courses VALUES (?,?,?,?)', (course_id, '네이티브 검증 과목', '검증용 PDF와 메모·필기만 저장합니다.', now()))
        asset = register_file(app.state.db, None, inspect_file(original), course_id)
        metadata = asyncio.run(document_metadata(app.state.db, asset['id'], Path(runtime)))
        info = {'course_id': course_id, 'asset_id': asset['id'], 'document_sha256': metadata['sha256']}
        info_path.write_text(json.dumps(info))
    flags = {'enabled': False, 'failures': 0}
    original_save = server.save_page_document

    def save_page_document(db, *args, **kwargs):
        if db is app.state.db and flags['enabled']:
            flags['failures'] += 1
            raise HTTPException(503, '검증용 페이지 저장 실패')
        return original_save(db, *args, **kwargs)

    server.save_page_document = save_page_document

    class FailureInput(BaseModel):
        enabled: bool

    @app.get('/api/fixture/fail-page-writes')
    async def failure_state():
        return dict(flags)

    @app.post('/api/fixture/fail-page-writes')
    async def fail_page_writes(body: FailureInput):
        flags['enabled'] = body.enabled
        return dict(flags)

    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import HTMLResponse, Response
    frontend = Path(frontend) if frontend else ROOT / 'frontend/dist'
    navigation = '<nav style="position:fixed;bottom:8px;right:8px;z-index:99999;background:#fff;color:#111;padding:10px;border:1px solid #555"><a href="/">제품 화면</a> · <a href="/fixture">QA 제어</a> · <a href="/tests/ink-storage-fixture.html?id=20261016native">저장·복구 fixture</a></nav>'

    @app.get('/')
    async def qa_index():
        return HTMLResponse((frontend / 'index.html').read_text().replace('<body>', '<body>' + navigation, 1))

    @app.get('/fixture')
    async def controls():
        return HTMLResponse('<meta charset="utf-8"><title>Solasi QA 제어</title><h1>QA 제어</h1><p>검증용 서버의 페이지 PUT 저장만 실패시킵니다.</p><button id="enable">저장 실패 켜기</button> <button id="disable">저장 실패 끄기</button><pre id="state" role="status">확인 중</pre>' + navigation + '<script src="/fixture-controls.js"></script>')

    @app.get('/fixture-controls.js')
    async def controls_script():
        return Response("""const output=document.getElementById('state');
async function state(enabled){try{if(enabled!==undefined){const {csrf_token}=await(await fetch('/api/client')).json();const r=await fetch('/api/fixture/fail-page-writes',{method:'POST',headers:{'Content-Type':'application/json','X-Session-Token':csrf_token},body:JSON.stringify({enabled})});if(!r.ok)throw new Error(await r.text());}const r=await fetch('/api/fixture/fail-page-writes');output.textContent=JSON.stringify(await r.json());}catch(e){output.textContent=String(e);}}
document.getElementById('enable').onclick=()=>void state(true);document.getElementById('disable').onclick=()=>void state(false);void state();""", media_type='text/javascript')

    if storage_fixture:
        storage_fixture = Path(storage_fixture)
        @app.get('/tests/ink-storage-fixture.html')
        async def storage_page():
            html = (storage_fixture / 'tests/ink-storage-fixture.html').read_text().replace('"/assets/', '"/fixture-assets/')
            return HTMLResponse(html.replace('<body>', '<body>' + navigation, 1))
        app.mount('/fixture-assets', StaticFiles(directory=storage_fixture / 'assets'), name='storage-fixture')
    app.mount('/', StaticFiles(directory=frontend, html=True), name='frontend')
    return app, info


def serve(manifest):
    import uvicorn
    from lecture_study import launcher
    settings = json.loads(Path(manifest).read_text())
    folder = Path(settings['folder'])
    if not (folder / '.native-validation').is_file():
        raise ValueError('Disposable validation marker is missing')
    listener = launcher.bind_listener(settings['port'], strict=True)
    if settings['mode'] == 'long':
        from lecture_study import config
        original_config = config.AppConfig
        original_print = builtins.print
        launcher.bind_listener = lambda *args, **kwargs: listener
        config.AppConfig = lambda data, runtime, **kwargs: original_config(data, Path(settings['runtime']), **kwargs)
        def native_print(*args, **kwargs):
            if args and isinstance(args[0], str) and args[0].startswith('http://127.0.0.1:'):
                args = ('실행 링크: ' + args[0], *args[1:])
            return original_print(*args, **kwargs)
        builtins.print = native_print
        sys.argv = ['serve_long_recording_fixture.py', str(folder / 'long-run'), settings['audio'], 'single', settings['model'], 'direct']
        try:
            runpy.run_path(str(ROOT / 'experiments/serve_long_recording_fixture.py'), run_name='__main__')
        finally:
            builtins.print = original_print
            config.AppConfig = original_config
            listener.close()
        return
    app, info = create_validation_app(folder, settings['runtime'], settings['port'], frontend=settings.get('frontend'), storage_fixture=settings.get('storage_fixture'))
    url = f"http://127.0.0.1:{settings['port']}/#bootstrap={app.state.bootstrap_token}"
    (folder / 'server-info.json').write_text(json.dumps({'url': url, **info}))
    print('실행 링크: ' + url, flush=True)
    try:
        uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=settings['port'], access_log=False)).run(sockets=[listener])
    finally:
        listener.close()


def build_exec_shim(folder, python, script, manifest):
    folder = Path(folder)
    shim = folder / 'run-server'
    source = folder / 'run-server.c'
    arguments = ', '.join(json.dumps(str(value)) for value in (python, script, 'serve', manifest))
    source.write_text('#include <unistd.h>\n#include <stdio.h>\nint main(void) {\n'
        '  if (chdir("/private/tmp") != 0) { perror("QA chdir"); return 126; }\n'
        '  char *args[] = {' + arguments + ', NULL};\n'
        '  execv(args[0], args); perror("QA execv"); return 127;\n}\n')
    staged = shim.with_suffix('.new')
    subprocess.run(['/usr/bin/xcrun', 'clang', '-O2', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(staged)], check=True)
    staged.replace(shim)
    return shim


def build(args):
    folder = args.folder.expanduser().absolute()
    if folder.exists():
        raise ValueError('Use a new disposable output folder')
    runtime_source = args.runtime.expanduser().resolve(strict=True)
    if args.mode == 'long':
        if args.audio is None:
            raise ValueError('--audio is required for the long fixture')
        audio = args.audio.expanduser().resolve(strict=True)
        if not audio.with_suffix('.json').is_file():
            raise ValueError('The audio provenance .json sidecar is required')
    folder.mkdir(parents=True, mode=0o700)
    (folder / '.native-validation').touch(mode=0o600)
    (folder / 'data').mkdir(mode=0o700)
    runtime = folder / 'runtime'
    runtime.mkdir(mode=0o700)
    for name in ('asr', 'ffmpeg', 'models', 'ollama', 'ollama-models', 'tessdata'):
        source = runtime_source / name
        if source.exists():
            (runtime / name).symlink_to(source, target_is_directory=source.is_dir())
    native_source = (ROOT / 'macos/Solasi.swift').read_text()
    old_log = '    private let logURL = FileManager.default.homeDirectoryForCurrentUser\n        .appendingPathComponent("Library/Logs/Solasi/server.log")'
    if native_source.count(old_log) != 1:
        raise ValueError('Native log declaration changed; review the QA-only override')
    qa_source = folder / 'NativeValidation.swift'
    qa_source.write_text(native_source.replace(old_log, '    private let logURL = URL(fileURLWithPath: ' + json.dumps(str(folder / 'server.log')) + ')'))
    manifest = folder / 'validation.json'
    manifest.write_text(json.dumps({'folder': str(folder), 'runtime': str(runtime), 'port': args.port, 'mode': args.mode, 'audio': str(audio) if args.mode == 'long' else None, 'model': args.model, 'native_source_sha256': hashlib.sha256(native_source.encode()).hexdigest(), 'qa_source_override': 'log URL only'}))
    # The QA executable blocked in dyld before main when stored under Documents.
    shim_folder = Path(tempfile.mkdtemp(prefix='solasi-native-shim-', dir='/private/tmp'))
    shim = build_exec_shim(shim_folder, sys.executable, Path(__file__).resolve(), manifest)
    bundle = folder / ('Solasi Long Validation.app' if args.mode == 'long' else 'Solasi Native Validation.app')
    subprocess.run([sys.executable, str(ROOT / 'scripts/install_macos_app.py'), '--data-dir', str(folder / 'data'), '--runtime-dir', str(runtime), '--destination', str(bundle), '--port', str(args.port)], check=True)
    launch = bundle / 'Contents/Resources/launch.json'
    settings = json.loads(launch.read_text())
    settings['python'] = str(shim)
    launch.write_text(json.dumps(settings))
    info_path = bundle / 'Contents/Info.plist'
    with info_path.open('rb') as handle:
        info = plistlib.load(handle)
    info.update(CFBundleIdentifier='local.solasi.validation.' + args.mode, CFBundleName=bundle.stem, CFBundleDisplayName=bundle.stem)
    with info_path.open('wb') as handle:
        plistlib.dump(info, handle)
    subprocess.run(['/usr/bin/xcrun', 'swiftc', '-O', '-target', platform.machine() + '-apple-macosx13.0', '-module-cache-path', str(folder / 'module-cache'), str(qa_source), '-o', str(bundle / 'Contents/MacOS/Solasi')], check=True)
    subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', str(bundle)], check=True)
    subprocess.run(['/usr/bin/codesign', '--verify', '--strict', '--verbose=2', str(bundle)], check=True)
    print('QA app: ' + str(bundle))
    print('Shared model files are linked; data, runtime control state, bundle storage, port and fixture output are separate.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    builder = commands.add_parser('build')
    builder.add_argument('folder', type=Path)
    builder.add_argument('--runtime', type=Path, required=True)
    builder.add_argument('--mode', choices=('app', 'long'), default='app')
    builder.add_argument('--audio', type=Path)
    builder.add_argument('--model', default='qwen3.5:4b')
    builder.add_argument('--port', type=int, default=62435)
    runner = commands.add_parser('serve')
    runner.add_argument('manifest', type=Path)
    args = parser.parse_args()
    if args.command == 'build':
        if not 1 <= args.port <= 65535:
            parser.error('--port must be 1–65535')
        build(args)
    else:
        serve(args.manifest)


if __name__ == '__main__':
    main()
