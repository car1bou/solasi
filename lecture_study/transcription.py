import asyncio
import hashlib
import json
import math
import re
import logging
import sys
import tempfile
import wave
from array import array
from contextlib import nullcontext
from pathlib import Path
from .audio import get_recording,recording_path
from .db import now,new_id
from .models import SourceRef
from .retrieval import index_source

VAD_SHA="2aa269b785eeb53a82983a20501ddf7c1d9c48e33ab63a41391ac6c9f7fb6987"
CHUNK_SECONDS=30
BASE_SHA="60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe"
MODEL_NAME="large-v3-turbo"
MODEL_SHA="1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69"
_verified=set()


def get_asr_terms(db,sid):
    from .db import session
    session(db,sid)
    row=db.execute("SELECT value FROM settings WHERE key=?",("asr_terms:"+sid,)).fetchone()
    return json.loads(row["value"]) if row else []


def asr_prompt(db,sid):
    from .retrieval import list_terms
    names=get_asr_terms(db,sid)
    names += [t['canonical'] for t in list_terms(db,sid)]
    names += [r[0] for r in db.execute('SELECT name FROM participants WHERE session_id=? AND active=1 ORDER BY name',(sid,))]
    selected=[]
    for name in names:
        name=' '.join(name.split())
        if any(ord(c)<32 or ord(c)==127 for c in name):continue
        if name and name not in selected and len(', '.join([*selected,name]).encode('utf-8'))<=200:selected.append(name)
    return ', '.join(selected)


def quiet_cut(samples,rate):
    if len(samples)<rate*CHUNK_SECONDS:return len(samples)
    step=round(rate*.02);first=max(0,len(samples)-rate*6)
    powers=[sum(v*v for v in samples[i:i+step]) for i in range(first,len(samples)-step+1,step)]
    energies=[sum(powers[i:i+10]) for i in range(len(powers)-9)]
    if not energies:return len(samples)
    best=min(range(len(energies)),key=lambda i:(energies[i],-i))
    # shortcut: relative energy finds pauses; use speech VAD boundaries if steady noise hides them.
    return first+(best+5)*step if energies[best]<max(energies)*.01 else len(samples)


def save_asr_terms(db,sid,terms):
    from .db import session
    session(db,sid)
    if not isinstance(terms,list) or any(not isinstance(t,str) or any(ord(c)<32 for c in t) for t in terms):
        raise ValueError("명칭을 쉼표로 구분해 입력하세요")
    terms=list(dict.fromkeys(t.strip() for t in terms if t.strip()))
    check_prompt(", ".join(terms))
    with db:
        db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)",("asr_terms:"+sid,json.dumps(terms,ensure_ascii=False)))
    return terms


def check_prompt(prompt):
    # Byte BPE needs at most one token per UTF-8 byte; stay under native Whisper's 223-token hint budget.
    if len(prompt.encode("utf-8"))>200: raise ValueError("용어가 너무 많습니다. 핵심 명칭 몇 개만 입력하세요")


def range_row(db,ident):
    row=db.execute("SELECT * FROM transcript_ranges WHERE id=?",(ident,)).fetchone()
    if row is None: raise KeyError("전사 구간을 찾을 수 없습니다")
    return dict(row)


def queue_range(db,rid,state,end,stored_end,final):
    if end<=state["start_frame"]: return
    ident=rid+":"+str(state["start_frame"])
    old=db.execute("SELECT * FROM transcript_ranges WHERE id=?",(ident,)).fetchone()
    revision=old["revision"]+1 if old else 1
    quiet=not state["speech"]
    status="done" if final and quiet else "queued"
    db.execute("""INSERT INTO transcript_ranges(id,recording_id,start_frame,end_frame,stored_start,stored_end,final,revision,status,quiet)
       VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET end_frame=excluded.end_frame,stored_end=excluded.stored_end,
       final=excluded.final,revision=excluded.revision,status=excluded.status,quiet=excluded.quiet,error=NULL,model=NULL""",
       (ident,rid,state["start_frame"],end,state["stored_start"],stored_end,int(final),revision,status,int(quiet)))
    if final:
        db.execute("DELETE FROM transcripts WHERE chunk_id=? AND final=0",(ident,))
        state.update(start_frame=end,stored_start=stored_end,quiet_frames=0,speech=False,last_preview=end)


