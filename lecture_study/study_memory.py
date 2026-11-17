"""Local conversation storage and course memory with revocable provenance."""
import json
from .db import new_id, now, course, session
from .models import Scope


def owner(db, session_id=None, course_id=None):
    if bool(session_id) == bool(course_id):
        raise ValueError('회차 또는 과목 한 곳을 지정하세요')
    if session_id:
        row = session(db, session_id)
        course_id = row['course_id']
    elif course_id:
        course(db, course_id)
    return {'course_id': course_id, 'session_id': None if course_id else session_id,
            'origin_session_id': session_id}


def key(owned):
    return 'course:' + owned['course_id'] if owned['course_id'] else 'session:' + owned['session_id']


def enabled(db):
    row = db.execute("SELECT value FROM settings WHERE key='study_memory_enabled'").fetchone()
    return row is None or json.loads(row[0]) is True


def control(db, owned):
    row = db.execute('SELECT * FROM study_controls WHERE owner_key=?', (key(owned),)).fetchone()
    return dict(row) if row else {'epoch': 0, 'cutoff': ''}


def epoch(db, owned):
    global_epoch = db.execute("SELECT value FROM settings WHERE key='study_memory_epoch'").fetchone()
    return str(global_epoch[0] if global_epoch else 0) + ':' + str(control(db, owned)['epoch'])


def thread_row(db, ident, owned):
    row = db.execute('SELECT * FROM study_threads WHERE id=? AND course_id IS ? AND session_id IS ?',
                     (ident, owned['course_id'], owned['session_id'])).fetchone()
    if row is None:
        raise KeyError('이 과목의 대화를 찾을 수 없습니다')
    return dict(row)


def list_threads(db, owned):
    return [dict(r) for r in db.execute('SELECT * FROM study_threads WHERE course_id IS ? AND session_id IS ? ORDER BY updated_at DESC,id',
                                      (owned['course_id'], owned['session_id']))]


def create_thread(db, owned, title='새 대화'):
    ident = new_id()
    with db:
        db.execute('INSERT INTO study_threads(id,course_id,session_id,origin_session_id,title,created_at,updated_at) VALUES (?,?,?,?,?,?,?)',
                   (ident, owned['course_id'], owned['session_id'], owned['origin_session_id'], title[:120], now(), now()))
    return thread_row(db, ident, owned)


def read_thread(db, ident, owned, before=None, limit=40):
    result = thread_row(db, ident, owned)
    if not 1 <= limit <= 100 or (before is not None and before < 1):
        raise ValueError('대화 범위를 확인하세요')
    rows = db.execute('''SELECT m.*,j.status AS job_status,j.error AS job_error FROM study_messages m
        LEFT JOIN jobs j ON j.id=m.job_id WHERE m.thread_id=? AND (? IS NULL OR m.ordinal<?)
        ORDER BY m.ordinal DESC LIMIT ?''', (ident, before, before, limit + 1)).fetchall()
    result['has_more'] = len(rows) > limit
    result['messages'] = [dict(r) for r in reversed(rows[:limit])]
    for msg in result['messages']:
        msg['scope'] = json.loads(msg['scope'])
    result['epoch'] = epoch(db, owned)
    return result


def add_user(db, ident, owned, text, scope, *, message_id=None, commit=True):
    from .retrieval import scope_ids
    thread_row(db, ident, owned)
    if not isinstance(text, str) or not text.strip() or len(text) > 10000:
        raise ValueError('질문은 1~10,000자로 입력하세요')
    selected = Scope.model_validate(scope)
    requested = owner(db, selected.session_id, selected.course_id)
    if key(requested) != key(owned):
        raise ValueError('대화와 질문의 과목 범위가 다릅니다')
    scope_ids(db, selected)
    ident_msg = message_id or new_id()
    ordinal = db.execute('SELECT coalesce(max(ordinal),0)+1 FROM study_messages WHERE thread_id=?', (ident,)).fetchone()[0]
    db.execute('INSERT INTO study_messages(id,thread_id,ordinal,role,text,scope,created_at) VALUES (?,?,?,\'user\',?,?,?)',
               (ident_msg, ident, ordinal, text.strip(), json.dumps(selected.model_dump()), now()))
    db.execute("UPDATE study_threads SET title=CASE WHEN title='새 대화' THEN ? ELSE title END,updated_at=?,summary_error=NULL WHERE id=?", (text.strip()[:60], now(), ident))
    if commit:
        db.commit()
    return dict(db.execute('SELECT * FROM study_messages WHERE id=?', (ident_msg,)).fetchone())


