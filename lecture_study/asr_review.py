"""One native decoding alternative; application requires the user's confirmation."""
import json,re,tempfile
from collections import Counter
from pathlib import Path
from . import transcription as tr
from .db import now,new_id,session
from .jobs import submit_job,get_job
from .models import SourceRef
from .retrieval import index_source


def active_segments(db,chunk_id):
    return [dict(r)for r in db.execute('SELECT * FROM transcripts WHERE chunk_id=? AND final=1 AND superseded_by IS NULL ORDER BY start_ms,id',(chunk_id,))]


def result_utf8_failure(chunk):
    return chunk['final'] and chunk['status']=='failed' and chunk['error']==tr.ASR_RESULT_UTF8_ERROR


def finish_recording_job(db,record,*,repair_failed=False):
    if not record['stop_job_id'] or record['status']=='recording' or not record['transcription_released']:return
    counts=tr.transcription_status(db,record['id'])
    if counts['queued'] or counts['running']:return
    failed=db.execute("SELECT error FROM transcript_ranges WHERE recording_id=? AND status IN ('failed','interrupted') LIMIT 1",(record['id'],)).fetchone()
    status='failed' if failed else 'cancelled' if counts['cancelled'] else 'done'
    result=json.dumps(counts);error=failed[0]if failed else None
    if repair_failed:
        parent=get_job(db,record['stop_job_id'])
        if parent['status']=='failed' and parent['error']!=tr.ASR_RESULT_UTF8_ERROR and not db.execute("SELECT 1 FROM transcript_ranges WHERE recording_id=? AND status IN ('failed','interrupted') AND error=?",(record['id'],parent['error'])).fetchone():status,error='failed',parent['error']
    with db:
        db.execute("UPDATE jobs SET status=?,result=?,error=?,updated_at=? WHERE id=? AND (status IN ('queued','running') OR (? AND status='failed')) AND (status!=? OR result IS NOT ? OR error IS NOT ?)",
                   (status,result,error,now(),record['stop_job_id'],repair_failed,status,result,error))



def uncovered_activity(activity,rows,offset):
    covered=sorted((r['start_ms']-offset-250,r['end_ms']-offset+250)for r in rows);gaps=[]
    # shortcut: coarse ASR timestamps can hide missing words inside an otherwise covered interval.
    for voice in activity:
        start,end=voice['start_ms'],voice['end_ms'];cursor=start
        for a,b in covered:
            if a>=end:break
            if b<=cursor:continue
            if min(a,end)-cursor>=750:gaps.append({'start_ms':cursor,'end_ms':min(a,end)})
            cursor=max(cursor,b)
            if cursor>=end:break
        if end-cursor>=750:gaps.append({'start_ms':cursor,'end_ms':end})
    return gaps


def suspect_reason(db,chunk,activity=None):
    if result_utf8_failure(chunk):return tr.ASR_RESULT_UTF8_ERROR
    if not chunk['final'] or chunk['status']!='done' or chunk['quiet']:return None
    rows=active_segments(db,chunk['id']);record=tr.get_recording(db,chunk['recording_id'])
    duration=(chunk['end_frame']-chunk['start_frame'])/record['sample_rate']
    if not rows and duration<=8:return '짧은 비영점 원음의 빈 전사: 발화 또는 소음인지 확인 필요'
    sentences=[s.strip()for row in rows for s in re.split(r'(?<=[.!?。])\s*',row['text'])if len(s.strip())>=12]
    if any(count>=3 for count in Counter(sentences).values()):return '같은 긴 문장이 3회 이상 반복됨: 원음 확인 필요'
    compact=re.sub(r'[\s.!?。,，…]+','',' '.join(row['text']for row in rows))
    if any(len(match[0])>=12 for match in re.finditer(r'(.{1,20}?)\1{5,}',compact)):return '짧은 말이 과도하게 반복됨: 실제 반복·웃음 또는 인식 오류인지 원음 확인 필요'
    first=record['offset_ms']+round(chunk['start_frame']*1000/record['sample_rate'])
    if activity and uncovered_activity(activity,rows,first):return '음성 활동 중 전사 시각 밖 구간이 남음: 누락·소음·경계 오차인지 원음 확인 필요'
    return None


