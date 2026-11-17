"""Independent record preservation. This module never removes original data."""
import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import uuid
import wave


@dataclass(frozen=True)
class ExportSelection:
    documents: bool = True
    audio: bool = True
    results: bool = True

    def __post_init__(self):
        if any(type(value) is not bool for value in asdict(self).values()):
            raise ValueError('보존 항목을 확인하세요')


def json_bytes(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()


def identity(path):
    info=Path(path).lstat()
    if stat.S_ISLNK(info.st_mode):raise ValueError('파일 연결이 바뀌었습니다: '+str(path))
    return [info.st_dev,info.st_ino]


def regular_file(path):
    path=Path(path)
    if not path.is_absolute() or path.resolve()!=path:raise ValueError('파일 경로가 바뀌었습니다: '+str(path))
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW),'rb') as handle:
        before=os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode):raise ValueError('일반 파일이 아닙니다: '+str(path))
        digest=hashlib.file_digest(handle,'sha256').hexdigest()
        after=os.fstat(handle.fileno())
    stamp=lambda info:(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)
    if stamp(before)!=stamp(after) or stamp(after)!=stamp(path.lstat()):raise ValueError('파일이 변경되었습니다: '+str(path))
    return {'bytes':after.st_size,'sha256':digest}


def database_fingerprint(db):
    digest=hashlib.sha256()
    for line in db.iterdump():digest.update(line.encode());digest.update(b'\n')
    return digest.hexdigest()


def check_idle(db):
    if db.execute("SELECT 1 FROM jobs WHERE status IN ('queued','running') LIMIT 1").fetchone() or db.execute("SELECT 1 FROM recordings WHERE status='recording' LIMIT 1").fetchone():
        raise ValueError('녹음·다운로드·자료 처리 등 진행 중인 작업을 마친 뒤 다시 시도하세요')
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'native_drafts' in tables:
        for key,value in db.execute('SELECT key,value FROM native_drafts'):
            draft=json.loads(value)
            if draft.get('dirty') is not False:
                raise ValueError('미저장 복구 초안을 확인하고 저장한 뒤 다시 시도하세요')
    if 'native_uploads' in tables and db.execute('SELECT 1 FROM native_uploads LIMIT 1').fetchone():
        raise ValueError('초안 저장을 마친 뒤 다시 시도하세요')


def safe_name(value):
    return re.sub(r'[\x00-\x1f/\\:*?"<>|]','_',str(value)).strip(' .')[:70] or '기록'


def readable(value,level=0):
    if isinstance(value,dict):return '\n'.join('  '*level+str(k)+':\n'+readable(v,level+1) for k,v in value.items())
    if isinstance(value,list):return '\n'.join('  '*level+'-\n'+readable(v,level+1) for v in value)
    return '\n'.join('  '*level+line for line in str('' if value is None else value).split('\n'))


