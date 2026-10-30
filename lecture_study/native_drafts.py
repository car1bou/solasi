"""Vault-owned raw drafts; successful replies follow the SQLite commit."""
import base64
import binascii
import hashlib
import json
import re
import time
from uuid import uuid4

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr

MAX_UPLOAD = 64*1024*1024
CHUNK_SIZE = 256*1024
MAX_PREFERENCE = 4096


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def checked_key(key):
    if not isinstance(key, str) or not 1 <= len(key) <= 4096 or '\x00' in key:
        raise ValueError('초안 키 오류')
    return key


def checked_draft(row):
    if not isinstance(row, dict): raise ValueError('초안 형식 오류')
    checked_key(row.get('key'))
    if (not isinstance(row.get('text'), str) or not isinstance(row.get('ink'), list) or
            type(row.get('revision')) is not int or row['revision'] < 0 or
            not isinstance(row.get('token'), str) or
            ('dirty' in row and type(row['dirty']) is not bool)):
        raise ValueError('초안 내용 오류')
    encoded(row)
    return row


def preference_key(key):
    if not isinstance(key, str) or (key not in ('notebook-tools','workspace-layout') and not re.fullmatch(
            r'notebook-view:[0-9a-f]{32}:[0-9a-f]{64}', key)):
        raise ValueError('필기 설정 키 오류')
    return 'native_preference:'+key


def checked_preference(key, value):
    preference_key(key)
    if not isinstance(value, dict): raise ValueError('필기 설정 형식 오류')
    if key == 'workspace-layout':
        if set(value) != {'sidebarCollapsed'} or type(value['sidebarCollapsed']) is not bool:
            raise ValueError('과목 목록 보기 설정 오류')
        return value
    if key == 'notebook-tools':
        numeric = {'penWidth':(.0005,.04), 'penOpacity':(.05,1),
                   'highlighterWidth':(.0005,.04), 'highlighterOpacity':(.05,1), 'eraserSize':(.003,.06)}
        if set(value) - {'eraserMode','textSize'} != {'tool','penColor','highlighterColor',*numeric}:
            raise ValueError('필기 설정 항목 오류')
        if value['tool'] not in ('pen','highlighter','text','stroke-eraser','partial-eraser','lasso','pan'):
            raise ValueError('필기 도구 오류')
        if 'textSize' in value:numeric['textSize']=(.012,.08)
        if 'eraserMode' in value and value['eraserMode'] not in ('stroke-eraser','partial-eraser'):
            raise ValueError('지우개 방식 오류')
        for field in ('penColor','highlighterColor'):
            if not isinstance(value[field], str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value[field]):
                raise ValueError('필기 색상 오류')
    else:
        numeric = {'zoom':(.1,3)}
        if set(value) - {'pageLayout'} != {'zoomMode','zoom','rotation','notesOpen'}:
            raise ValueError('페이지 보기 설정 항목 오류')
        if 'pageLayout' in value and value['pageLayout'] not in ('continuous','single'):
            raise ValueError('페이지 표시 방식 오류')
        if (value['zoomMode'] not in ('fit','page','manual') or type(value['rotation']) is not int or
                value['rotation'] not in (0,90,180,270) or type(value['notesOpen']) is not bool):
            raise ValueError('페이지 보기 설정 오류')
    for field,(low,high) in numeric.items():
        if type(value[field]) not in (int,float) or not low <= value[field] <= high:
            raise ValueError('필기 설정 값 범위 오류')
    if len(encoded(value).encode('utf-8')) > MAX_PREFERENCE: raise ValueError('필기 설정 크기 오류')
    return value