def plan_chunks(db,rid,stopping=False):
    row=get_recording(db,rid)
    if row['transcription_mode']=='after_stop' and not row['transcription_released']:return []
    if row["kind"]!="live":
        return [dict(r) for r in db.execute("SELECT * FROM transcript_ranges WHERE recording_id=? ORDER BY start_frame",(rid,))]
    saved=db.execute("SELECT state,remainder FROM recording_scan WHERE recording_id=?",(rid,)).fetchone()
    state=json.loads(saved["state"]) if saved else dict(last_seq=-1,start_frame=0,stored_start=0,cursor_source=0,cursor_stored=0,quiet_frames=0,speech=False,last_preview=0)
    remainder=saved["remainder"] if saved else b""
    rate=row["sample_rate"];step=round(rate*.02)
    with recording_path(db,rid).open("rb") as handle,db:
        for packet in db.execute("SELECT * FROM pcm_packets WHERE recording_id=? AND seq>? ORDER BY seq",(rid,state["last_seq"])).fetchall():
            if packet["first_frame"]!=state["cursor_source"]:
                queue_range(db,rid,state,state["cursor_source"],state["cursor_stored"],True)
                state.update(start_frame=packet["first_frame"],stored_start=packet["stored_start"],quiet_frames=0,speech=False,last_preview=packet["first_frame"])
                remainder=b""
            handle.seek(44+packet["stored_start"]*2)
            payload=handle.read(packet["frame_count"]*2)
            if len(payload)!=packet["frame_count"]*2: raise OSError("저장된 원음이 짧습니다")
            first=packet["first_frame"]-len(remainder)//2
            stored=packet["stored_start"]-len(remainder)//2
            combined=remainder+payload
            samples=array("h");samples.frombytes(combined)
            if sys.byteorder!="little": samples.byteswap()
            used=len(samples)//step*step
            for offset in range(0,used,step):
                # shortcut: noisy recordings wait up to 30 seconds for final text; previews keep updating.
                quiet=not any(samples[offset:offset+step])
                state["quiet_frames"]=state["quiet_frames"]+step if quiet else 0
                state["speech"] |= not quiet
                end=first+offset+step;stored_end=stored+offset+step
                if end-state["start_frame"]>=rate*CHUNK_SECONDS or (end-state["start_frame"]>=rate*3 and state["quiet_frames"]>=rate*.8):
                    if end-state['start_frame']>=rate*CHUNK_SECONDS:
                        handle.seek(44+state['stored_start']*2)
                        window=array('h');window.frombytes(handle.read((stored_end-state['stored_start'])*2))
                        if sys.byteorder!='little':window.byteswap()
                        cut=quiet_cut(window,rate)
                        boundary=state['start_frame']+cut;stored_boundary=state['stored_start']+cut
                        queue_range(db,rid,state,boundary,stored_boundary,True)
                        state['speech']=any(window[cut:])
                    else:queue_range(db,rid,state,end,stored_end,True)
            remainder=combined[used*2:]
            state.update(last_seq=packet["seq"],cursor_source=packet["first_frame"]+packet["frame_count"],cursor_stored=packet["stored_start"]+packet["frame_count"])
            if state["cursor_source"]-state["start_frame"]>=rate*10 and state["cursor_source"]-state["last_preview"]>=rate*10:
                queue_range(db,rid,state,state["cursor_source"],state["cursor_stored"],False)
                state["last_preview"]=state["cursor_source"]
        if stopping:
            if remainder:
                tail=array("h");tail.frombytes(remainder)
                state["speech"] |= any(tail)
            queue_range(db,rid,state,state["cursor_source"],state["cursor_stored"],True)
            remainder=b""
        db.execute("INSERT OR REPLACE INTO recording_scan VALUES (?,?,?)",(rid,json.dumps(state),remainder))
    return [dict(r) for r in db.execute("SELECT * FROM transcript_ranges WHERE recording_id=? ORDER BY start_frame",(rid,))]


