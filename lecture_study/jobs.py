import asyncio
import json
from .db import new_id, now, session,course


async def wait_for_transcription(db,job_id):
    paused=False
    def show_wait(waiting):
        row=db.execute('SELECT result FROM jobs WHERE id=?',(job_id,)).fetchone()
        if row is None:return
        progress=json.loads(row[0]) if row[0] else {}
        if waiting:progress['paused_reason']='전사 처리 후 실행'
        else:progress.pop('paused_reason',None)
        with db:db.execute('UPDATE jobs SET result=?,updated_at=? WHERE id=?',(json.dumps(progress,ensure_ascii=False),now(),job_id))
    try:
        while db.execute("SELECT 1 FROM transcript_ranges WHERE final=1 AND status IN ('queued','running') LIMIT 1").fetchone():
            if not paused:show_wait(True);paused=True
            await asyncio.sleep(.1)
    finally:
        if paused:show_wait(False)


def get_job(db, ident):
    row = db.execute("SELECT * FROM jobs WHERE id=?", (ident,)).fetchone()
    if row is None:
        raise KeyError("작업을 찾을 수 없습니다")
    result = dict(row)
    for key in ("request","result"):
        result[key] = json.loads(result[key]) if result[key] else None
    return result


def active_candidate(db,sid,exclude=None):
    for row in db.execute("SELECT id,request FROM jobs WHERE session_id=? AND kind='ai' AND status IN ('queued','running') ORDER BY created_at",(sid,)):
        if row['id']!=exclude and json.loads(row['request']).get('request',{}).get('kind')=='candidates':return get_job(db,row['id'])
    return None


def submit_job(db, session_id, kind, request, retry_job_id=None,course_id=None):
    if session_id and course_id:raise ValueError('회차 또는 과목 한 곳을 지정하세요')
    if session_id is not None:session(db,session_id)
    if course_id is not None:course(db,course_id)
    if kind=='ai' and request.get('request',{}).get('kind')=='candidates' and active_candidate(db,session_id,retry_job_id):
        raise ValueError('이 기록의 질문 후보 추출이 이미 진행 중입니다')
    if retry_job_id:
        old = get_job(db,retry_job_id)
        if old["session_id"]!=session_id or old['course_id']!=course_id or old["kind"]!=kind or old["request"]!=request:
            raise ValueError("재시도 작업이 일치하지 않습니다")
        if old["status"] not in ("failed","cancelled","interrupted"):
            return old
        with db:
            db.execute("UPDATE jobs SET status='queued',error=NULL,result=NULL,updated_at=? WHERE id=?",(now(),retry_job_id))
        return get_job(db,retry_job_id)
    ident = new_id()
    with db:
        db.execute("INSERT INTO jobs(id,session_id,course_id,kind,status,request,created_at,updated_at) VALUES (?,?,?,?,'queued',?,?,?)",
                   (ident,session_id,course_id,kind,json.dumps(request,ensure_ascii=False),now(),now()))
    return get_job(db,ident)


async def run_job(db, ident, operation):
    with db:
        db.execute("UPDATE jobs SET status='running',updated_at=? WHERE id=?",(now(),ident))
    try:
        result = await operation()
        if hasattr(result,"model_dump"):
            result = result.model_dump()
        with db:
            db.execute("UPDATE jobs SET status='done',result=?,error=NULL,updated_at=? WHERE id=?",
                       (json.dumps(result,ensure_ascii=False),now(),ident))
    except asyncio.CancelledError:
        with db:
            db.execute("UPDATE jobs SET status='cancelled',updated_at=? WHERE id=?",(now(),ident))
        raise
    except Exception as exc:
        with db:
            db.execute("UPDATE jobs SET status='failed',error=?,updated_at=? WHERE id=?",(str(exc)[:500],now(),ident))


def launch_job(app, job, operation):
    task = asyncio.create_task(run_job(app.state.db,job["id"],operation))
    app.state.tasks.add(task)
    app.state.job_tasks[job["id"]] = task
    def finished(task):
        if task.cancelled():
            with app.state.db:app.state.db.execute("UPDATE jobs SET status='cancelled',updated_at=? WHERE id=? AND status IN ('queued','running')",(now(),job['id']))
        app.state.tasks.discard(task)
        app.state.job_tasks.pop(job["id"],None)
        if not app.state.closing and app.state.db.execute("SELECT 1 FROM jobs WHERE kind='asr_review' AND status='queued' LIMIT 1").fetchone():app.state.kick_transcription()
    task.add_done_callback(finished)
    return job
