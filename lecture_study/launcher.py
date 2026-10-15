import argparse
import json
import socket
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
import uvicorn
from .config import AppConfig
from .server import create_app
from .runtime import probe_runtime

def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]

def bind_listener(port=0):
    listener=socket.socket()
    listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    try:listener.bind(('127.0.0.1',port))
    except OSError:
        if not port:listener.close();raise
        listener.bind(('127.0.0.1',0))
    listener.listen(128);return listener


def main():
    parser = argparse.ArgumentParser(description="수업·회의 기록실")
    parser.add_argument("--data-dir", type=Path, default=Path.home()/"Library/Application Support/LectureStudy")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument('--runtime-dir',type=Path)
    parser.add_argument('--check',action='store_true')
    args = parser.parse_args()
    if args.port<0 or args.port>65535: parser.error('포트는 0–65535입니다')
    if args.check:
        print(json.dumps(probe_runtime(AppConfig(args.data_dir,args.runtime_dir or args.data_dir/'runtime')),ensure_ascii=False,indent=2));return
    listener=bind_listener(args.port);port=listener.getsockname()[1]
    config = AppConfig(args.data_dir, args.runtime_dir or args.data_dir/"runtime", port=port)
    try:app = create_app(config)
    except ValueError as exc:listener.close();parser.error(str(exc))
    url = f"http://127.0.0.1:{port}"
    def open_when_ready():
        for _ in range(100):
            try:
                with urllib.request.urlopen(url+"/api/health", timeout=1) as response:
                    if response.status == 200:
                        webbrowser.open(url+"/#bootstrap="+app.state.bootstrap_token)
                        return
            except OSError:
                time.sleep(0.1)
    if not args.no_browser:
        threading.Thread(target=open_when_ready, daemon=True).start()
    print('실행 링크: '+url+'/#bootstrap='+app.state.bootstrap_token,flush=True)
    try:uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,access_log=False)).run(sockets=[listener])
    except KeyboardInterrupt:pass
    finally:listener.close()

if __name__ == "__main__":
    main()