def parse_segments(body,duration_ms,start_ms=0):
    if not isinstance(body,dict) or not isinstance(body.get("transcription"),list): raise ValueError("전사 JSON이 유효하지 않습니다")
    result=[]
    for raw in body["transcription"]:
        if not isinstance(raw,dict) or not isinstance(raw.get("offsets"),dict) or not isinstance(raw.get("text"),str): raise ValueError("전사 문장이 유효하지 않습니다")
        first,last=raw["offsets"].get("from"),raw["offsets"].get("to")
        if type(first) is not int or type(last) is not int or first<0 or last<first: raise ValueError("전사 시각이 유효하지 않습니다")
        text=raw["text"].strip()
        first,last=min(first,duration_ms),min(last,duration_ms)
        if text and last>first: result.append(dict(start_ms=start_ms+first,end_ms=start_ms+last,text=text))
    return result


async def stop_process(process):
    if process.returncode is not None:return
    async def close():
        process.terminate()
        try:await asyncio.wait_for(process.communicate(),2)
        except TimeoutError:process.kill();await process.communicate()
    cleanup=asyncio.create_task(close());cancelled=False
    # Reap the owned process before propagating another packet/parent cancellation.
    while not cleanup.done():
        try:await asyncio.shield(cleanup)
        except asyncio.CancelledError:cancelled=True
    await cleanup
    if cancelled:raise asyncio.CancelledError