def checked_chunk(db,chunk_id):
    chunk=tr.range_row(db,chunk_id);record=tr.get_recording(db,chunk['recording_id']);session(db,record['session_id'])
    if not chunk['final'] or (chunk['status']!='done' and not result_utf8_failure(chunk)):raise ValueError('확정 전사 완료 또는 UTF-8 형식 오류 구간만 다시 인식할 수 있습니다')
    if record['status']=='audio_deleted':raise ValueError('원음이 삭제되거나 연결 해제되었습니다')
    if record['kind']=='file':tr.external_audio_path(db,record)
    elif not tr.recording_path(db,record['id']).is_file():raise ValueError('원음을 찾을 수 없습니다')
    return chunk,record


def queue_review(db,chunk_id,*,automatic,activity=None,runtime=None):
    chunk,record=checked_chunk(db,chunk_id)
    old=[get_job(db,r[0])for r in db.execute("SELECT id FROM jobs WHERE session_id=? AND kind='asr_review'",(record['session_id'],))]
    if automatic and any(j['request']['chunk_id']==chunk_id and j['request']['automatic']for j in old):return None
    if active:=next((j for j in old if j['request']['chunk_id']==chunk_id and j['status']in ('queued','running')),None):return active if not automatic else None
    if automatic and any(r['revision']>1 for r in active_segments(db,chunk_id)):return None
    reason=suspect_reason(db,chunk,activity)if automatic else '사용자가 원음 재인식을 요청함'
    if not reason:return None
    request={'chunk_id':chunk_id,'recording_id':record['id'],'chunk_revision':chunk['revision'],'original_status':chunk['status'],'original_error':chunk['error'],'automatic':automatic,'reason':reason,'original_segments':active_segments(db,chunk_id),'prompt':chunk['prompt'],'model':tr.MODEL_NAME,'alternative':'native-vad-off'}
    from . import qwen_asr
    if runtime is not None and qwen_asr.available(runtime):request.update(model=qwen_asr.MODEL,alternative=qwen_asr.ALTERNATIVE)
    if activity is not None:request['voice_activity_ranges']=activity
    return submit_job(db,record['session_id'],'asr_review',request)


def unchanged(db,request):
    chunk,record=checked_chunk(db,request['chunk_id'])
    if chunk['revision']!=request['chunk_revision'] or chunk['status']!=request.get('original_status','done') or chunk['error']!=request.get('original_error') or active_segments(db,chunk['id'])!=request['original_segments']:raise ValueError('후보 생성 후 전사가 변경되었습니다. 현재 원문으로 다시 인식하세요')
    return chunk,record


async def process_review(db,job,runtime):
    request=job['request'];chunk,record=unchanged(db,request)
    duration=round((chunk['end_frame']-chunk['start_frame'])*1000/record['sample_rate']);metrics={}
    with tempfile.TemporaryDirectory(prefix='lecture-review-')as temp:
        clip=Path(temp)/'input.wav';await tr.range_clip(db,record,chunk,clip,runtime)
        from . import qwen_asr
        if request['alternative']==qwen_asr.ALTERNATIVE:
            candidate=await qwen_asr.transcribe(clip,runtime);text=candidate['text'].strip()
            segments=[{'start_ms':0,'end_ms':duration,'text':text}]if text else [];metrics={k:v for k,v in candidate.items()if k!='text'}
            warning='Qwen3-ASR 재인식 후보입니다. 구간 전체 시각이며 단어 정렬이 아닙니다. 용어 힌트 없이 인식하며 소음·누락·잘못된 문장이 남을 수 있으므로 원음을 확인하세요.'
        else:
            segments=await tr.transcribe_range(clip,0,request['prompt'],runtime,padding_ms=200,vad_enabled=False)
            warning='음성 감지 없이 재인식한 후보입니다. 소음에서 잘못된 문장이 생길 수 있으므로 원음을 확인하세요.'
    unchanged(db,request)
    for s in segments:
        if type(s['start_ms'])is not int or type(s['end_ms'])is not int or not 0<=s['start_ms']<s['end_ms']<=duration or not isinstance(s['text'],str) or not s['text'].strip():raise ValueError('재인식 결과가 원음 범위를 벗어납니다')
    text=' '.join(s['text'].strip()for s in segments)
    if len(text)>10000:raise ValueError('재인식 후보가 10000자를 초과합니다')
    if request.get('voice_activity_ranges')==[] and text:warning='음성 활동이 감지되지 않은 구간의 후보입니다. 발화·소음 또는 감지 누락인지 확인하세요. '+warning
    first=record['offset_ms']+round(chunk['start_frame']*1000/record['sample_rate'])
    return {'text':text,'segments':segments,'start_ms':first,'end_ms':first+duration,'warning':warning,'model':request['model'],'metrics':metrics,'applied':False}


