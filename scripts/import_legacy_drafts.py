"""Import a verified, closed legacy app's draft export without deleting its store."""
import argparse
import json
from pathlib import Path
import subprocess
import sys


def main():
    from lecture_study.config import acquire_data_lock
    from lecture_study.db import open_db
    from lecture_study.legacy_drafts import import_backup
    from scripts.install_macos_app import read_existing_settings
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app',type=Path,required=True)
    parser.add_argument('--backup',type=Path,required=True)
    parser.add_argument('--editors-saved-and-closed',action='store_true',help='사용자가 기존 모든 창의 미저장 입력을 저장하고 종료했음을 확인')
    args=parser.parse_args()
    if not args.editors_saved_and_closed:parser.error('먼저 기존 앱의 모든 편집 입력을 저장한 뒤 앱을 종료하세요')
    settings=read_existing_settings(args.app)
    if 'port' not in settings:parser.error('이 앱은 이전 HTTP 버전이 아닙니다')
    running=subprocess.run(['/usr/sbin/lsof','-t','-a','-d','txt','--',str(args.app/'Contents/MacOS/Solasi')],capture_output=True,text=True)
    if running.returncode!=1 or running.stdout.strip():parser.error('이전 앱이 실행 중이거나 종료를 확인할 수 없습니다')
    data=Path(settings['data'])
    with acquire_data_lock(data):
        db=open_db(data)
        try:report=import_backup(db,args.backup,f"http://127.0.0.1:{settings['port']}")
        finally:db.close()
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    main()