async def command(argv,timeout=120):
    process=await asyncio.create_subprocess_exec(*map(str,argv),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    try:
        stdout,stderr=await asyncio.wait_for(process.communicate(),timeout)
        if process.returncode: raise ValueError("음성 처리 실패: 엔진 또는 입력 형식을 확인하세요")
        return stdout
    finally:
        await stop_process(process)


def engine_paths(runtime):
    runtime=Path(runtime)
    if (runtime/'asr/receipt.json').is_file():
        from .runtime import component_status
        if not component_status('asr',runtime)['ready']:raise ValueError('전사 엔진 파일 검증 실패')
    ffmpeg=runtime/("asr/bin/ffmpeg" if (runtime/"asr/receipt.json").is_file() else "ffmpeg/bin/ffmpeg");whisper=runtime/("asr/bin/whisper-cli" if (runtime/"asr/receipt.json").is_file() else "build/whisper/bin/whisper-cli");model=runtime/"models"/("ggml-"+MODEL_NAME+".bin")
    if not all(p.is_file() for p in (ffmpeg,whisper,model)): raise ValueError("전사 엔진과 "+MODEL_NAME+" 모델을 준비하세요")
    verify_model(model,MODEL_SHA)
    return ffmpeg,whisper,model


def verify_model(path,expected):
    if not path.is_file(): raise ValueError("전사·VAD 모델을 준비하세요")
    stamp=(str(path),path.stat().st_size,path.stat().st_mtime_ns,expected)
    if stamp not in _verified:
        digest=hashlib.sha256()
        with path.open("rb") as handle:
            while chunk:=handle.read(1024*1024): digest.update(chunk)
        if digest.hexdigest()!=expected: raise ValueError("전사 모델 파일 검증 실패")
        _verified.add(stamp)


async def transcribe_range(input_wav,start_ms,prompt,runtime_dir,*,preview=False,padding_ms=30,vad_enabled=True,min_speech_ms=250):
    check_prompt(prompt)
    ffmpeg,whisper,model=await asyncio.to_thread(engine_paths,runtime_dir)
    vad=Path(runtime_dir)/"models/ggml-silero-v6.2.0.bin"
    if vad_enabled:await asyncio.to_thread(verify_model,vad,VAD_SHA)
    with tempfile.TemporaryDirectory(prefix="lecture-asr-") as temp:
        clip=Path(temp)/"clip.wav";prefix=Path(temp)/"result"
        await command([ffmpeg,"-nostdin","-v","error","-y","-i",input_wav,"-ac","1","-ar","16000","-c:a","pcm_s16le",clip])
        with wave.open(str(clip)) as wav: duration=round(wav.getnframes()*1000/wav.getframerate())
        if not duration: return []
        argv=[whisper,"-m",model,"-f",clip,"-l","ko","-oj","-of",prefix,"-np"]
        if vad_enabled:argv += ["--vad","-vm",vad,"--vad-speech-pad-ms",str(padding_ms),"--vad-min-speech-duration-ms",str(min_speech_ms)]
        if preview:argv += ["-bs","1","-bo","1","-nf"]
        if prompt.strip(): argv+=["--prompt",prompt]
        await command(argv)
        try: body=json.loads(prefix.with_suffix(".json").read_text())
        except (OSError,json.JSONDecodeError): raise ValueError("전사 결과를 읽을 수 없습니다") from None
        return parse_segments(body,duration,start_ms)



def parse_activity(output,duration_ms):
    text=output.decode('utf-8');count=re.search(r'Detected (\d+) speech segments:',text)
    rows=re.findall(r'Speech segment (\d+): start = (\d+\.\d+), end = (\d+\.\d+)',text)
    if len(text)>65536 or not count or int(count[1])>4096:raise ValueError('음성 활동 출력 크기가 유효하지 않습니다')
    if [int(r[0])for r in rows]!=list(range(int(count[1]))):raise ValueError('음성 활동 출력 형식이 유효하지 않습니다')
    result=[]
    for _,a,b in rows:
        a,b=round(float(a)*10),round(float(b)*10)  # This pinned native utility returns centiseconds.
        if not 0<=a<b<=duration_ms+40 or result and a<result[-1]['end_ms']:raise ValueError('음성 활동 시각이 원음을 벗어납니다')
        if a<duration_ms:result.append({'start_ms':a,'end_ms':min(b,duration_ms)})
    return result


async def speech_activity(input_wav,runtime_dir):
    runtime=Path(runtime_dir);receipt=runtime/'asr/receipt.json';name='bin/whisper-vad-speech-segments'
    utility=runtime/('asr/'+name if receipt.is_file()else'build/whisper/'+name)
    if not utility.is_file():return None
    if receipt.is_file():
        from .runtime import matches
        expected=json.loads(receipt.read_text())['files'].get(name)
        if not expected:return None
        if not matches(utility,expected):raise ValueError('음성 활동 검사 파일 검증 실패')
    ffmpeg,_,_=await asyncio.to_thread(engine_paths,runtime)
    vad=runtime/'models/ggml-silero-v6.2.0.bin';await asyncio.to_thread(verify_model,vad,VAD_SHA)
    with tempfile.TemporaryDirectory(prefix='lecture-activity-')as temp:
        clip=Path(input_wav)
        try:
            with wave.open(str(clip))as handle:normalize=(handle.getnchannels(),handle.getsampwidth(),handle.getframerate())!=(1,2,16000)
        except (wave.Error,EOFError):normalize=True
        if normalize:
            clip=Path(temp)/'clip.wav'
            await command([ffmpeg,'-nostdin','-v','error','-y','-i',input_wav,'-ac','1','-ar','16000','-c:a','pcm_s16le',clip])
        with wave.open(str(clip))as handle:duration=round(handle.getnframes()*1000/handle.getframerate())
        output=await command([utility,'-vm',vad,'-f',clip,'-np','-t','1','-vp','0'],timeout=30)
        return parse_activity(output,duration)


def accept_transcription(db,recording_id,chunk_id,revision,final,segments):
    chunk=range_row(db,chunk_id);record=get_recording(db,recording_id)
    if chunk["recording_id"]!=recording_id: raise ValueError("전사 소속이 다릅니다")
    if chunk["final"] and not final: return False
    if chunk["status"]=="done" or chunk["revision"]!=revision or bool(chunk["final"])!=bool(final): return False
    duration=round((chunk["end_frame"]-chunk["start_frame"])*1000/record["sample_rate"])
    start=record["offset_ms"]+round(chunk["start_frame"]*1000/record["sample_rate"])
    checked=[]
    for segment in segments:
        a,b,text=segment["start_ms"],segment["end_ms"],segment["text"].strip()
        if type(a) is not int or type(b) is not int or not 0<=a<b<=duration or not text: raise ValueError("전사 구간이 원음 범위를 벗어납니다")
        checked.append((a+start,b+start,text))
    with db:
        db.execute("DELETE FROM transcripts WHERE chunk_id=?",(chunk_id,))
        for a,b,text in checked:
            ident=new_id()
            db.execute("INSERT INTO transcripts(id,session_id,recording_id,chunk_id,start_ms,end_ms,original_text,text,revision,final,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",(ident,record["session_id"],recording_id,chunk_id,a,b,text,text,1,int(final),now()))
            if final:
                ref=SourceRef(id=ident+":v1",kind="transcript",session_id=record["session_id"],start_ms=a,end_ms=b)
                db.execute("INSERT INTO sources(id,ref,text_snapshot) VALUES (?,?,?)",(ref.id,ref.model_dump_json(),text))
                index_source(db,ref,text)
        db.execute("UPDATE transcript_ranges SET status='done',error=NULL WHERE id=?",(chunk_id,))
    return True


def list_transcripts(db,sid):
    return [dict(row) for row in db.execute("SELECT * FROM transcripts WHERE session_id=? AND superseded_by IS NULL ORDER BY start_ms,id",(sid,))]


class TranscriptConflict(ValueError):
    pass


def edit_segment(db,ident,text,*,bounds=None,expected_revision=None):
    row=db.execute("SELECT * FROM transcripts WHERE id=?",(ident,)).fetchone()
    if row is None: raise KeyError("전사를 찾을 수 없습니다")
    if row["superseded_by"]:raise ValueError("새 버전으로 대체된 전사입니다")
    if not row["final"]: raise ValueError("확정 전사만 수정할 수 있습니다")
    if expected_revision is not None and (type(expected_revision)is not int or expected_revision<1):raise ValueError('전사 버전을 확인하세요')
    if expected_revision is not None and row['revision']!=expected_revision:raise TranscriptConflict('선택한 전사가 변경되었습니다. 수정 내용을 복사한 뒤 다시 선택하세요')
    if not isinstance(text,str) or not text.strip() or len(text)>10000: raise ValueError("전사 문장을 입력하세요")
    start,end=bounds or (row['start_ms'],row['end_ms'])
    chunk=range_row(db,row['chunk_id']);record=get_recording(db,row['recording_id'])
    if not chunk['final'] or chunk['recording_id']!=record['id'] or record['session_id']!=row['session_id']:raise ValueError('확정 전사 소속을 확인하세요')
    first=record['offset_ms']+round(chunk['start_frame']*1000/record['sample_rate'])
    last=record['offset_ms']+round(chunk['end_frame']*1000/record['sample_rate'])
    if type(start)is not int or type(end)is not int or not first<=start<end<=last:raise ValueError('전사 구간이 원음 범위를 벗어납니다')
    revision=row["revision"]+1
    ref=SourceRef(id=ident+":v"+str(revision),kind="transcript",session_id=row["session_id"],version=revision,start_ms=start,end_ms=end)
    with db if not db.in_transaction else nullcontext():
        if not db.execute("UPDATE transcripts SET text=?,revision=?,start_ms=?,end_ms=? WHERE id=? AND revision=?",(text.strip(),revision,start,end,ident,row['revision'])).rowcount:raise TranscriptConflict('전사가 변경되었습니다. 다시 선택하세요')
        db.execute("INSERT INTO sources(id,ref,text_snapshot) VALUES (?,?,?)",(ref.id,ref.model_dump_json(),text.strip()))
        index_source(db,ref,text.strip())
    return dict(db.execute("SELECT * FROM transcripts WHERE id=?",(ident,)).fetchone())


def edit_segments(db,sid,segments):
    from .db import session
    session(db,sid)
    if not isinstance(segments,list) or not 1<=len(segments)<=200:raise ValueError('한 번에 1~200개 확정 문장을 수정하세요')
    if len({s['id'] for s in segments})!=len(segments):raise ValueError('같은 문장을 중복 수정할 수 없습니다')
    if any(not isinstance(s['text'],str) for s in segments) or sum(len(s['text']) for s in segments)>200000:raise ValueError('선택한 전사는 전체 200,000자까지 수정할 수 있습니다')
    with db:
        if not db.in_transaction:db.execute('BEGIN IMMEDIATE')
        for item in segments:
            row=db.execute('SELECT session_id FROM transcripts WHERE id=?',(item['id'],)).fetchone()
            if not row or row['session_id']!=sid:raise ValueError('선택한 회차의 전사만 수정할 수 있습니다')
        return [edit_segment(db,item['id'],item['text'],expected_revision=item['expected_revision']) for item in segments]


def export_transcript(db,sid,format,base_url):
    from .db import session
    from .lifecycle import resolve_source
    from html import escape
    owner=session(db,sid)
    rows=[row for row in list_transcripts(db,sid) if row['final']]
    if format=='txt':return owner['title']+'\n\n'+' '.join(row['text'] for row in rows)+'\n'
    if format!='md':raise ValueError('TXT 또는 Markdown 형식을 선택하세요')
    def safe(text):
        return re.sub(r'([\\`*_{}\[\]()#+.!|>~-])',r'\\\1',escape(text,quote=False))
    def stamp(ms):
        return f'{ms//60000}:{ms//1000%60:02}.{ms%1000:03}'
    lines=['# '+safe(owner['title']),'',
        '> 원음 링크는 로컬 앱 실행 및 해당 앱의 인증이 필요합니다. 현재 포트가 바뀌거나 원음이 삭제되면 열리지 않습니다. 이 파일에는 원음이 포함되지 않으며 다른 기기에서 그대로 재생되는 오디오 묶음이 아닙니다.',
        '> 시각은 확정 전사 구간 기준입니다. 단어별 시각은 제공하지 않습니다.','']
    for row in rows:
        ident=row['id']+':v'+str(row['revision'])
        source=resolve_source(db,SourceRef(id=ident,kind='transcript'))
        link='원음 없음'
        if source['open_url'] and source['seek_seconds'] is not None and source['end_seconds'] is not None:
            positions=','.join(f'{value:.9f}'.rstrip('0').rstrip('.') for value in (source['seek_seconds'],source['end_seconds']))
            url=base_url.rstrip('/')+source['open_url']+'#t='+positions
            link='[원음 듣기]('+url+')'
        lines.extend([f"**{stamp(row['start_ms'])}–{stamp(row['end_ms'])}** · `{ident}` · {link}",'',safe(row['text']),''])
    return '\n'.join(lines)


def transcription_status(db,rid):
    result={"queued":0,"running":0,"failed":0,"done":0,"interrupted":0,"cancelled":0}
    for row in db.execute("SELECT status,count(*) n FROM transcript_ranges WHERE recording_id=? GROUP BY status",(rid,)):
        result[row["status"]]=row["n"]
    return result


async def process_pending(db,rid,runtime_dir,retry=False):
    if retry:
        with db: db.execute("UPDATE transcript_ranges SET status='queued',error=NULL WHERE recording_id=? AND status IN ('failed','interrupted','cancelled')",(rid,))
    while chunk:=db.execute("SELECT * FROM transcript_ranges WHERE recording_id=? AND status='queued' ORDER BY final DESC,start_frame LIMIT 1",(rid,)).fetchone():
        await process_chunk(db,dict(chunk),runtime_dir)
    return transcription_status(db,rid)


async def process_chunk(db,chunk,runtime_dir):
    record=get_recording(db,chunk["recording_id"])
    prompt=asr_prompt(db,record["session_id"])
    with db: db.execute("UPDATE transcript_ranges SET status='running',prompt=?,model=NULL WHERE id=? AND revision=?",(prompt,chunk["id"],chunk["revision"]))
    try:
        with tempfile.TemporaryDirectory(prefix="lecture-range-") as temp:
            clip=Path(temp)/"input.wav"
            await range_clip(db,record,chunk,clip,runtime_dir)
            with wave.open(str(clip)) as source:
                samples=array("h");samples.frombytes(source.readframes(source.getnframes()))
            if sys.byteorder!="little": samples.byteswap()
            quiet=not any(samples)
            with db: db.execute("UPDATE transcript_ranges SET model=? WHERE id=? AND revision=?",(None if quiet else MODEL_NAME,chunk["id"],chunk["revision"]))
            options={}
            if not chunk['final']:options['preview']=True
            if chunk['final'] or record['source_frames']>=record['sample_rate']*CHUNK_SECONDS:options['padding_ms']=1000 if chunk['final']and(record['transcription_mode']=='after_stop'or record['kind']=='file')else 200
            segments=[] if quiet else await transcribe_range(clip,0,prompt,runtime_dir,**options)
            duration=round((chunk["end_frame"]-chunk["start_frame"])*1000/record["sample_rate"])
            segments=[{**segment,"end_ms":min(segment["end_ms"],duration)} for segment in segments if segment["start_ms"]<duration]
            accepted=accept_transcription(db,record["id"],chunk["id"],chunk["revision"],bool(chunk["final"]),segments)
            if accepted and chunk['final'] and not quiet:
                try:return await speech_activity(clip,runtime_dir)
                except Exception as exc:logging.getLogger(__name__).warning('Optional voice activity scan skipped: %s',exc)
    except asyncio.CancelledError:
        with db: db.execute("UPDATE transcript_ranges SET status='interrupted' WHERE id=? AND revision=? AND status='running'",(chunk["id"],chunk["revision"]))
        raise
    except Exception as exc:
        with db: db.execute("UPDATE transcript_ranges SET status='failed',error=? WHERE id=? AND revision=?",(str(exc)[:300],chunk["id"],chunk["revision"]))

async def register_audio(db,sid,path,runtime_dir):
    from fractions import Fraction
    from .db import data_dir,session
    session(db,sid)
    if db.execute("SELECT 1 FROM recordings WHERE session_id=? AND status='recording'",(sid,)).fetchone():raise ValueError('녹음을 종료한 후 파일을 연결하세요')
    path=Path(path).resolve(strict=True)
    if not path.is_file() or path.is_relative_to(data_dir(db).resolve()): raise ValueError("외부 오디오 파일을 선택하세요")
    before=path.stat()
    if not 0<before.st_size<=2*1024**3: raise ValueError("오디오는 2 GiB 이하만 처리할 수 있습니다")
    with path.open("rb") as handle: header=handle.read(32)
    recognized=(header[:4] in (b"fLaC",b"OggS",b"caff",b"FORM",bytes.fromhex("1a45dfa3")) or
                header.startswith(b"ID3") or (header[:4]==b"RIFF" and header[8:12]==b"WAVE") or
                header[4:8]==b"ftyp" or (len(header)>1 and header[0]==255 and header[1]&224==224))
    if not recognized: raise ValueError("지원되는 오디오 형식이 아닙니다")
    probe=Path(runtime_dir)/("asr/bin/ffprobe" if (Path(runtime_dir)/"asr/receipt.json").is_file() else "ffmpeg/bin/ffprobe")
    if not probe.is_file(): raise ValueError("FFmpeg를 준비하세요")
    output=await command([probe,"-v","error","-protocol_whitelist","file","-select_streams","a:0","-show_entries",
          "stream=sample_rate,channels,duration,duration_ts,time_base:format=duration","-of","json","-i",path],30)
    try:
        body=json.loads(output);stream=body["streams"][0];rate=int(stream["sample_rate"]);channels=int(stream["channels"])
        if "duration_ts" in stream and "time_base" in stream:
            duration=float(int(stream["duration_ts"])*Fraction(stream["time_base"]))
        else: duration=float(stream.get("duration",body.get("format",{}).get("duration")))
        if not 8000<=rate<=384000 or not 1<=channels<=64 or not math.isfinite(duration) or duration<=0: raise ValueError()
    except (ValueError,TypeError,KeyError,IndexError): raise ValueError("유효한 오디오 스트림과 길이가 필요합니다") from None
    digest=await asyncio.to_thread(file_hash,path)
    after=path.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns): raise ValueError("선택 중 파일이 변경되었습니다")
    if db.execute("SELECT 1 FROM recordings WHERE session_id=? AND status='recording'",(sid,)).fetchone():raise ValueError('녹음을 종료한 후 파일을 연결하세요')
    ident=new_id();frames=round(duration*rate)
    if frames>2**53-1: raise ValueError("오디오 길이가 너무 깁니다")
    boundaries=await file_boundaries(path,frames,rate,runtime_dir) if frames>rate*CHUNK_SECONDS else [frames]
    after=path.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('선택 중 파일이 변경되었습니다')
    if db.execute("SELECT 1 FROM recordings WHERE session_id=? AND status='recording'",(sid,)).fetchone():raise ValueError('녹음을 종료한 후 파일을 연결하세요')
    end=db.execute("SELECT max(offset_ms+source_frames*1000/sample_rate) FROM recordings WHERE session_id=?",(sid,)).fetchone()[0] or 0
    with db:
        db.execute("""INSERT INTO recordings(id,session_id,kind,sample_rate,status,started_at,ended_at,offset_ms,stored_frames,source_frames,external_path)
             VALUES (?,?,'file',?,'stopped',?,?,?,?,?,?)""",(ident,sid,rate,now(),now(),round(end),frames,frames,str(path)))
        db.execute("INSERT INTO audio_files VALUES (?,?,?,?,?,?,?)",(ident,path.name,before.st_size,before.st_mtime_ns,digest,channels,round(duration*1000)))
        start=0
        for last in boundaries:
            db.execute("INSERT INTO transcript_ranges(id,recording_id,start_frame,end_frame,stored_start,stored_end,final,revision,status) VALUES (?,?,?,?,?,?,1,1,'queued')",
                       (ident+":"+str(start),ident,start,last,start,last))
            start=last
    return ident