class NativeDrafts:
    def __init__(self, db, initial_id=None):
        if initial_id is not None and (not isinstance(initial_id,str) or not re.fullmatch('[0-9a-f]{32}',initial_id)):
            raise ValueError('보관함 식별자 오류')
        self.db = db
        with db:
            db.execute('CREATE TABLE IF NOT EXISTS native_drafts(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS native_migrations(digest TEXT PRIMARY KEY,payload TEXT NOT NULL,report TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS native_uploads(id TEXT PRIMARY KEY,size INTEGER NOT NULL,received INTEGER NOT NULL,kind TEXT NOT NULL,journal_key TEXT,created REAL NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS native_upload_parts(id TEXT REFERENCES native_uploads(id) ON DELETE CASCADE,offset INTEGER,body BLOB NOT NULL,PRIMARY KEY(id,offset))')
            db.execute('INSERT OR IGNORE INTO settings VALUES (?,?)', ('native_vault_id', initial_id or uuid4().hex))

    def state(self):
        settings = dict(self.db.execute("SELECT key,value FROM settings WHERE key IN ('native_vault_id','native_theme')"))
        return {'vault_id':settings['native_vault_id'], 'theme':settings.get('native_theme', 'system')}

    def discard_abandoned_uploads(self):
        # Call only after acquiring the vault lock; previous processes cannot resume these transfers.
        with self.db: self.db.execute('DELETE FROM native_uploads')

    def theme(self, value):
        if value not in ('system', 'light', 'dark'): raise ValueError('화면 모드 오류')
        with self.db: self.db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', ('native_theme',value))
        return self.state()

    def read_preference(self, key):
        row = self.db.execute('SELECT value FROM settings WHERE key=?', (preference_key(key),)).fetchone()
        if row is None: return {'value':None}
        raw = row[0]
        if not isinstance(raw, str) or len(raw.encode('utf-8')) > MAX_PREFERENCE:
            raise ValueError('저장된 필기 설정 크기 오류')
        return {'value':checked_preference(key,json.loads(raw))}

    def write_preference(self, key, value):
        stored_key = preference_key(key)
        checked_preference(key,value)
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (stored_key,encoded(value)))
        return {'value':value}

    def read(self, key, after='', limit=100000):
        checked_key(key)
        if not isinstance(after,str) or type(limit) is not int or not 1 <= limit <= 100000:
            raise ValueError('초안 조회 범위 오류')
        prefix = key+'::'
        return [json.loads(row[0]) for row in self.db.execute(
            'SELECT value FROM native_drafts WHERE (key=? OR substr(key,1,?)=?) AND key>? ORDER BY key LIMIT ?', (key,len(prefix),prefix,after,limit))]

    def delete(self, key):
        checked_key(key)
        if '::' not in key or not key.rpartition('::')[2]: raise ValueError('복구 사본만 제거할 수 있습니다')
        with self.db: self.db.execute('DELETE FROM native_drafts WHERE key=?', (key,))
        return {'deleted':True}

    def begin(self, size, *, kind, journal_key=None):
        if type(size) is not int or not 1 <= size <= MAX_UPLOAD: raise ValueError('초안 전송 크기 오류')
        if kind not in ('write','import'): raise ValueError('초안 전송 형식 오류')
        if kind == 'write': checked_key(journal_key)
        with self.db:
            self.db.execute('DELETE FROM native_uploads WHERE created<?', (time.time()-3600,))
            if self.db.execute('SELECT count(*) FROM native_uploads').fetchone()[0] >= 4:
                raise ValueError('진행 중인 초안 저장을 기다려 주세요')
            ident = uuid4().hex
            self.db.execute('INSERT INTO native_uploads VALUES (?,?,0,?,?,?)', (ident,size,kind,journal_key,time.time()))
        return {'id':ident, 'chunk_size':CHUNK_SIZE}

    def _upload(self, ident):
        row = self.db.execute('SELECT * FROM native_uploads WHERE id=?', (ident,)).fetchone()
        if row is None: raise KeyError('진행 중인 초안 전송이 없습니다')
        return row

    def append(self, ident, offset, data):
        row = self._upload(ident)
        if not isinstance(data,str) or len(data)>4*((CHUNK_SIZE+2)//3): raise ValueError('초안 조각 크기 오류')
        try: part = base64.b64decode(data, validate=True)
        except (ValueError,binascii.Error): raise ValueError('초안 조각 인코딩 오류') from None
        if type(offset) is not int or offset != row['received'] or not 0 < len(part) <= CHUNK_SIZE or offset+len(part)>row['size']:
            raise ValueError('초안 조각 순서 또는 크기 오류')
        with self.db:
            self.db.execute('INSERT INTO native_upload_parts VALUES (?,?,?)', (ident,offset,part))
            self.db.execute('UPDATE native_uploads SET received=? WHERE id=?', (offset+len(part),ident))
        return {'received':offset+len(part)}

    def abort(self, ident):
        with self.db: self.db.execute('DELETE FROM native_uploads WHERE id=?', (ident,))
        return {'cancelled':True}

    def commit(self, ident):
        upload = self._upload(ident)
        if upload['received'] != upload['size']: raise ValueError('초안 전송이 끝나지 않았습니다')
        raw = b''.join(row[0] for row in self.db.execute('SELECT body FROM native_upload_parts WHERE id=? ORDER BY offset',(ident,)))
        if len(raw) != upload['size']: raise ValueError('초안 전송 길이가 다릅니다')
        digest = hashlib.sha256(raw).hexdigest()
        def invalid_constant(value): raise ValueError('초안 JSON 숫자 오류')
        try: value = json.loads(raw,parse_constant=invalid_constant)
        except (UnicodeError,json.JSONDecodeError): raise ValueError('초안 JSON 형식 오류') from None
        with self.db:
            if upload['kind'] == 'write':
                row = checked_draft(value)
                journal_key = upload['journal_key']
                if not journal_key.startswith(row['key']+'::') or journal_key == row['key']+'::':
                    raise ValueError('초안 복구 키 오류')
                self.db.execute('INSERT OR REPLACE INTO native_drafts VALUES (?,?)', (row['key'],encoded(row)))
                if row.get('dirty',True):
                    self.db.execute('INSERT OR REPLACE INTO native_drafts VALUES (?,?)', (journal_key,encoded({**row,'key':journal_key})))
                else: self.db.execute('DELETE FROM native_drafts WHERE key=?', (journal_key,))
                report = {'sha256':digest,'count':1}
            else: report = self._import(value, raw, digest)
            self.db.execute('DELETE FROM native_uploads WHERE id=?', (ident,))
        return report

    def _import(self, value, raw, digest):
        if (not isinstance(value,dict) or type(value.get('version')) is not int or value['version'] != 1 or
                value.get('vault_id') != self.state()['vault_id'] or not isinstance(value.get('origin'),str) or
                not isinstance(value.get('drafts'),list) or value.get('theme') not in ('system','light','dark')):
            raise ValueError('보관함 또는 초안 백업 형식이 다릅니다')
        saved = self.db.execute('SELECT report FROM native_migrations WHERE digest=?',(digest,)).fetchone()
        if saved: return json.loads(saved[0])
        rows = [checked_draft(row) for row in value['drafts']]
        if len({row['key'] for row in rows}) != len(rows): raise ValueError('백업에 중복 초안 키가 있습니다')
        conflicts = 0
        for row in rows:
            _,conflict=self.preserve_imported_row(row,digest)
            conflicts+=conflict
        self.db.execute('INSERT OR IGNORE INTO settings VALUES (?,?)',('native_theme',value['theme']))
        report = {'sha256':digest,'count':len(rows),'conflicts':conflicts}
        # Retain the complete export, including raw backups and unsaved editor input.
        self.db.execute('INSERT INTO native_migrations VALUES (?,?,?)',(digest,raw.decode('utf-8'),encoded(report)))
        return report

    def preserve_imported_row(self, row, digest):
        previous=self.db.execute('SELECT value FROM native_drafts WHERE key=?',(row['key'],)).fetchone()
        conflict=bool(previous and json.loads(previous[0])!=row)
        if conflict:
            row={**row,'key':checked_key(row['key']+'::import-'+digest)}
            previous=self.db.execute('SELECT value FROM native_drafts WHERE key=?',(row['key'],)).fetchone()
            if previous and json.loads(previous[0])!=row:raise ValueError('백업 복구 키가 충돌합니다')
        self.db.execute('INSERT OR IGNORE INTO native_drafts VALUES (?,?)',(row['key'],encoded(row)))
        if json.loads(self.db.execute('SELECT value FROM native_drafts WHERE key=?',(row['key'],)).fetchone()[0])!=row:
            raise ValueError('초안 이전 후 대조 실패')
        return row,conflict


class BeginInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    size: StrictInt
    kind: StrictStr
    journal_key: StrictStr | None = None


class PartInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    offset: StrictInt
    data: StrictStr


def attach_native_drafts(app, db):
    store = NativeDrafts(db)
    store.discard_abandoned_uploads()
    router = APIRouter(prefix='/api/native')

    @router.get('/state')
    async def state(): return store.state()

    @router.put('/theme')
    async def theme(body: dict): return store.theme(body.get('theme'))

    @router.get('/preferences/{key}')
    async def read_preference(key: str): return store.read_preference(key)

    @router.put('/preferences/{key}')
    async def write_preference(key: str, request: Request):
        raw = await request.body()
        if len(raw) > MAX_PREFERENCE: raise ValueError('필기 설정 크기 오류')
        try: body = json.loads(raw)
        except (UnicodeError,json.JSONDecodeError): raise ValueError('필기 설정 JSON 형식 오류') from None
        if not isinstance(body, dict) or set(body) != {'value'}: raise ValueError('필기 설정 요청 형식 오류')
        return store.write_preference(key,body['value'])

    @router.get('/drafts/read')
    async def read(key: str, after: str=''): return store.read(key,after,1)

    @router.delete('/drafts/journal')
    async def delete(key: str): return store.delete(key)

    @router.post('/drafts/uploads')
    async def begin(body: BeginInput): return store.begin(**body.model_dump())

    @router.put('/drafts/uploads/{ident}')
    async def append(ident: str, body: PartInput): return store.append(ident,**body.model_dump())

    @router.post('/drafts/uploads/{ident}/commit')
    async def commit(ident: str): return store.commit(ident)

    @router.delete('/drafts/uploads/{ident}')
    async def abort(ident: str): return store.abort(ident)

    app.include_router(router)