def memory_list(db, cid):
    course(db, cid)
    return [dict(r) for r in db.execute('''SELECT m.*,s.thread_id,t.title AS conversation_title FROM study_memories m
        LEFT JOIN study_messages s ON s.id=m.source_message_id LEFT JOIN study_threads t ON t.id=s.thread_id
        WHERE m.course_id=? ORDER BY m.updated_at DESC,m.id''', (cid,))]


def invalidate(db, owned, *, cutoff=False):
    old = control(db, owned)
    db.execute('INSERT OR REPLACE INTO study_controls VALUES (?,?,?)',
               (key(owned), old['epoch'] + 1, now() if cutoff else old['cutoff']))
    threads = [r['id'] for r in list_threads(db, owned)]
    for row in db.execute("SELECT id,request FROM jobs WHERE kind='study_chat'").fetchall():
        request = json.loads(row['request'])
        if request.get('thread_id') in threads:
            # Frozen context is personal data too; stale jobs must never replay it.
            request = {'thread_id': request['thread_id'], 'invalidated': True}
            db.execute("UPDATE jobs SET request=?,status=CASE WHEN status IN ('queued','running') THEN 'cancelled' ELSE status END,error='학습 맥락이 변경되었습니다. 새 질문을 실행하세요' WHERE id=?", (json.dumps(request), row['id']))
    db.execute('UPDATE study_threads SET summary=\'\',summary_through=0 WHERE course_id IS ? AND session_id IS ?',
               (owned['course_id'], owned['session_id']))
    if cutoff:
        db.execute('UPDATE study_messages SET processed=1 WHERE thread_id IN (SELECT id FROM study_threads WHERE course_id IS ? AND session_id IS ?)',
                   (owned['course_id'], owned['session_id']))


def set_enabled(db, value):
    if type(value) is not bool:
        raise ValueError('기억 사용 여부를 확인하세요')
    with db:
        db.execute("INSERT OR REPLACE INTO settings VALUES ('study_memory_enabled',?)", (json.dumps(value),))
        old = db.execute("SELECT value FROM settings WHERE key='study_memory_epoch'").fetchone()
        db.execute("INSERT OR REPLACE INTO settings VALUES ('study_memory_epoch',?)", (str(int(old[0]) + 1 if old else 1),))
        for row in db.execute('SELECT DISTINCT course_id,session_id FROM study_threads').fetchall():
            invalidate(db, dict(row))


def edit_memory(db, cid, ident, text, status, revision):
    course(db, cid)
    if not isinstance(text, str) or not text.strip() or len(text) > 2000 or status not in ('active', 'resolved', 'review'):
        raise ValueError('기억 내용과 상태를 확인하세요')
    with db:
        changed = db.execute('UPDATE study_memories SET text=?,status=?,manual=1,revision=revision+1,updated_at=? WHERE id=? AND course_id=? AND revision=?',
                             (text.strip(), status, now(), ident, cid, revision)).rowcount
        if not changed:
            raise ValueError('기억이 변경되었습니다. 새로고침 후 다시 수정하세요')
        invalidate(db, owner(db, course_id=cid), cutoff=True)