async def file_boundaries(path,frames,rate,runtime):
    runtime=Path(runtime);managed=(runtime/'asr/receipt.json').is_file()
    if managed:
        from .runtime import component_status
        if not (await asyncio.to_thread(component_status,'asr',runtime))['ready']:raise ValueError('전사 엔진 파일 검증 실패')
    ffmpeg=runtime/('asr/bin/ffmpeg' if managed else 'ffmpeg/bin/ffmpeg')
    if not ffmpeg.is_file():raise ValueError('FFmpeg를 준비하세요')
    process=await asyncio.create_subprocess_exec(str(ffmpeg),'-nostdin','-v','error','-protocol_whitelist','file','-i',str(path),'-map','0:a:0','-ac','1','-ar','16000','-f','s16le','pipe:1',stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
    buffer=b'';cursor=0;boundaries=[];capacity=16000*CHUNK_SECONDS*2
    try:
        while True:
            try:buffer+=await asyncio.wait_for(process.stdout.readexactly(capacity-len(buffer)),30)
            except asyncio.IncompleteReadError as exc:buffer+=exc.partial
            if not buffer:break
            if len(buffer)%2:raise ValueError('오디오 PCM 길이가 유효하지 않습니다')
            samples=array('h');samples.frombytes(buffer)
            if sys.byteorder!='little':samples.byteswap()
            cut=quiet_cut(samples,16000);cursor+=cut;buffer=buffer[cut*2:]
            boundary=round(cursor*rate/16000)
            if boundary<frames:boundaries.append(boundary)
        if await asyncio.wait_for(process.wait(),30) or abs(cursor/16000-frames/rate)>1:raise ValueError('오디오 길이를 확인할 수 없습니다')
        return [*boundaries,frames]
    except TimeoutError:raise ValueError('오디오 분할 제한 시간 초과') from None
    finally:
        await stop_process(process)


def file_hash(path):
    digest=hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk:=handle.read(1024*1024): digest.update(chunk)
    return digest.hexdigest()


def external_audio_path(db,record):
    saved=db.execute("SELECT * FROM audio_files WHERE recording_id=?",(record["id"],)).fetchone()
    if saved is None: raise ValueError("오디오 연결 정보를 찾을 수 없습니다")
    path=Path(record["external_path"])
    try: stat=path.stat()
    except OSError: raise ValueError("연결된 오디오 파일을 읽을 수 없습니다") from None
    if (stat.st_size,stat.st_mtime_ns)!=(saved["size"],saved["mtime_ns"]): raise ValueError("오디오 원본이 변경되었습니다. 다시 연결하세요")
    return path


async def external_clip(db,record,chunk,clip,runtime_dir):
    source=external_audio_path(db,record)
    ffmpeg,_,_=await asyncio.to_thread(engine_paths,runtime_dir)
    start=chunk["start_frame"]/record["sample_rate"];duration=(chunk["end_frame"]-chunk["start_frame"])/record["sample_rate"]
    await command([ffmpeg,"-nostdin","-v","error","-y","-protocol_whitelist","file","-ss",str(start),"-i",source,
                  "-t",str(duration),"-map","0:a:0","-ac","1","-ar","16000","-c:a","pcm_s16le",clip])
    external_audio_path(db,record)


async def range_clip(db,record,chunk,clip,runtime_dir):
    if record["status"]=="audio_deleted":raise ValueError("원음이 삭제되거나 연결 해제되었습니다")
    if record["kind"]=="live":
        with wave.open(str(recording_path(db,record["id"]))) as source:
            source.setpos(chunk["stored_start"]);payload=source.readframes(chunk["stored_end"]-chunk["stored_start"])
        if len(payload)!=(chunk["stored_end"]-chunk["stored_start"])*2: raise OSError("원음 구간이 짧습니다")
        with wave.open(str(clip),"wb") as out:
            out.setnchannels(1);out.setsampwidth(2);out.setframerate(record["sample_rate"]);out.writeframes(payload)
    else:
        await external_clip(db,record,chunk,clip,runtime_dir)
