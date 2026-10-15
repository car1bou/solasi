"""Serve a disposable real-worklet/WAV fixture; drive its fault buttons through a browser.

Run from lecture-study: .venv/bin/python experiments/serve_recording_fixture.py /tmp/recording-check
No microphone access or model inference: the page generates silent MediaStream audio.
"""
import json
import subprocess
import sys
from pathlib import Path
import uvicorn
from fastapi.staticfiles import StaticFiles

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lecture_study import server
from lecture_study.config import AppConfig
from lecture_study.db import create_session
from lecture_study.launcher import bind_listener

async def no_inference(db,chunk,runtime_dir):
    with db:db.execute("UPDATE transcript_ranges SET status='done' WHERE id=?",(chunk['id'],))

if __name__=='__main__':
    folder=Path(sys.argv[1]).resolve()
    if folder.exists():raise SystemExit('Use a new, disposable fixture directory')
    folder.mkdir(parents=True)
    listener=bind_listener();port=listener.getsockname()[1]
    server.process_chunk=no_inference
    app=server.create_app(AppConfig(folder/'data',folder/'runtime',port=port))
    sid=create_session(app.state.db,'lecture','녹음 복구 검증',None,None).id
    entry=folder/'fixture.tsx'
    entry.write_text('import {mount} from '+json.dumps(str(ROOT/'frontend/tests/recording-fixture.tsx'))+';mount('+json.dumps(sid)+');')
    (folder/'index.html').write_text('<html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>녹음 복구 검증</title><div id="root"></div><script type="module" src="./fixture.tsx"></script></html>')
    build="import {build} from 'vite';await build({configFile:false,root:process.argv[1],build:{assetsInlineLimit:0,outDir:'dist'}});"
    subprocess.run(['node','--input-type=module','-e',build,str(folder)],cwd=ROOT/'frontend',check=True)
    if app.routes[-1].name=='frontend':app.routes.pop()
    app.mount('/',StaticFiles(directory=folder/'dist',html=True))
    url=f'http://127.0.0.1:{port}/#bootstrap='+app.state.bootstrap_token
    (folder/'info.json').write_text(json.dumps({'url':url,'session_id':sid,'data_dir':str(folder/'data')},ensure_ascii=False))
    print(url,flush=True)
    try:uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,access_log=False)).run(sockets=[listener])
    except KeyboardInterrupt:pass
    finally:listener.close()
