import json
import re
import shutil
from pathlib import Path
from .db import data_dir,session
from .models import SourceRef
from .materials import source_status
from .audio import get_recording,recording_path
from .transcription import external_audio_path


def cleanup_files(db):
    root=data_dir(db).resolve()
    for task in db.execute("SELECT * FROM file_cleanup").fetchall():
        try:
            if task["kind"] not in ("audio","assets") or not re.fullmatch("[a-f0-9]{32}",task["resource_id"]): raise ValueError("관리 경로가 유효하지 않습니다")
            path=root/task["kind"]/task["resource_id"]
            if not path.parent.resolve().is_relative_to(root): raise ValueError("관리 경로 밖의 파일입니다")
            if path.is_symlink(): path.unlink()
            elif path.exists(): shutil.rmtree(path)
            with db: db.execute("DELETE FROM file_cleanup WHERE kind=? AND resource_id=?",(task["kind"],task["resource_id"]))
        except (OSError,ValueError) as exc:
            with db: db.execute("UPDATE file_cleanup SET error=? WHERE kind=? AND resource_id=?",(str(exc)[:300],task["kind"],task["resource_id"]))


def delete_audio(db,sid):
    session(db,sid)
    with db:
        for row in db.execute("SELECT id,kind FROM recordings WHERE session_id=?",(sid,)).fetchall():
            if row["kind"]=="live": db.execute("INSERT OR IGNORE INTO file_cleanup(kind,resource_id) VALUES ('audio',?)",(row["id"],))
        db.execute("UPDATE recordings SET status='audio_deleted',external_path=NULL WHERE session_id=?",(sid,))
        db.execute("UPDATE sessions SET recording_status='audio_deleted' WHERE id=?",(sid,))
    cleanup_files(db)


def delete_session(db,sid,confirmed):
    if confirmed is not True: raise ValueError("기록 삭제를 확인하세요")
    if not db.execute("SELECT 1 FROM sessions WHERE id=?",(sid,)).fetchone(): raise KeyError("기록을 찾을 수 없습니다")
    with db:
        db.execute("UPDATE sessions SET deleted=1 WHERE id=?",(sid,))
        assets=[r[0] for r in db.execute("SELECT asset_id FROM session_assets WHERE session_id=?",(sid,))]
        recordings=[r["id"] for r in db.execute("SELECT id FROM recordings WHERE session_id=?",(sid,))]
        for rid in recordings:
            db.execute("INSERT OR IGNORE INTO file_cleanup(kind,resource_id) VALUES ('audio',?)",(rid,))
        db.execute("UPDATE sources SET deleted=1,text_snapshot='' WHERE json_extract(ref,'$.session_id')=?",(sid,))
        db.execute("DELETE FROM session_assets WHERE session_id=?",(sid,))
        for aid in assets:
            if not db.execute("SELECT 1 FROM session_assets WHERE asset_id=?",(aid,)).fetchone():
                db.execute("UPDATE sources SET deleted=1,text_snapshot='' WHERE json_extract(ref,'$.asset_id')=?",(aid,))
                db.execute("DELETE FROM assets WHERE id=?",(aid,))
                db.execute("INSERT OR IGNORE INTO file_cleanup(kind,resource_id) VALUES ('assets',?)",(aid,))
        deleted={row[0] for row in db.execute('SELECT id FROM sources WHERE deleted=1')}
        for row in db.execute('SELECT id,evidence FROM artifacts').fetchall():
            evidence=json.loads(row['evidence']);changed=False
            for item in evidence:
                if item['ref']['id'] in deleted and item['text']: item['text']='';changed=True
            if changed: db.execute('UPDATE artifacts SET evidence=? WHERE id=?',(json.dumps(evidence,ensure_ascii=False),row['id']))
        for row in db.execute("SELECT id,request FROM jobs WHERE kind='ai'").fetchall():
            request=json.loads(row['request']);changed=False
            for item in [*request.get('evidence',[]),*(e for part in request.get('summary_parts',[]) for e in part)]:
                if item['ref']['id'] in deleted and item['text']: item['text']='';changed=True
            if changed: db.execute('UPDATE jobs SET request=? WHERE id=?',(json.dumps(request,ensure_ascii=False),row['id']))
        for row in db.execute("SELECT id,result FROM jobs WHERE kind='search' AND result IS NOT NULL").fetchall():
            result=json.loads(row['result']);changed=False
            for item in result.get('evidence',[]):
                if item['ref']['id'] in deleted and item['text']:item['text']='';changed=True
            if changed:
                result['warning']='삭제된 근거 포함 · 새 검색을 실행하세요'
                db.execute('UPDATE jobs SET result=? WHERE id=?',(json.dumps(result,ensure_ascii=False),row['id']))
        db.execute("DELETE FROM chunks WHERE source_id IN (SELECT id FROM sources WHERE deleted=1)")
        db.execute("DELETE FROM terms WHERE scope_key=?",("session:"+sid,))
        db.execute("DELETE FROM settings WHERE key IN (?,?,?)",("asr_terms:"+sid,"candidate_options:"+sid,"candidate_last:"+sid))
        db.execute("DELETE FROM notes WHERE session_id=?",(sid,))
        db.execute("DELETE FROM transcripts WHERE session_id=?",(sid,))
        for rid in recordings:
            for table in ("recording_scan","pcm_packets","audio_files","transcript_ranges"):
                db.execute("DELETE FROM "+table+" WHERE recording_id=?",(rid,))
        db.execute("DELETE FROM recordings WHERE session_id=?",(sid,))
        db.execute("DELETE FROM jobs WHERE session_id=?",(sid,))
        db.execute("DELETE FROM sessions WHERE id=?",(sid,))
    cleanup_files(db)


