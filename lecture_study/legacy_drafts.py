"""Validate a quiescent WK export and import raw rows in one vault transaction."""
import hashlib
import json
import re
from pathlib import Path

from .native_drafts import MAX_UPLOAD, NativeDrafts, checked_draft, encoded


def manifest(folder: Path, expected_origin: str):
    path=folder/'manifest.json'
    if path.is_symlink() or not 0<path.stat().st_size<=16*1024*1024:raise ValueError('초안 이전 목록 크기 오류')
    raw=path.read_bytes();value=json.loads(raw)
    if (type(value.get('version')) is not int or value['version']!=1 or value.get('format')!='solasi-legacy-drafts-jsonl' or
            value.get('origin')!=expected_origin or value.get('source_bundle_id')!='local.solasi.launcher' or
            value.get('verified') is not True or not re.fullmatch('[0-9a-f]{32}',str(value.get('vault_id',''))) or
            not isinstance(value.get('rows'),list) or type(value.get('row_count')) is not int or value['row_count']!=len(value['rows']) or
            type(value.get('total_bytes')) is not int or value['total_bytes']<0 or
            not re.fullmatch('[0-9a-f]{64}',str(value.get('rows_sha256',''))) or
            value.get('unsaved_inputs')!=[]):
        raise ValueError('이전 앱의 검증된 초안 목록이 아닙니다')
    return raw,value


def rows(folder, value):
    path=folder/'drafts.jsonl'
    if path.is_symlink() or path.stat().st_size!=value['total_bytes']:raise ValueError('초안 백업 길이 오류')
    whole=hashlib.sha256();offset=0;keys=set()
    with path.open('rb') as handle:
        for item in value['rows']:
            if type(item.get('bytes')) is not int or not 1<=item['bytes']<=MAX_UPLOAD or item.get('offset')!=offset:
                raise ValueError('초안 백업 범위 오류')
            raw=handle.read(item['bytes']);newline=handle.read(1)
            if newline!=b'\n' or hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('초안 백업 해시 오류')
            whole.update(raw+newline);offset+=len(raw)+1
            row=checked_draft(json.loads(raw))
            if row['key']!=item['key'] or row['key'] in keys:raise ValueError('초안 키 중복 또는 불일치')
            paths=item.get('undefined_paths',[])
            validate_undefined_paths(row,paths)
            paths_raw=json.dumps(paths,ensure_ascii=False,separators=(',',':')).encode('utf-8')
            if hashlib.sha256(paths_raw).hexdigest()!=item.get('undefined_paths_sha256'):
                raise ValueError('초안 undefined 목록 해시 오류')
            keys.add(row['key']);yield row
        if handle.read(1) or offset!=value['total_bytes'] or whole.hexdigest()!=value['rows_sha256']:
            raise ValueError('전체 초안 백업 대조 실패')


def validate_undefined_paths(row, paths):
    if not isinstance(paths,list):raise ValueError('초안 undefined 목록 오류')
    seen=set()
    for path in paths:
        if (not isinstance(path,list) or not 1<=len(path)<=64 or
                any(not isinstance(part,str) and type(part) is not int for part in path)):
            raise ValueError('초안 undefined 경로 오류')
        key=tuple(path)
        if key in seen:raise ValueError('초안 undefined 경로 중복')
        seen.add(key);parent=row
        for part in path[:-1]:
            if isinstance(parent,dict) and isinstance(part,str) and part in parent:parent=parent[part]
            elif isinstance(parent,list) and type(part) is int and 0<=part<len(parent):parent=parent[part]
            else:raise ValueError('초안 undefined 상위 경로 오류')
        last=path[-1]
        if isinstance(parent,dict) and isinstance(last,str) and last not in parent:continue
        if isinstance(parent,list) and type(last) is int and 0<=last<len(parent) and parent[last] is None:continue
        raise ValueError('초안 undefined 표현이 원문과 다릅니다')


def import_backup(db, folder, expected_origin):
    raw,value=manifest(folder,expected_origin)
    # Validate the complete export before adding the native storage tables.
    for _ in rows(folder,value):pass
    store=NativeDrafts(db,initial_id=value['vault_id'])
    if store.state()['vault_id']!=value['vault_id']:raise ValueError('다른 보관함의 초안입니다')
    digest=hashlib.sha256(raw).hexdigest()
    saved=db.execute('SELECT report FROM native_migrations WHERE digest=?',(digest,)).fetchone()
    if saved:
        report=json.loads(saved[0]);verify_import(db,folder,expected_origin);return report
    conflicts=0;mapping=[]
    with db:
        for row in rows(folder,value):
            restored,conflict=store.preserve_imported_row(row,digest)
            conflicts+=conflict;mapping.append(restored['key'])
        theme=value.get('theme')
        if theme not in ('light','dark','system'):theme='system'
        db.execute('INSERT OR IGNORE INTO settings VALUES (?,?)',('native_theme',theme))
        report={'sha256':digest,'count':len(mapping),'conflicts':conflicts,'keys':mapping,'origin':expected_origin,'format':value['format']}
        db.execute('INSERT INTO native_migrations VALUES (?,?,?)',(digest,raw.decode(),encoded(report)))
    verify_import(db,folder,expected_origin)
    return report


def verify_import(db, folder, expected_origin):
    raw,value=manifest(folder,expected_origin);digest=hashlib.sha256(raw).hexdigest()
    saved=db.execute('SELECT payload,report FROM native_migrations WHERE digest=?',(digest,)).fetchone()
    vault=db.execute("SELECT value FROM settings WHERE key='native_vault_id'").fetchone()
    if not saved or saved[0]!=raw.decode() or not vault or vault[0]!=value['vault_id']:raise ValueError('초안 이전 증거 없음')
    report=json.loads(saved[1])
    if report.get('count')!=value['row_count'] or len(report.get('keys',[]))!=value['row_count']:raise ValueError('초안 이전 개수 오류')
    for index,row in enumerate(rows(folder,value)):
        key=report['keys'][index]
        if key not in (row['key'],row['key']+'::import-'+digest):raise ValueError('초안 이전 키 오류')
        found=db.execute('SELECT value FROM native_drafts WHERE key=?',(key,)).fetchone()
        if not found or json.loads(found[0])!={**row,'key':key}:raise ValueError('초안 이전 내용 불일치')
    return digest