def delete_memory(db, cid, ident):
    course(db, cid)
    with db:
        if not db.execute('DELETE FROM study_memories WHERE id=? AND course_id=?', (ident, cid)).rowcount:
            raise KeyError('기억을 찾을 수 없습니다')
        invalidate(db, owner(db, course_id=cid), cutoff=True)


def clear_memories(db, cid):
    course(db, cid)
    with db:
        db.execute('DELETE FROM study_memories WHERE course_id=?', (cid,))
        invalidate(db, owner(db, course_id=cid), cutoff=True)


def delete_thread(db, ident, owned):
    thread_row(db, ident, owned)
    with db:
        invalidate(db, owned)
        for row in db.execute("SELECT id,request FROM jobs WHERE kind='study_chat'").fetchall():
            if json.loads(row['request']).get('thread_id') == ident:
                db.execute('DELETE FROM artifacts WHERE job_id=?', (row['id'],))
                db.execute('UPDATE jobs SET result=NULL WHERE id=?', (row['id'],))
        db.execute('DELETE FROM study_threads WHERE id=?', (ident,))


def next_extraction(db):
    if not enabled(db):
        return None
    row = db.execute('''SELECT t.* FROM study_threads t WHERE EXISTS (
        SELECT 1 FROM study_messages m WHERE m.thread_id=t.id AND m.role='user' AND m.processed=0)
        AND t.summary_error IS NULL
        ORDER BY t.updated_at LIMIT 1''').fetchone()
    if row is None:
        return None
    thread = dict(row)
    thread['messages'] = [dict(r) for r in db.execute("SELECT * FROM study_messages WHERE thread_id=? AND role='user' AND processed=0 ORDER BY ordinal LIMIT 6", (row['id'],))]
    return thread


def apply_extraction(db, tid, owned, expected_epoch, ids, body):
    thread_row(db, tid, owned)
    if expected_epoch != epoch(db, owned) or not enabled(db):
        raise ValueError('학습 맥락이 변경되었습니다')
    if not isinstance(body, dict) or not isinstance(body.get('summary'), str) or len(body['summary']) > 2000 or not isinstance(body.get('items'), list) or len(body['items']) > 12:
        raise ValueError('학습 기억 형식을 확인하세요')
    rows = {r['id']: dict(r) for r in db.execute("SELECT * FROM study_messages WHERE thread_id=? AND role='user'", (tid,)) if r['id'] in ids}
    cutoff = control(db, owned)['cutoff']
    if len(rows) != len(ids) or any(r['created_at'] <= cutoff for r in rows.values()):
        raise ValueError('학습 맥락이 변경되었습니다')
    for item in body['items']:
        if (not isinstance(item, dict) or item.get('kind') not in ('topic', 'progress', 'difficulty', 'question')
                or item.get('status') not in ('active', 'resolved', 'review')
                or not isinstance(item.get('text'), str) or not 1 <= len(item['text']) <= 1000
                or not isinstance(item.get('quote'), str) or not 1 <= len(item['quote']) <= 1000
                or item.get('message_id') not in rows or item['quote'] not in rows[item['message_id']]['text']):
            raise ValueError('원문과 다른 학습 기억입니다')
        if item.get('replaces'):
            previous=db.execute('SELECT * FROM study_memories WHERE id=? AND course_id=?',(item['replaces'],owned['course_id'])).fetchone()
            if previous is None or previous['manual'] or previous['kind']!=item['kind']:
                raise ValueError('정정할 자동 기억의 근거를 확인하세요')
    with db:
        if owned['course_id']:
            for item in body['items']:
                if item.get('replaces'):
                    db.execute('DELETE FROM study_memories WHERE id=?',(item['replaces'],))
                db.execute('''INSERT INTO study_memories(id,course_id,kind,text,quote,source_message_id,status,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(source_message_id,kind,quote) DO NOTHING''',
                           (new_id(), owned['course_id'], item['kind'], item['text'], item['quote'], item['message_id'], item['status'], now(), now()))
        for ident in ids:
            db.execute('UPDATE study_messages SET processed=1 WHERE id=?', (ident,))
        db.execute('UPDATE study_threads SET summary=?,summary_through=?,summary_error=NULL WHERE id=?',
                   (body['summary'], max((r['ordinal'] for r in rows.values()), default=0), tid))


