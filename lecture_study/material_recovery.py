"""Restore an original's location without replacing its document identity."""
import json
from pathlib import Path
from .db import data_dir, session
from .materials import asset_dir, public_asset


def reconnect_original(db, asset_id, inspected, *, session_id=None, course_id=None):
    owner_course = session(db, session_id).get('course_id') if session_id else course_id
    linked = db.execute('SELECT 1 FROM course_assets WHERE course_id=? AND asset_id=? UNION ALL SELECT 1 FROM session_assets WHERE session_id=? AND asset_id=?', (owner_course, asset_id, session_id, asset_id)).fetchone()
    if not linked:
        raise KeyError('연결된 자료가 아닙니다')
    _, asset = asset_dir(db, asset_id)
    if Path(inspected['path']).is_relative_to(data_dir(db).resolve()):
        raise ValueError('앱 관리 폴더 밖의 원본 파일을 선택하세요')
    if (inspected['sha256'], inspected['kind']) != (asset['sha256'], asset['kind']):
        raise ValueError('기존 원본과 내용이 다릅니다. 같은 내용의 원본을 선택하세요. 다른 자료는 자료 연결로 추가할 수 있습니다')
    if db.execute('SELECT 1 FROM assets WHERE external_path=? AND id!=?', (inspected['path'], asset_id)).fetchone():
        raise ValueError('이미 다른 자료에 연결된 파일입니다. 기존 연결은 변경하지 않았습니다')
    for row in db.execute("SELECT request FROM jobs WHERE kind='parse' AND status IN ('queued','running')"):
        if json.loads(row['request']).get('asset_id') == asset_id:
            raise ValueError('자료 추출이 끝난 뒤 원본을 다시 찾으세요')
    with db:
        db.execute('UPDATE assets SET external_path=?,mtime_ns=? WHERE id=?', (inspected['path'], inspected['mtime_ns'], asset_id))
    return public_asset(db, asset_dir(db, asset_id)[1])