def apply_review(db,job_id,text):
    job=get_job(db,job_id)
    if job['kind']!='asr_review' or job['status']!='done' or not job['result']:raise ValueError('완료한 재인식 후보만 적용할 수 있습니다')
    result=job['result']
    if result.get('applied'):return result
    if not isinstance(text,str)or not text.strip()or len(text)>10000:raise ValueError('원음을 확인한 전사를 입력하세요')
    chunk,record=unchanged(db,job['request']);rows=job['request']['original_segments']
    with db:
        if rows:
            primary=rows[0]['id']
            db.execute('UPDATE jobs SET updated_at=? WHERE id=?',(now(),job_id))
            for row in rows[1:]:db.execute('UPDATE transcripts SET superseded_by=? WHERE id=?',(primary,row['id']))
            tr.edit_segment(db,primary,text,bounds=(result['start_ms'],result['end_ms']))
        else:
            primary=new_id();ref=SourceRef(id=primary+':v1',kind='transcript',session_id=record['session_id'],start_ms=result['start_ms'],end_ms=result['end_ms'])
            db.execute('INSERT INTO transcripts(id,session_id,recording_id,chunk_id,start_ms,end_ms,original_text,text,revision,final,created_at)VALUES(?,?,?,?,?,?,?,?,1,1,?)',(primary,record['session_id'],record['id'],chunk['id'],result['start_ms'],result['end_ms'],'',text.strip(),now()))
            db.execute('INSERT INTO sources(id,ref,text_snapshot)VALUES(?,?,?)',(ref.id,ref.model_dump_json(),text.strip()));index_source(db,ref,text.strip())
        result.update(applied=True,applied_text=text.strip(),transcript_id=primary)
        db.execute('UPDATE jobs SET result=?,updated_at=? WHERE id=?',(json.dumps(result,ensure_ascii=False),now(),job_id))
        if result_utf8_failure(chunk):
            db.execute("UPDATE transcript_ranges SET status='done',error=NULL WHERE id=?",(chunk['id'],))
            finish_recording_job(db,record,repair_failed=True)
    return result


def range_details(db,chunk):
    from .lifecycle import playback_position
    record=tr.get_recording(db,chunk['recording_id'])
    first=record['offset_ms']+round(chunk['start_frame']*1000/record['sample_rate'])
    result={'start_ms':first,'end_ms':first+round((chunk['end_frame']-chunk['start_frame'])*1000/record['sample_rate']),'audio_url':None,'seek_seconds':None}
    try:result['seek_seconds']=playback_position(db,record['id'],first);result['audio_url']='/api/recordings/'+record['id']+'/audio'
    except (KeyError,ValueError,OSError):pass
    return result


def empty_ranges(db,sid):
    return [dict(r)|range_details(db,r)for r in db.execute("SELECT t.* FROM transcript_ranges t JOIN recordings r ON r.id=t.recording_id WHERE r.session_id=? AND r.status!='audio_deleted' AND t.final=1 AND (t.status='done' OR (t.status='failed' AND t.error=?)) AND t.quiet=0 AND t.model IS NOT NULL AND NOT EXISTS(SELECT 1 FROM transcripts s WHERE s.chunk_id=t.id AND s.superseded_by IS NULL) ORDER BY r.offset_ms,t.start_frame",(sid,tr.ASR_RESULT_UTF8_ERROR))]


def public_reviews(db,sid):
    result=[]
    for row in db.execute("SELECT id FROM jobs WHERE session_id=? AND kind='asr_review' ORDER BY created_at DESC",(sid,)):
        job=get_job(db,row[0]);chunk=tr.range_row(db,job['request']['chunk_id']);job.update(range_details(db,chunk));result.append(job)
    return result