async def prepare_export(db,config,destination,selection):
    from .materials import original_path
    from .lifecycle import playable_path
    from .notebook_pdf import export_pdf
    check_idle(db)
    destination=Path(destination)
    if not destination.is_absolute():raise ValueError('절대 경로의 보존 위치를 선택하세요')
    destination=destination.resolve(strict=True)
    protected=[config.data_dir.resolve(),config.runtime_dir.resolve()]
    for root in protected:
        if destination.is_relative_to(root):raise ValueError('앱 관리 폴더 밖의 보존 위치를 선택하세요')
    required=32*1024**2
    if selection.documents:
        required+=sum(max(0,r[0])*2 for r in db.execute('SELECT size FROM assets'))
        required+=sum((len(r[0])+len(r[1]))*4 for r in db.execute('SELECT text,ink FROM page_document_revisions'))
    if selection.audio:
        for row in db.execute("SELECT id FROM recordings WHERE status!='audio_deleted'"):
            required+=playable_path(db,row['id']).stat().st_size
    if selection.results:
        required+=sum((len(r[0])+len(r[1]))*4 for r in db.execute('SELECT body,evidence FROM artifacts'))
    if shutil.disk_usage(destination).free < required:raise ValueError('선택한 기록을 보존할 저장 공간이 부족합니다. 다른 위치를 선택하세요')
    stamp=database_fingerprint(db)
    folder=destination/('Solasi 보관자료-'+datetime.now().strftime('%Y-%m-%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
    folder.mkdir(mode=0o700)
    receipt={'format':1,'id':uuid.uuid4().hex,'directory':str(folder),'directory_identity':identity(folder),'selection':asdict(selection),
             'database':stamp,'files':[],'sources':[],'records':[]}
    sessions={r['id']:dict(r) for r in db.execute('SELECT * FROM sessions WHERE deleted=0')}
    courses={r['id']:dict(r) for r in db.execute('SELECT * FROM courses')}

    def owner_path(sid=None,cid=None):
        session=sessions.get(sid,{});cid=cid or session.get('course_id')
        course=courses.get(cid,{})
        parts=[]
        if course:parts.append(safe_name(course['title'])+'-'+cid[:8])
        if session:parts.append(safe_name(session['title'])+'-'+sid[:8])
        return Path(*parts) if parts else Path('기타')

    def add(path,category,record,kind='file'):
        info=regular_file(path)
        receipt['files'].append({'path':str(path.relative_to(folder)),'category':category,'kind':kind,**info})
        receipt['records'].append({'id':record,'category':category,'path':str(path.relative_to(folder))})

    def text(relative,value,category,record):
        path=folder/relative;path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        payload=value.encode('utf-8')
        with path.open('xb') as handle:handle.write(payload);handle.flush();os.fsync(handle.fileno())
        if path.read_bytes()!=payload:raise ValueError('텍스트 보존 내용이 일치하지 않습니다')
        add(path,category,record,'text')

    async def copy(source,relative,category,record,expected=None):
        source=source.resolve(strict=True);before=await asyncio.to_thread(regular_file,source)
        if expected and before['sha256']!=expected:raise ValueError('원본 내용이 변경되었습니다: '+source.name)
        target=folder/relative;target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        def transfer():
            with source.open('rb') as src,target.open('xb') as dst:shutil.copyfileobj(src,dst);dst.flush();os.fsync(dst.fileno())
        await asyncio.to_thread(transfer)
        if regular_file(target)!=before or regular_file(source)!=before:raise ValueError('원본 복사 검증 실패: '+source.name)
        receipt['sources'].append({'path':str(source),**before})
        add(target,category,record)
        return target

    if selection.documents:
        for assetrow in db.execute('SELECT * FROM assets').fetchall():
            asset=dict(assetrow);aid=asset['id']
            linked=db.execute('SELECT course_id FROM course_assets WHERE asset_id=? ORDER BY course_id LIMIT 1',(aid,)).fetchone()
            sessionlink=db.execute('SELECT session_id FROM session_assets WHERE asset_id=? ORDER BY session_id LIMIT 1',(aid,)).fetchone()
            base=owner_path(sessionlink[0] if sessionlink else None,linked[0] if linked else None)/'문서'/(safe_name(asset['filename'])+'-'+aid[:8])
            try:source=original_path(db,asset)
            except Exception as exc:
                from fastapi import HTTPException
                if isinstance(exc,HTTPException):raise ValueError(str(exc.detail)) from None
                raise
            original=await copy(source,base/('원본-'+safe_name(asset['filename'])),'documents','asset:'+aid,asset['sha256'])
            pages=db.execute('SELECT d.*,r.text,r.ink FROM page_documents d JOIN page_document_revisions r ON r.document_id=d.id AND r.revision=d.revision WHERE d.asset_id=? ORDER BY d.course_id,d.page',(aid,)).fetchall()
            groups={}
            for row in pages:
                if row['document_sha256']!=asset['sha256']:raise ValueError('이전 원본의 필기를 보존할 원본 파일이 필요합니다: '+asset['filename'])
                groups.setdefault(row['course_id'],[]).append(dict(row))
            for cid,rows in groups.items():
                suffix='-'+cid[:8];notes=[]
                for row in rows:
                    notes.append(f"## {row['page']}쪽 메모\n{row['text']}")
                    for recognition in db.execute("SELECT text,approved_text,status FROM ink_recognitions WHERE document_id=? ORDER BY created_at",(row['id'],)):
                        notes.append(f"### 손글씨 인식 ({recognition['status']})\n{recognition['approved_text'] if recognition['approved_text'] is not None else recognition['text']}")
                text(base/('메모'+suffix+'.txt'),'\n\n'.join(notes)+'\n','documents','page-memos:'+aid+':'+cid)
                if any(json.loads(row['ink']) for row in rows):
                    if asset['kind'] not in ('pdf','png','jpg'):raise ValueError('이 자료의 필기를 PDF로 보존할 수 없습니다: '+asset['filename'])
                    metadata=db.execute('SELECT metadata FROM asset_documents WHERE asset_id=? AND sha256=?',(aid,asset['sha256'])).fetchone()
                    if not metadata:raise ValueError('필기 페이지 정보가 없습니다: '+asset['filename'])
                    count=json.loads(metadata[0])['total_pages'];inks={row['page']:json.loads(row['ink']) for row in rows}
                    payload=[{'page':n,'ink':inks.get(n,[])} for n in range(1,count+1)]
                    output=folder/base/('필기'+suffix+'.pdf')
                    await export_pdf(original,output,payload)
                    add(output,'documents','notebook:'+aid+':'+cid,'verified-pdf')
            if not groups and asset['kind']=='pdf':
                # Unannotated PDFs are already copied without conversion or data loss.
                pass
        for sid,session in sessions.items():
            row=db.execute('SELECT text FROM notes WHERE session_id=? ORDER BY version DESC LIMIT 1',(sid,)).fetchone()
            if row:text(owner_path(sid)/'회차 메모.txt',row['text'],'documents','memo:'+sid)

    audio_paths={}
    if selection.audio:
        for row in db.execute("SELECT * FROM recordings WHERE status!='audio_deleted' ORDER BY started_at").fetchall():
            if row['session_id'] not in sessions:continue
            source=playable_path(db,row['id'])
            target=await copy(source,owner_path(row['session_id'])/'녹음'/(row['id']+source.suffix.lower()),'audio','recording:'+row['id'])
            if target.suffix.lower()=='.wav':
                with wave.open(str(target),'rb') as wav:
                    if wav.getnframes()!=row['stored_frames'] and row['kind']=='live':raise ValueError('녹음 길이가 일치하지 않습니다')
                    if wav.getnframes()<=0 or wav.getframerate()<=0:raise ValueError('재생할 수 없는 녹음입니다')
            else:
                from .runtime import asr_binary
                from .transcription import command
                probe=asr_binary(config.runtime_dir,'ffprobe')
                details=json.loads(await command([probe,'-v','error','-protocol_whitelist','file','-show_entries','format=duration','-of','json','-i',target],30))
                if float(details['format']['duration'])<=0:raise ValueError('재생할 수 없는 녹음입니다')
            audio_paths[row['id']]=target

    if selection.results:
        from .study_memory import export_records
        study=export_records(db)
        if any(study.values()):
            relative=Path('대화와 학습 기억')/'기록.json'
            text(relative,json.dumps(study,ensure_ascii=False,indent=2)+'\n','results','study:all')
            receipt['study']={'path':str(relative),'counts':{k:len(v) for k,v in study.items()}}
        from .transcription import list_transcripts
        for sid,session in sessions.items():
            rows=[r for r in list_transcripts(db,sid) if r['final']]
            if rows:
                lines=[session['title'],'']
                for r in rows:
                    audio=audio_paths.get(r['recording_id']);link=os.path.relpath(audio,folder/owner_path(sid)) if audio else '오디오 미포함'
                    position=''
                    if audio:
                        from .lifecycle import playback_position
                        try:
                            first=playback_position(db,r['recording_id'],r['start_ms'])
                            last=playback_position(db,r['recording_id'],max(r['start_ms'],r['end_ms']-1))+.001
                            position=f' · 파일 {first:.3f}–{last:.3f}초'
                        except ValueError:position=' · 파일 위치 미확정: 원음 누락 구간'
                    lines.extend([f"[회차 {r['start_ms']/1000:.3f}–{r['end_ms']/1000:.3f}초{position}] {link}",r['text'],''])
                text(owner_path(sid)/'전사.txt','\n'.join(lines),'results','transcript:'+sid)
        for row in db.execute('SELECT * FROM artifacts ORDER BY created_at').fetchall():
            if row['session_id'] and row['session_id'] not in sessions:continue
            from .answers import get_artifact
            from .outputs import get_attempt
            saved=get_artifact(db,row['id']);body=saved['body'];metadata=saved['metadata']
            content={'종류':row['kind'],'생성 시각':row['created_at'],'사용자 확인':saved['confirmed'],'내용':body,'출처':saved['evidence']}
            for key in ('model','question'):
                if key in metadata:content[key]=metadata[key]
            attempts=[]
            for attemptrow in db.execute('SELECT id FROM attempts WHERE quiz_id=? ORDER BY created_at',(row['id'],)):
                attempt=get_attempt(db,attemptrow['id'])
                attempts.append({k:attempt[k] for k in ('question_id','submitted_answer','grade','explanation','status')})
            if attempts:content['제출한 답과 평가']=attempts
            text(owner_path(row['session_id'],row['course_id'])/'AI 결과'/(row['kind']+'-'+row['id']+'.txt'),readable(content)+'\n','results','artifact:'+row['id'])
        for row in db.execute('SELECT p.*,j.session_id,j.course_id,j.status,j.error FROM artifact_parts p JOIN jobs j ON j.id=p.job_id WHERE NOT EXISTS(SELECT 1 FROM artifacts a WHERE a.job_id=j.id) ORDER BY j.created_at,p.part_no'):
            if row['session_id'] and row['session_id'] not in sessions:continue
            content={'상태':'미완료 · 완료된 구간만 보존','작업 상태':row['status'],'구간 번호':row['part_no']+1,'내용':json.loads(row['body']),'출처 정보':json.loads(row['metadata'])}
            text(owner_path(row['session_id'],row['course_id'])/'AI 결과'/(row['job_id']+'-부분-'+str(row['part_no'])+'.txt'),readable(content)+'\n','results','partial:'+row['job_id']+':'+str(row['part_no']))
        for row in db.execute('SELECT t.id,v.* FROM terms t JOIN term_versions v ON v.term_id=t.id WHERE v.revision=(SELECT max(revision) FROM term_versions WHERE term_id=t.id)'):
            text(Path('용어')/(row['id']+'.txt'),readable({k:json.loads(row[k]) if k in ('aliases','evidence') else row[k] for k in ('canonical','aliases','explanation','evidence')})+'\n','results','term:'+row['id'])
        for row in db.execute('SELECT key,kind,result,state FROM brain_work WHERE result IS NOT NULL'):
            text(Path('분석 결과')/(hashlib.sha256(row['key'].encode()).hexdigest()[:24]+'.txt'),readable(dict(row))+'\n','results','brain:'+row['key'])

    if database_fingerprint(db)!=stamp:raise ValueError('내보내는 동안 원래 기록이 변경되었습니다. 다시 시도하세요')
    verify_export(receipt,db)
    manifest=folder/'보존 목록.json'
    with manifest.open('xb') as handle:handle.write(json_bytes(receipt));handle.flush();os.fsync(handle.fileno())
    with (folder/'읽어주세요.txt').open('x',encoding='utf-8') as handle:
        handle.write('솔라시 보관자료\nPDF는 필기를 포함한 열람용 최종본입니다. 원래 편집 이력은 포함하지 않습니다.\n보존 선택: '+readable(asdict(selection))+'\n검증된 파일 수: '+str(len(receipt['files']))+'\n')
    receipt['manifest']=str(manifest);receipt['manifest_sha256']=regular_file(manifest)['sha256']
    return receipt


def verify_export(receipt,db=None):
    folder=Path(receipt['directory'])
    if receipt.get('format')!=1 or folder.resolve()!=folder or identity(folder)!=receipt['directory_identity']:raise ValueError('보존 폴더가 바뀌었습니다')
    if db is not None and database_fingerprint(db)!=receipt['database']:raise ValueError('원래 기록이 변경되었습니다. 다시 내보내세요')
    seen=set()
    for item in receipt['files']:
        relative=Path(item['path'])
        if relative.is_absolute() or '..' in relative.parts or str(relative) in seen:raise ValueError('보존 파일 경로 오류')
        seen.add(str(relative));path=folder/relative
        if path.resolve()!=path or regular_file(path)!={'bytes':item['bytes'],'sha256':item['sha256']}:raise ValueError('보존 파일이 손상되거나 변경되었습니다: '+str(relative))
    if len(receipt['records'])!=len(receipt['files']):raise ValueError('보존 목록이 일치하지 않습니다')
    if receipt.get('study'):
        saved=json.loads((folder/receipt['study']['path']).read_text())
        if {k:len(v) for k,v in saved.items()}!=receipt['study']['counts']:raise ValueError('대화·학습 기억의 보존 개수가 일치하지 않습니다')
        if db is not None:
            from .study_memory import export_records
            if saved!=export_records(db):raise ValueError('대화·학습 기억의 보존 내용이 일치하지 않습니다')
    for source in receipt['sources']:
        if regular_file(Path(source['path']))!={'bytes':source['bytes'],'sha256':source['sha256']}:raise ValueError('원본 파일이 변경되었습니다')
    if receipt.get('manifest') and regular_file(Path(receipt['manifest']))['sha256']!=receipt['manifest_sha256']:raise ValueError('보존 목록이 변경되었습니다')