def playable_path(db,rid):
    record=get_recording(db,rid)
    session(db,record["session_id"])
    if record["status"]=="audio_deleted": raise ValueError("원음이 삭제되거나 연결 해제되었습니다")
    path=external_audio_path(db,record) if record["kind"]=="file" else recording_path(db,rid)
    if not path.is_file(): raise ValueError("원음을 찾을 수 없습니다")
    return path


def playback_position(db,rid,ms):
    record=get_recording(db,rid)
    playable_path(db,rid)
    frame=round((ms-record["offset_ms"])*record["sample_rate"]/1000)
    if not 0<=frame<record["source_frames"]: raise ValueError("원음 범위를 벗어납니다")
    if record["kind"]=="file": return frame/record["sample_rate"]
    packet=db.execute("SELECT * FROM pcm_packets WHERE recording_id=? AND first_frame<=? AND first_frame+frame_count>? ORDER BY seq LIMIT 1",(rid,frame,frame)).fetchone()
    if not packet: raise ValueError("누락 구간은 재생할 수 없습니다")
    return (packet["stored_start"]+frame-packet["first_frame"])/record["sample_rate"]


def resolve_source(db,ref):
    saved=db.execute("SELECT * FROM sources WHERE id=?",(ref.id,)).fetchone()
    if saved is None: raise KeyError("출처를 찾을 수 없습니다")
    actual=SourceRef.model_validate_json(saved["ref"])
    result={"status":"deleted" if saved["deleted"] else "current","ref":actual.model_dump(),"text_snapshot":saved["text_snapshot"],"open_url":None,"seek_seconds":None,"end_seconds":None}
    if saved["deleted"]: return result
    if actual.kind=="material":
        asset=db.execute("SELECT * FROM assets WHERE id=?",(actual.asset_id,)).fetchone()
        if not asset: result["status"]="deleted";return result
        original=source_status(db,dict(asset))
        result["original_status"]=original
        if original=="missing": result["status"]="deleted"
        elif original!="current" or actual.version!=asset["version"]: result["status"]="changed"
        if result["status"]=="current":
            result["open_url"]="/api/assets/"+actual.asset_id+"/original"+("#page="+str(actual.page) if asset["kind"]=="pdf" and actual.page else "")
            if actual.page and asset["kind"] in ("pdf","png","jpg"): result["image_url"]="/api/assets/"+actual.asset_id+"/pages/"+str(actual.page)
    elif actual.kind in ("note","transcript"):
        if not db.execute("SELECT 1 FROM sessions WHERE id=? AND deleted=0",(actual.session_id,)).fetchone(): result["status"]="deleted";return result
        if actual.kind=="note":
            current=db.execute("SELECT max(version) FROM notes WHERE session_id=?",(actual.session_id,)).fetchone()[0]
            if current!=actual.version: result["status"]="changed"
        else:
            ident=actual.id.rsplit(":v",1)[0]
            segment=db.execute("SELECT * FROM transcripts WHERE id=?",(ident,)).fetchone()
            if not segment: result["status"]="deleted";return result
            if segment["revision"]!=actual.version or segment["superseded_by"]: result["status"]="changed"
            try:
                result["seek_seconds"]=playback_position(db,segment["recording_id"],actual.start_ms)
                result["end_seconds"]=result["seek_seconds"]+(actual.end_ms-actual.start_ms)/1000
                result["open_url"]="/api/recordings/"+segment["recording_id"]+"/audio"
            except (OSError,ValueError,KeyError): result["original_status"]="missing"
    elif actual.kind=="web":
        web=db.execute('SELECT title,retrieved_at FROM web_sources WHERE source_id=?',(actual.id,)).fetchone()
        if web: result.update(dict(web))
        from urllib.parse import urlsplit
        if actual.url and urlsplit(actual.url).scheme in ("http","https"): result["open_url"]=actual.url
    return result