def remove_session_context(db, sid):
    rows = db.execute('SELECT DISTINCT t.* FROM study_threads t JOIN study_messages m ON m.thread_id=t.id WHERE json_extract(m.scope,\'$.session_id\')=?', (sid,)).fetchall()
    for row in rows:
        invalidate(db, dict(row), cutoff=True)
        db.execute("DELETE FROM study_messages WHERE thread_id=? AND json_extract(scope,'$.session_id')=?", (row['id'], sid))
        db.execute("UPDATE study_threads SET title='대화' WHERE id=?", (row['id'],))
    db.execute('DELETE FROM study_threads WHERE session_id=?', (sid,))


def context_messages(db, tid, owned, query):
    cutoff = control(db, owned)['cutoff']
    rows = [dict(r) for r in db.execute('''SELECT m.* FROM study_messages m LEFT JOIN jobs j ON j.id=m.job_id
        WHERE m.thread_id=? AND m.created_at>? AND (m.role='assistant' OR m.job_id IS NULL OR j.status='done') ORDER BY m.ordinal''', (tid, cutoff))]
    recent = rows[-8:]
    words = [w for w in query.split() if len(w) > 1]
    older = [r for r in rows[:-8] if any(w in r['text'] for w in words)][-4:]
    return older + recent


def export_records(db):
    return {'conversations': [dict(r) for r in db.execute('SELECT * FROM study_threads ORDER BY id')],
            'messages': [dict(r) for r in db.execute('SELECT * FROM study_messages ORDER BY thread_id,ordinal')],
            'memories': [dict(r) for r in db.execute('SELECT * FROM study_memories ORDER BY id')]}


def sync_quizzes(db):
    from .answers import get_artifact
    from .outputs import get_attempt
    if not enabled(db):
        return
    for row in db.execute("SELECT p.id,a.session_id,a.course_id,p.created_at FROM attempts p JOIN artifacts a ON a.id=p.quiz_id WHERE p.status='done'").fetchall():
        owned=owner(db,row['session_id'],row['course_id'])
        cid=owned['course_id']
        if not cid or row['created_at']<=control(db,owned)['cutoff']:
            continue
        attempt=get_attempt(db,row['id'])
        grade={'correct':'정답','partial':'부분 정답','incorrect':'오답'}.get(attempt['grade'])
        if not grade:
            continue
        quiz=get_artifact(db,attempt['quiz_id'])
        question=next((q for q in quiz['body'].get('questions',[]) if q.get('id')==attempt['question_id']),None)
        if not question:
            continue
        text='퀴즈 관찰 · '+question['prompt'][:500]+' · '+grade+' (이 문항의 결과이며 이해도 전체를 뜻하지 않습니다)'
        old=db.execute('SELECT * FROM study_memories WHERE source_attempt_id=?',(row['id'],)).fetchone()
        if old and (old['manual'] or old['text']==text):
            continue
        with db:
            if old:
                invalidate(db,owned)
            db.execute('''INSERT INTO study_memories(id,course_id,kind,text,quote,source_attempt_id,status,created_at,updated_at)
                VALUES (?,?,'quiz',?,?,?,'review',?,?) ON CONFLICT(source_attempt_id) DO UPDATE SET text=excluded.text,quote=excluded.quote,revision=study_memories.revision+1,updated_at=excluded.updated_at''',
                       (new_id(),cid,text,'문제: '+question['prompt'][:500]+'\n내 답: '+attempt['submitted_answer'][:1000]+'\n현재 평가: '+grade,row['id'],row['created_at'],now()))
