import React,{useEffect,useRef,useState} from 'react';
import PlaybackAudio from './PlaybackAudio';
import type {PlaybackHandle} from './PlaybackAudio';
import {useCloseGuard} from './use-close-guard';
import {api} from './api';
import JobProgress from './JobProgress';
import type {Job} from './types';
import {enforceTranscriptBounds,resolveTranscriptAudio,selectTranscriptRange,transcriptStamp} from './transcript-script';
import type {TranscriptAudio,TranscriptSegment} from './transcript-script';

type Segment=TranscriptSegment;
type Recording={id:string;kind:string;status:string;capture_id?:string;transcription_mode?:'after_stop'|'realtime';transcription_released?:number;gaps:{start_frame:number;end_frame:number}[];sample_rate:number;error:string|null;transcription:{queued:number;running:number;failed:number;interrupted:number;cancelled:number}};
const stamp=(ms:number)=>Math.floor(ms/60000)+':'+String(Math.floor(ms/1000)%60).padStart(2,'0');
type Review=Job<{text:string;warning:string;applied:boolean;applied_text?:string}>&{request:{chunk_id:string;reason:string;original_segments:Segment[]};audio_url:string|null;seek_seconds:number|null;start_ms:number;end_ms:number};
type EmptyRange=Pick<Review,'start_ms'|'end_ms'|'audio_url'|'seek_seconds'>&{id:string};
function ReviewCard({job,refresh}:{job:Review;refresh:()=>Promise<void>}){
  const [text,setText]=useState(job.result?.text||''),[busy,setBusy]=useState(false),[error,setError]=useState('');
  useCloseGuard('재인식 후보 수정',busy||!job.result?.applied&&text!==(job.result?.text||''));
  useEffect(()=>{setText(job.result?.text||'');},[job.result?.text]);
  async function apply(){setBusy(true);setError('');try{await api('/jobs/'+job.id+'/apply-transcript',{method:'POST',body:JSON.stringify({text})});await refresh();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  return <details className="recording-status"><summary>재인식 후보 · {stamp(job.start_ms)}–{stamp(job.end_ms)} · {job.result?.applied?'적용됨':job.status==='done'?'확인 필요':job.status==='queued'?'최초 전사·생성 후 실행':({running:'재인식 중',failed:'실패',cancelled:'취소됨',interrupted:'중단됨'}[job.status]||job.status)}</summary><p>{job.request.reason}</p><JobProgress job={job} onChange={()=>void refresh()}/><p>요청 당시 전사</p><pre className="source-text">{job.request.original_segments.map(s=>s.text).join(' ')||'(빈 전사)'}</pre>{job.audio_url&&<PlaybackAudio controls preload="none" src={job.audio_url} onLoadedMetadata={e=>{if(job.seek_seconds!==null)e.currentTarget.currentTime=job.seek_seconds;}} aria-label="재인식 구간 원음"/>}{job.result&&<><p>{job.result.warning}</p>{job.result.applied?<pre className="source-text">{job.result.applied_text}</pre>:<><label>원음 확인 후 적용할 전사<textarea value={text} onChange={e=>setText(e.target.value)} maxLength={10000}/></label><button disabled={busy||!text.trim()||!job.audio_url} onClick={()=>void apply()}>확인한 전사 적용</button></>}</>}{error&&<p role="alert">{error}</p>}</details>;
}

export function TranscriptScript({sessionId,segments,reviews,refresh,review}:{sessionId:string;segments:Segment[];reviews:Review[];refresh:()=>Promise<void>;review:(chunk:string)=>Promise<void>}){
  const [selected,setSelected]=useState<Segment[]>([]),[editing,setEditing]=useState(false),[drafts,setDrafts]=useState<Record<string,string>>({});
  const [busy,setBusy]=useState<'listen'|'save'|null>(null),[error,setError]=useState('');
  useCloseGuard('전사 수정',busy==='save'||editing&&selected.some(segment=>drafts[segment.id]!==segment.text));
  const [playback,setPlayback]=useState<{clips:TranscriptAudio[];index:number}|null>(null);
  const script=useRef<HTMLParagraphElement>(null),audio=useRef<PlaybackHandle>(null),playRequest=useRef(0);
  const confirmed=segments.filter(s=>s.final),provisional=segments.filter(s=>!s.final);
  useEffect(()=>()=>{playRequest.current++;audio.current?.pause();},[]);
  function choose(rows:Segment[]){
    if(editing||busy==='save')return;
    playRequest.current++;audio.current?.pause();setPlayback(null);setBusy(null);setError('');
    if(rows.length>200){setSelected([]);setError('한 번에 최대 200개 문장을 선택하세요');return;}
    setSelected(rows.map(s=>({...s})));
  }
  function readSelection(){
    const selection=window.getSelection(),root=script.current;
    if(!root||!selection||selection.isCollapsed||!selection.rangeCount)return;
    const range=selection.getRangeAt(0);
    if(!root.contains(range.startContainer)||!root.contains(range.endContainer))return;
    const prefix=range.cloneRange();prefix.selectNodeContents(root);prefix.setEnd(range.startContainer,range.startOffset);
    const start=prefix.toString().length;
    choose(selectTranscriptRange(confirmed,start,start+range.toString().length));
  }
  function clear(){playRequest.current++;audio.current?.pause();setPlayback(null);setSelected([]);setEditing(false);setError('');setBusy(null);}
  async function listen(){
    const request=++playRequest.current;
    audio.current?.pause();setPlayback(null);setError('');setBusy('listen');
    try{
      const clips=await resolveTranscriptAudio(selected,id=>api('/sources/'+encodeURIComponent(id)));
      if(request===playRequest.current)setPlayback({clips,index:0});
    }catch(e){if(request===playRequest.current)setError((e as Error).message);}
    finally{if(request===playRequest.current)setBusy(null);}
  }
  async function save(){
    setBusy('save');setError('');
    try{
      const data=await api<{segments:Segment[]}>('/sessions/'+sessionId+'/transcripts',{method:'PATCH',body:JSON.stringify({segments:selected.map(s=>({id:s.id,expected_revision:s.revision,text:drafts[s.id]}))})});
      setSelected(data.segments);setEditing(false);await refresh();
    }catch(e){setError((e as Error).message);}
    finally{setBusy(null);}
  }
  function advance(index:number){
    audio.current?.pause();
    setPlayback(current=>current?.index===index?(index+1<current.clips.length?{...current,index:index+1}:null):current);
  }
  const clip=playback?.clips[playback.index];
  const selectedRange=selected.length?transcriptStamp(selected[0].start_ms)+'–'+transcriptStamp(selected[selected.length-1].end_ms):'';
  return <div className="transcript-script-view">
    <div className="subheading transcript-heading"><h3>대본</h3><div className="transcript-exports"><a href={'/api/sessions/'+sessionId+'/transcripts/export?format=txt'} download>TXT 내보내기</a><a href={'/api/sessions/'+sessionId+'/transcripts/export?format=md'} download>Markdown 내보내기</a></div></div>
    <p className="transcript-help">문장을 클릭하거나 글을 드래그해 선택한 뒤 듣거나 수정하세요. 한 번에 최대 200개 문장을 선택할 수 있습니다.</p>
    <p className="transcript-help">단어별 시각이 없어 일부 단어를 선택해도 닿은 확정 전사 구간 전체를 재생합니다. Markdown 원음 링크는 앱 실행과 인증이 필요하며, 내보낸 파일에 원음이 포함되지는 않습니다.</p>
    {confirmed.length?<p ref={script} className="transcript-script" aria-label="확정 전사 대본" onPointerUp={readSelection} onKeyUp={readSelection}>{confirmed.map(s=><React.Fragment key={s.id}><span role="button" tabIndex={0} className={selected.some(item=>item.id===s.id)?'selected':''} aria-label={transcriptStamp(s.start_ms)+'–'+transcriptStamp(s.end_ms)+' '+s.text+' 문장 선택'} onClick={()=>{if(window.getSelection()?.isCollapsed!==false)choose([s]);}} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose([s]);}}}>{s.text}</span>{' '}</React.Fragment>)}</p>:<p className="muted">확정 전사가 생기면 대본이 여기에 표시됩니다.</p>}
    {!!provisional.length&&<div className="transcript-provisional" aria-label="잠정 전사"><strong>잠정 전사 · 확정 후 선택할 수 있습니다</strong>{provisional.map(s=><p key={s.id}><small>{transcriptStamp(s.start_ms)}–{transcriptStamp(s.end_ms)}</small> {s.text}</p>)}</div>}
    {!!selected.length&&<aside className="transcript-selection" aria-label="선택 전사 구간">
      <div className="subheading"><strong>선택 구간 · {selectedRange} · {selected.length}개 문장</strong><button disabled={busy==='save'} onClick={clear} aria-label="전사 선택 닫기">×</button></div>
      <p className="transcript-help">표시된 실제 전사 구간을 문장 순서대로 재생합니다. 누락 구간과 녹음 사이의 빈 시간은 건너뜁니다. 선택 당시의 문장과 버전을 유지합니다.</p>
      <div className="transcript-selection-actions"><button disabled={busy!==null} onClick={()=>void listen()}>{busy==='listen'?'원음 확인 중':'선택 구간 듣기'}</button><button disabled={busy!==null||editing} onClick={()=>{setEditing(true);setDrafts(Object.fromEntries(selected.map(s=>[s.id,s.text])));setError('');}}>수정</button></div>
      {clip&&playback&&<div className="transcript-playback"><p role="status">{playback.index+1}/{playback.clips.length} 구간 재생 · {transcriptStamp(selected[playback.index].start_ms)}–{transcriptStamp(selected[playback.index].end_ms)}</p><PlaybackAudio key={clip.id} ref={audio} controls preload="metadata" src={clip.open_url} aria-label="선택 구간 원음" onLoadedMetadata={e=>{const element=e.currentTarget;element.currentTime=clip.seek_seconds;void element.play().catch(()=>setError('재생 버튼을 눌러 원음을 들어보세요'));}} onPlay={e=>{if(enforceTranscriptBounds(e.currentTarget,clip))e.currentTarget.currentTime=clip.seek_seconds;}} onSeeking={e=>{if(enforceTranscriptBounds(e.currentTarget,clip,true))advance(playback.index);}} onTimeUpdate={e=>{if(enforceTranscriptBounds(e.currentTarget,clip))advance(playback.index);}} onEnded={()=>advance(playback.index)} onError={()=>{setPlayback(null);setError('원음을 재생할 수 없습니다');}}/></div>}
      {editing?<div className="transcript-edit-panel"><p>문장 경계와 시각은 유지됩니다. 모든 문장이 함께 저장되며 하나라도 변경되었으면 저장하지 않습니다.</p>{selected.map((s,index)=><label key={s.id} htmlFor={'edit-transcript-'+s.id}>{index+1}. {transcriptStamp(s.start_ms)}–{transcriptStamp(s.end_ms)} · v{s.revision}<textarea id={'edit-transcript-'+s.id} value={drafts[s.id]||''} maxLength={10000} disabled={busy==='save'} onChange={e=>setDrafts({...drafts,[s.id]:e.target.value})}/></label>)}<div className="transcript-selection-actions"><button disabled={busy==='save'} onClick={()=>{setEditing(false);setError('');}}>수정 취소</button><button disabled={busy!==null||selected.some(s=>!drafts[s.id]?.trim())||selected.reduce((sum,s)=>sum+(drafts[s.id]?.length||0),0)>200000} onClick={()=>void save()}>{busy==='save'?'저장 중':'선택 문장 모두 저장'}</button></div></div>:<details><summary>선택한 문장과 원래 인식문 확인</summary>{selected.map(s=><div key={s.id} className="transcript-selected-segment"><small>{transcriptStamp(s.start_ms)}–{transcriptStamp(s.end_ms)} · v{s.revision}</small><p>{s.text}</p>{s.revision>1&&<details><summary>원래 인식문</summary><p>{s.original_text}</p></details>}</div>)}{[...new Map(selected.map(s=>[s.chunk_id,s])).values()].map(s=><button key={s.chunk_id} className="text-button" disabled={reviews.some(j=>['queued','running'].includes(j.status)&&j.request.chunk_id===s.chunk_id)} onClick={()=>void review(s.chunk_id)}>{transcriptStamp(s.start_ms)} 원음 다시 인식</button>)}</details>}
    </aside>}
    {error&&<p role="alert" className="transcript-error">{error}</p>}
  </div>;
}

