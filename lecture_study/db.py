import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from .models import Session

def now() -> str:
    return datetime.now(timezone.utc).isoformat()

def new_id() -> str:
    return uuid4().hex

def open_db(data_dir: Path) -> sqlite3.Connection:
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(data_dir / "app.sqlite3", timeout=10, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version>18:
        db.close()
        raise ValueError("더 최신 앱의 데이터입니다")
    migration=""
    if version==2:
        columns={row["name"] for row in db.execute("PRAGMA table_info(assets)")}
        for name,definition in (("external_path","TEXT"),("mtime_ns","INTEGER"),("version","INTEGER NOT NULL DEFAULT 1")):
            if name not in columns: migration+="ALTER TABLE assets ADD COLUMN "+name+" "+definition+";\n"
    if version<6:
        columns={row["name"] for row in db.execute("PRAGMA table_info(transcript_ranges)")}
        if columns and "prompt" not in columns:
            migration+="ALTER TABLE transcript_ranges ADD COLUMN prompt TEXT NOT NULL DEFAULT '';\n"
    if version<7:
        columns={row["name"] for row in db.execute("PRAGMA table_info(transcript_ranges)")}
        if columns and "model" not in columns:
            migration+="ALTER TABLE transcript_ranges ADD COLUMN model TEXT;\nUPDATE transcript_ranges SET model='base' WHERE status='done' AND quiet=0;\n"
    if version<13 and db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone():
        db.execute('PRAGMA foreign_keys=OFF')
        migration+="CREATE TABLE jobs_v13(id TEXT PRIMARY KEY,session_id TEXT REFERENCES sessions(id),kind TEXT NOT NULL,status TEXT NOT NULL,request TEXT NOT NULL,result TEXT,error TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL); INSERT INTO jobs_v13 SELECT * FROM jobs; DROP TABLE jobs; ALTER TABLE jobs_v13 RENAME TO jobs;\n"
    if version<14:
        columns={row['name'] for row in db.execute('PRAGMA table_info(notes)')}
        if columns and 'anchor_ms' not in columns:migration+="ALTER TABLE notes ADD COLUMN anchor_ms INTEGER;\n"
    if version<15:
        columns={row['name'] for row in db.execute('PRAGMA table_info(transcripts)')}
        if columns and 'superseded_by' not in columns:migration+="ALTER TABLE transcripts ADD COLUMN superseded_by TEXT REFERENCES transcripts(id);\n"
        migration+="DROP VIEW IF EXISTS searchable_chunks;\n"
    if version<16:
        columns={row['name']for row in db.execute('PRAGMA table_info(recordings)')}
        for name,definition in (('transcription_mode',"TEXT NOT NULL DEFAULT 'realtime' CHECK(transcription_mode IN ('realtime','after_stop'))"),('transcription_released','INTEGER NOT NULL DEFAULT 1 CHECK(transcription_released IN (0,1))'),('capture_id',"TEXT NOT NULL DEFAULT ''")):
            if columns and name not in columns:migration+='ALTER TABLE recordings ADD COLUMN '+name+' '+definition+';\n'
        if columns:migration+="UPDATE recordings SET capture_id=id WHERE capture_id='';\n"
    if version<17:
        columns={row['name'] for row in db.execute('PRAGMA table_info(assets)')}
        if columns and 'extraction_sha256' not in columns:
            migration+="ALTER TABLE assets ADD COLUMN extraction_sha256 TEXT; UPDATE assets SET extraction_sha256=sha256 WHERE extraction IS NOT NULL;\n"
        columns={row['name'] for row in db.execute('PRAGMA table_info(jobs)')}
        if columns and 'course_id' not in columns:migration+="ALTER TABLE jobs ADD COLUMN course_id TEXT REFERENCES courses(id);\n"
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='artifacts'").fetchone():
            db.execute('PRAGMA foreign_keys=OFF')
            migration+="""CREATE TABLE artifacts_v17(id TEXT PRIMARY KEY,job_id TEXT NOT NULL UNIQUE REFERENCES jobs(id) ON DELETE CASCADE,session_id TEXT REFERENCES sessions(id),kind TEXT NOT NULL,body TEXT NOT NULL,evidence TEXT NOT NULL,metadata TEXT NOT NULL,edited INTEGER NOT NULL DEFAULT 0,confirmed INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,course_id TEXT REFERENCES courses(id),CHECK((session_id IS NULL)!=(course_id IS NULL)));
INSERT INTO artifacts_v17 SELECT *,NULL FROM artifacts;
DROP TABLE artifacts;
ALTER TABLE artifacts_v17 RENAME TO artifacts;
"""
        migration+="DROP VIEW IF EXISTS searchable_chunks;\n"
    if version<18:migration+="DROP VIEW IF EXISTS searchable_chunks;\n"
    try:
        backfill="INSERT OR IGNORE INTO course_assets SELECT s.course_id,sa.asset_id FROM session_assets sa JOIN sessions s ON s.id=sa.session_id WHERE s.course_id IS NOT NULL AND s.kind='lecture';" if version<17 else ""
        db.executescript("BEGIN IMMEDIATE;\n"+migration+Path(__file__).with_name("schema.sql").read_text()+backfill)
        if db.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('데이터의 참조 관계를 확인하세요')
        db.commit()
    except BaseException:
        db.rollback();db.close();raise
    db.execute('PRAGMA foreign_keys=ON')
    if db.execute('PRAGMA foreign_key_check').fetchone(): db.close();raise ValueError('데이터의 참조 관계를 확인하세요')
    return db

def data_dir(db) -> Path:
    return Path(db.execute("PRAGMA database_list").fetchone()[2]).parent

def session(db, session_id: str):
    row = db.execute("SELECT id,kind,course_id,title,description,lecture_no,started_at,created_at,recording_status FROM sessions WHERE id=? AND deleted=0", (session_id,)).fetchone()
    if row is None:
        raise KeyError("기록을 찾을 수 없습니다")
    return dict(row)


def course(db, course_id: str):
    row=db.execute('SELECT * FROM courses WHERE id=?',(course_id,)).fetchone()
    if row is None:raise KeyError('과목을 찾을 수 없습니다')
    return dict(row)


def request_owner(db, request):
    return session(db,request.session_id) if request.session_id else course(db,request.course_id)

def create_session(db, kind: str, title: str, course_id: str|None, lecture_no: int|None, started_at: str|None = None, description: str = "") -> Session:
    if course_id and not db.execute("SELECT 1 FROM courses WHERE id=?", (course_id,)).fetchone():
        raise KeyError("과목을 찾을 수 없습니다")
    if kind == "meeting" and course_id:
        raise ValueError("회의에는 과목을 지정하지 않습니다")
    created = now()
    if started_at:
        parsed = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("일시에는 시간대가 필요합니다")
        started_at = parsed.astimezone(timezone.utc).isoformat()
    ident = new_id()
    with db:
        db.execute("INSERT INTO sessions(id,kind,course_id,title,description,lecture_no,started_at,created_at) VALUES (?,?,?,?,?,?,?,?)", (ident,kind,course_id,title,description,lecture_no,started_at or created,created))
    return Session.model_validate(session(db, ident))
