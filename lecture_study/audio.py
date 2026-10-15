import math
import hashlib
import json
import os
import struct
from datetime import datetime
from .db import data_dir,new_id,now,session
from .jobs import submit_job

MAX_COUNTER = 2**53-1


def get_recording(db,ident):
    row = db.execute("SELECT * FROM recordings WHERE id=?",(ident,)).fetchone()
    if row is None:
        raise KeyError("녹음을 찾을 수 없습니다")
    value = dict(row)
    value["gaps"] = json.loads(value["gaps"])
    return value


def recording_path(db,ident):
    get_recording(db,ident)
    return data_dir(db)/"audio"/ident/"raw.wav"


def wav_header(rate,frames):
    size = frames*2
    if size>2**32-37:
        raise ValueError("녹음 파일 크기 한도입니다. 새 녹음을 시작하세요")
    return struct.pack("<4sI4s4sIHHIIHH4sI",b"RIFF",size+36,b"WAVE",b"fmt ",16,1,1,rate,rate*2,2,16,b"data",size)


def write_pcm(path,rate,stored_frames,payload):
    header = wav_header(rate,stored_frames+len(payload)//2)
    with path.open("r+b") as handle:
        handle.seek(44+stored_frames*2)
        handle.write(payload)
        handle.seek(0)
        handle.write(header)
        handle.flush()
        os.fsync(handle.fileno())


def repair_wav(path,rate,frames):
    if not path.is_file() or path.stat().st_size<44+frames*2:
        raise OSError("저장된 원음을 복구할 수 없습니다")
    with path.open("r+b") as handle:
        handle.truncate(44+frames*2)
        handle.seek(0)
        handle.write(wav_header(rate,frames))
        handle.flush()
        os.fsync(handle.fileno())


def start_recording(db,session_id,sample_rate,transcription_mode="realtime",resume_from=None):
    session(db,session_id)
    if type(sample_rate) is not int or not 8000<=sample_rate<=192000:
        raise ValueError("지원하지 않는 sample rate입니다")
    if db.execute("SELECT 1 FROM recordings WHERE session_id=? AND status='recording'",(session_id,)).fetchone():
        raise ValueError("이미 녹음 중입니다")
    if transcription_mode not in ('realtime','after_stop'):raise ValueError('전사 방식을 확인하세요')
    previous=get_recording(db,resume_from) if resume_from else None
    if previous and (previous['session_id']!=session_id or previous['transcription_mode']!=transcription_mode or previous['status']=='recording' or transcription_mode=='after_stop' and previous['transcription_released']):raise ValueError('복구할 녹음의 소속·방식·상태가 일치하지 않습니다')
    ident,created = new_id(),now()
    capture_id=(previous['capture_id']or previous['id'])if previous else ident
    first = db.execute("SELECT started_at FROM recordings WHERE session_id=? ORDER BY started_at LIMIT 1",(session_id,)).fetchone()
    offset = max(0,int((datetime.fromisoformat(created)-datetime.fromisoformat(first[0])).total_seconds()*1000)) if first else 0
    previous_end=db.execute('SELECT max(offset_ms+source_frames*1000.0/sample_rate) FROM recordings WHERE session_id=?',(session_id,)).fetchone()[0]
    offset=max(offset,math.ceil(previous_end or 0))
    folder = data_dir(db)/"audio"/ident
    folder.mkdir(parents=True,mode=0o700)
    with (folder/"raw.wav").open("wb") as handle:
        handle.write(wav_header(sample_rate,0))
        handle.flush()
        os.fsync(handle.fileno())
    with db:
        db.execute("INSERT INTO recordings(id,session_id,sample_rate,status,started_at,offset_ms,transcription_mode,transcription_released,capture_id) VALUES (?,?,?,'recording',?,?,?,?,?)",
                   (ident,session_id,sample_rate,created,offset,transcription_mode,int(transcription_mode=='realtime'),capture_id))
        db.execute("UPDATE sessions SET recording_status='recording' WHERE id=?",(session_id,))
    return ident


def append_pcm(db,recording_id,seq,first_frame,frame_count,payload):
    row = get_recording(db,recording_id)
    if any(type(n) is not int or not 0<=n<=MAX_COUNTER for n in (seq,first_frame,frame_count)) or first_frame+frame_count>MAX_COUNTER:
        raise ValueError("프레임 위치가 유효하지 않습니다")
    if not 1<=frame_count<=row["sample_rate"] or len(payload)!=frame_count*2:
        raise ValueError("PCM 길이가 유효하지 않습니다")
    digest = hashlib.sha256(payload).hexdigest()
    old = db.execute("SELECT * FROM pcm_packets WHERE recording_id=? AND seq=?",(recording_id,seq)).fetchone()
    if old:
        if (old["first_frame"],old["frame_count"],old["sha256"])!=(first_frame,frame_count,digest):
            raise ValueError("같은 프레임 번호의 내용이 다릅니다")
        return {"seq":seq,"frame_count":frame_count,"stored_frames":row["stored_frames"],"source_frames":row["source_frames"]}
    if row["status"]!="recording" or seq<=row["last_seq"] or first_frame<row["source_frames"]:
        raise ValueError("녹음 상태 또는 프레임 순서가 유효하지 않습니다")
    gaps = row["gaps"]
    if first_frame>row["source_frames"]:
        gaps.append({"start_frame":row["source_frames"],"end_frame":first_frame})
    path = recording_path(db,recording_id)
    try:
        write_pcm(path,row["sample_rate"],row["stored_frames"],payload)
        with db:
            db.execute("INSERT INTO pcm_packets VALUES (?,?,?,?,?,?,?)",
                       (recording_id,seq,first_frame,frame_count,row["stored_frames"],digest,now()))
            db.execute("UPDATE recordings SET stored_frames=?,source_frames=?,last_seq=?,gaps=? WHERE id=?",
                       (row["stored_frames"]+frame_count,first_frame+frame_count,seq,json.dumps(gaps),recording_id))
    except BaseException:
        try:
            repair_wav(path,row["sample_rate"],row["stored_frames"])
        except OSError:
            pass
        raise
    return {"seq":seq,"frame_count":frame_count,"stored_frames":row["stored_frames"]+frame_count,"source_frames":first_frame+frame_count}


def interrupt_recording(db,ident):
    row = get_recording(db,ident)
    if row["status"]=="recording":
        with db:
            db.execute("UPDATE recordings SET status='interrupted' WHERE id=?",(ident,))
            db.execute("UPDATE sessions SET recording_status='interrupted' WHERE id=?",(row["session_id"],))


def stop_recording(db,recording_id,end_frame=None,interrupted=False,error=None):
    row = get_recording(db,recording_id)
    if end_frame is not None and (type(end_frame) is not int or not 0<=end_frame<=MAX_COUNTER):
        raise ValueError("종료 프레임이 유효하지 않습니다")
    gaps = row["gaps"]
    if end_frame and end_frame>row["source_frames"]:
        gaps.append({"start_frame":row["source_frames"],"end_frame":end_frame})
        interrupted = True
    if row["stop_job_id"]:
        from .jobs import get_job
        # A disconnected socket can finalize before the client's last frame count arrives.
        with db:
            db.execute("UPDATE recordings SET gaps=?,source_frames=?,error=coalesce(?,error),status=CASE WHEN ? THEN 'interrupted' ELSE status END WHERE id=?",(json.dumps(gaps),max(row["source_frames"],end_frame or 0),error,interrupted,recording_id))
        return get_job(db,row["stop_job_id"])
    repair_wav(recording_path(db,recording_id),row["sample_rate"],row["stored_frames"])
    job = submit_job(db,row["session_id"],"transcribe",{"recording_id":recording_id,"final":True})
    status = "interrupted" if interrupted or row["status"]=="interrupted" else "stopped"
    with db:
        db.execute("UPDATE recordings SET status=?,ended_at=?,gaps=?,stop_job_id=?,source_frames=?,error=coalesce(?,error) WHERE id=?",(status,now(),json.dumps(gaps),job["id"],max(row["source_frames"],end_frame or 0),error,recording_id))
        db.execute("UPDATE sessions SET recording_status=? WHERE id=?",(status,row["session_id"]))
    return job


def recover_recordings(db):
    for saved in db.execute("SELECT id FROM recordings WHERE kind='live' AND status='recording'").fetchall():
        row = get_recording(db,saved["id"])
        try:
            repair_wav(recording_path(db,row["id"]),row["sample_rate"],row["stored_frames"])
        except OSError:
            with db:
                db.execute("UPDATE recordings SET error='원음 복구 실패' WHERE id=?",(row["id"],))
        interrupt_recording(db,row["id"])