export default function TranscriptView({sessionId}:{sessionId:string}) {
  const [segments,setSegments]=useState<Segment[]>([]),[records,setRecords]=useState<Recording[]>([]),[reviews,setReviews]=useState<Review[]>([]),[empty,setEmpty]=useState<EmptyRange[]>([]);
  const [error,setError]=useState(''),[busy,setBusy]=useState(false);
  async function refresh(){const data=await api<{transcripts:Segment[];recordings:Recording[];asr_reviews:Review[];empty_transcript_ranges:EmptyRange[]}>('/sessions/'+sessionId+'/events');setSegments(data.transcripts);setRecords(data.recordings);setReviews(data.asr_reviews||[]);setEmpty(data.empty_transcript_ranges||[]);}
  useEffect(()=>{let active=true;const poll=()=>api<{transcripts:Segment[];recordings:Recording[];asr_reviews:Review[];empty_transcript_ranges:EmptyRange[]}>('/sessions/'+sessionId+'/events').then(data=>{if(active){setSegments(data.transcripts);setRecords(data.recordings);setReviews(data.asr_reviews||[]);setEmpty(data.empty_transcript_ranges||[]);}}).catch(e=>{if(active)setError(e.message);});void poll();const timer=setInterval(()=>void poll(),1000);return()=>{active=false;clearInterval(timer);};},[sessionId]);
  async function connect(){setBusy(true);setError('');try{await api('/sessions/'+sessionId+'/recordings',{method:'POST'});await refresh();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  async function retry(id:string){setError('');try{await api('/recordings/'+id+'/transcribe',{method:'POST'});await refresh();}catch(e){setError((e as Error).message);}}
  async function review(chunk:string){setError('');try{await api('/transcript-ranges/'+chunk+'/review',{method:'POST'});await refresh();}catch(e){setError((e as Error).message);}}
  return <section className="card"><div className="subheading"><h2>전사</h2><button disabled={busy||records.some(r=>r.status==='recording')} onClick={()=>void connect()}>{busy?'선택 중':'녹음 파일 연결'}</button></div>
    {records.map(r=><div key={r.id} className="recording-status"><span>{r.kind==='live'?'마이크':'파일'} · {r.status==='audio_deleted'?'원음 없음':r.status==='recording'?'녹음 중':r.status==='interrupted'?'중단':'종료'}</span>
      {r.transcription_mode==='after_stop'&&!r.transcription_released&&<span role="status"> · 녹음 종료 후 전사</span>}
      {(r.transcription.queued+r.transcription.running)>0&&r.transcription_released!==0&&<span role="status"> · 전사 대기 {r.transcription.queued} · 처리 {r.transcription.running}</span>}
      {r.gaps.length>0&&<span> · 누락 {r.gaps.map(g=>transcriptStamp(g.start_frame*1000/r.sample_rate)+'–'+transcriptStamp(g.end_frame*1000/r.sample_rate)).join(', ')}</span>}
      {(r.transcription.failed+r.transcription.interrupted+r.transcription.cancelled>0||r.status==='interrupted'||r.transcription_released===0&&r.status!=='recording')&&r.status!=='audio_deleted'&&<button disabled={records.some(record=>record.status==='recording'&&record.capture_id===r.capture_id)} onClick={()=>void retry(r.id)}>{r.transcription_released===0?'전사 실행':'전사 재시도'}</button>}{r.error&&<p role="alert">{r.error}</p>}</div>)}
    <TranscriptScript key={sessionId} sessionId={sessionId} segments={segments} reviews={reviews} refresh={refresh} review={review}/>
    {empty.map(r=><details key={r.id}><summary>빈 전사 구간 · {stamp(r.start_ms)}–{stamp(r.end_ms)}</summary><p>발화 또는 소음인지 원음을 확인하세요.</p>{r.audio_url&&<PlaybackAudio controls preload="none" src={r.audio_url} onLoadedMetadata={e=>{if(r.seek_seconds!==null)e.currentTarget.currentTime=r.seek_seconds;}} aria-label="빈 전사 구간 원음"/>}<button disabled={!r.audio_url||reviews.some(j=>j.request.chunk_id===r.id&&['queued','running'].includes(j.status))} onClick={()=>void review(r.id)}>원음 다시 인식</button></details>)}
    {reviews.map(job=><ReviewCard key={job.id} job={job} refresh={refresh}/>)}
    {error&&<p role="alert">{error}</p>}
  </section>;
}
