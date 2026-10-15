import React,{useEffect,useState} from 'react';
import SourceLink from './SourceLink';
import {api} from './api';
import JobProgress from './JobProgress';
import type {Job} from './types';

type Segment={id:string;chunk_id:string;start_ms:number;end_ms:number;text:string;original_text:string;revision:number;final:number};
type Recording={id:string;kind:string;status:string;capture_id?:string;transcription_mode?:'after_stop'|'realtime';transcription_released?:number;gaps:{start_frame:number;end_frame:number}[];sample_rate:number;error:string|null;transcription:{queued:number;running:number;failed:number;interrupted:number;cancelled:number}};
const stamp=(ms:number)=>Math.floor(ms/60000)+':'+String(Math.floor(ms/1000)%60).padStart(2,'0');
type Review=Job<{text:string;warning:string;applied:boolean;applied_text?:string}>&{request:{chunk_id:string;reason:string;original_segments:Segment[]};audio_url:string|null;seek_seconds:number|null;start_ms:number;end_ms:number};
type EmptyRange=Pick<Review,'start_ms'|'end_ms'|'audio_url'|'seek_seconds'>&{id:string};
function ReviewCard({job,refresh}:{job:Review;refresh:()=>Promise<void>}){
  const [text,setText]=useState(job.result?.text||''),[busy,setBusy]=useState(false),[error,setError]=useState('');
  useEffect(()=>{setText(job.result?.text||'');},[job.result?.text]);
  async function apply(){setBusy(true);setError('');try{await api('/jobs/'+job.id+'/apply-transcript',{method:'POST',body:JSON.stringify({text})});await refresh();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  return <details className="recording-status"><summary>재인식 후보 · {stamp(job.start_ms)}–{stamp(job.end_ms)} · {job.result?.applied?'적용됨':job.status==='done'?'확인 필요':job.status==='queued'?'최초 전사·생성 후 실행':({running:'재인식 중',failed:'실패',cancelled:'취소됨',interrupted:'중단됨'}[job.status]||job.status)}</summary><p>{job.request.reason}</p><JobProgress job={job} onChange={()=>void refresh()}/><p>요청 당시 전사</p><pre className="source-text">{job.request.original_segments.map(s=>s.text).join(' ')||'(빈 전사)'}</pre>{job.audio_url&&<audio controls preload="none" src={job.audio_url} onLoadedMetadata={e=>{if(job.seek_seconds!==null)e.currentTarget.currentTime=job.seek_seconds;}} aria-label="재인식 구간 원음"/>}{job.result&&<><p>{job.result.warning}</p>{job.result.applied?<pre className="source-text">{job.result.applied_text}</pre>:<><label>원음 확인 후 적용할 전사<textarea value={text} onChange={e=>setText(e.target.value)} maxLength={10000}/></label><button disabled={busy||!text.trim()||!job.audio_url} onClick={()=>void apply()}>확인한 전사 적용</button></>}</>}{error&&<p role="alert">{error}</p>}</details>;
}
export default function TranscriptView({sessionId}:{sessionId:string}) {
  const [segments,setSegments]=useState<Segment[]>([]),[records,setRecords]=useState<Recording[]>([]),[reviews,setReviews]=useState<Review[]>([]),[empty,setEmpty]=useState<EmptyRange[]>([]);
  const [error,setError]=useState(''),[busy,setBusy]=useState(false);
  const [editing,setEditing]=useState<string|null>(null),[text,setText]=useState('');
  async function refresh(){const data=await api<{transcripts:Segment[];recordings:Recording[];asr_reviews:Review[];empty_transcript_ranges:EmptyRange[]}>('/sessions/'+sessionId+'/events');setSegments(data.transcripts);setRecords(data.recordings);setReviews(data.asr_reviews||[]);setEmpty(data.empty_transcript_ranges||[]);}
  useEffect(()=>{let active=true;const poll=()=>api<{transcripts:Segment[];recordings:Recording[];asr_reviews:Review[];empty_transcript_ranges:EmptyRange[]}>('/sessions/'+sessionId+'/events').then(data=>{if(active){setSegments(data.transcripts);setRecords(data.recordings);setReviews(data.asr_reviews||[]);setEmpty(data.empty_transcript_ranges||[]);}}).catch(e=>{if(active)setError(e.message);});void poll();const timer=setInterval(()=>void poll(),1000);return()=>{active=false;clearInterval(timer);};},[sessionId]);
  async function connect(){setBusy(true);setError('');try{await api('/sessions/'+sessionId+'/recordings',{method:'POST'});await refresh();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  async function retry(id:string){setError('');try{await api('/recordings/'+id+'/transcribe',{method:'POST'});await refresh();}catch(e){setError((e as Error).message);}}
  async function review(chunk:string){setError('');try{await api('/transcript-ranges/'+chunk+'/review',{method:'POST'});await refresh();}catch(e){setError((e as Error).message);}}
  async function save(){setError('');try{await api('/transcripts/'+editing,{method:'PATCH',body:JSON.stringify({text})});setEditing(null);await refresh();}catch(e){setError((e as Error).message);}}
  return <section className="card"><div className="subheading"><h2>전사</h2><button disabled={busy||records.some(r=>r.status==='recording')} onClick={()=>void connect()}>{busy?'선택 중':'녹음 파일 연결'}</button></div>
    {records.map(r=><div key={r.id} className="recording-status"><span>{r.kind==='live'?'마이크':'파일'} · {r.status==='audio_deleted'?'원음 없음':r.status==='recording'?'녹음 중':r.status==='interrupted'?'중단':'종료'}</span>
      {r.transcription_mode==='after_stop'&&!r.transcription_released&&<span role="status"> · 녹음 종료 후 전사</span>}
      {(r.transcription.queued+r.transcription.running)>0&&r.transcription_released!==0&&<span role="status"> · 전사 대기 {r.transcription.queued} · 처리 {r.transcription.running}</span>}
      {r.gaps.length>0&&<span> · 누락 {r.gaps.map(g=>stamp(g.start_frame*1000/r.sample_rate)+'–'+stamp(g.end_frame*1000/r.sample_rate)).join(', ')}</span>}
      {(r.transcription.failed+r.transcription.interrupted+r.transcription.cancelled>0||r.status==='interrupted'||r.transcription_released===0&&r.status!=='recording')&&r.status!=='audio_deleted'&&<button disabled={records.some(record=>record.status==='recording'&&record.capture_id===r.capture_id)} onClick={()=>void retry(r.id)}>{r.transcription_released===0?'전사 실행':'전사 재시도'}</button>}{r.error&&<p role="alert">{r.error}</p>}</div>)}
    <div className="transcript-list">{segments.map(s=><div key={s.id} className={'transcript '+(s.final?'final':'provisional')}>{s.final?<SourceLink id={s.id+':v'+s.revision} label={stamp(s.start_ms)+'–'+stamp(s.end_ms)}/>:<span className="muted">{stamp(s.start_ms)}–{stamp(s.end_ms)} · 잠정</span>}
      {editing===s.id?<div><label className="sr-only" htmlFor={'segment-'+s.id}>전사 수정</label><textarea id={'segment-'+s.id} value={text} onChange={e=>setText(e.target.value)} maxLength={10000}/><button onClick={()=>setEditing(null)}>취소</button><button onClick={()=>void save()}>저장</button></div>:<p>{s.text}{s.final?<button className="text-button" onClick={()=>{setEditing(s.id);setText(s.text);}}>수정</button>:null}{s.final&&<button className="text-button" disabled={reviews.some(j=>['queued','running'].includes(j.status)&&j.request.chunk_id===s.chunk_id)} onClick={()=>void review(s.chunk_id)}>원음 다시 인식</button>}</p>}
      {s.revision>1&&<details><summary>원래 인식문 · v{s.revision}</summary><p>{s.original_text}</p></details>}</div>)}</div>
    {empty.map(r=><details key={r.id}><summary>빈 전사 구간 · {stamp(r.start_ms)}–{stamp(r.end_ms)}</summary><p>발화 또는 소음인지 원음을 확인하세요.</p>{r.audio_url&&<audio controls preload="none" src={r.audio_url} onLoadedMetadata={e=>{if(r.seek_seconds!==null)e.currentTarget.currentTime=r.seek_seconds;}} aria-label="빈 전사 구간 원음"/>}<button disabled={!r.audio_url||reviews.some(j=>j.request.chunk_id===r.id&&['queued','running'].includes(j.status))} onClick={()=>void review(r.id)}>원음 다시 인식</button></details>)}
    {reviews.map(job=><ReviewCard key={job.id} job={job} refresh={refresh}/>)}
    {error&&<p role="alert">{error}</p>}
  </section>;
}
