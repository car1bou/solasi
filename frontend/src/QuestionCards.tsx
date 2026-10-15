import React,{useEffect,useState} from 'react';
import {api} from './api';
import SourceLink from './SourceLink';
import JobProgress from './JobProgress';
import type {Artifact} from './QuestionView';
import type {Session,Job} from './types';

type Card={id:string;prompt:string;quote:string;source_id:string;pinned:boolean;dismissed:boolean;edited:boolean;answer_job_id:string|null};
type State={cards:Card[];options:{enabled:boolean};local:boolean;job:Job<{id:string}>|null};
function CardAnswer({jobId}:{jobId:string}){
  const [job,setJob]=useState<Job<{id:string}>|null>(null),[answer,setAnswer]=useState<Artifact|null>(null),[error,setError]=useState('');
  const [revision,setRevision]=useState(0);
  useEffect(()=>{let live=true;let timer:ReturnType<typeof setTimeout>;
    const poll=async()=>{try{const next=await api<Job<{id:string}>>('/jobs/'+jobId);if(!live)return;setJob(next);
      if(next.status==='done'&&next.result?.id){const saved=await api<Artifact>('/artifacts/'+next.result.id);if(live)setAnswer(saved);}
      else {setAnswer(null);if(['queued','running'].includes(next.status))timer=setTimeout(()=>void poll(),1500);}
    }catch(e){if(live)setError((e as Error).message);}};
    setError('');void poll();return()=>{live=false;clearTimeout(timer);};
  },[jobId,revision]);
  return <div>{job&&<JobProgress job={job} onChange={next=>{setJob(next);setRevision(r=>r+1);}}/>} {answer&&<><pre className="source-text">{answer.body.answer}</pre>{answer.body.uncertainty&&<p>{answer.body.uncertainty}</p>}{answer.body.citations?.map(c=><SourceLink key={c.source_id} id={c.source_id} label={answer.evidence.find(e=>e.ref.id===c.source_id)?.label||'근거'}/>)}</>}{error&&<p role="alert">{error}</p>}</div>;
}
export default function QuestionCards({session}:{session:Session}){
  const [state,setState]=useState<State>({cards:[],options:{enabled:false},local:true,job:null}),[error,setError]=useState(''),[busy,setBusy]=useState(false),[selected,setSelected]=useState<string|null>(null),[showAll,setShowAll]=useState(false),[editing,setEditing]=useState<{id:string;prompt:string}|null>(null);
  const base='/sessions/'+session.id;
  const refresh=async()=>setState(await api<State>(base+'/question-cards'));
  const act=async(operation:()=>Promise<unknown>)=>{setBusy(true);setError('');try{await operation();await refresh();}catch(e){setError((e as Error).message);}finally{setBusy(false);}};
  useEffect(()=>{let live=true;const poll=async()=>{try{const next=await api<State>(base+'/question-cards');if(live)setState(next);}catch(e){if(live)setError((e as Error).message);}};void poll();const timer=setInterval(()=>void poll(),3000);return()=>{live=false;clearInterval(timer);};},[session.id]);
  useEffect(()=>{if(!state.options.enabled||!state.local)return;const extract=async()=>{try{await api(base+'/question-candidates',{method:'POST',body:JSON.stringify({automatic:true})});await refresh();}catch(e){setError((e as Error).message);}};void extract();const timer=setInterval(()=>void extract(),30000);return()=>clearInterval(timer);},[session.id,state.options.enabled,state.local]);
  const running=state.job&&['queued','running'].includes(state.job.status);
  return <details className="card"><summary>질문 후보</summary><label className="checkbox-line"><input type="checkbox" checked={state.options.enabled} disabled={busy||(!state.local&&!state.options.enabled)} onChange={e=>void act(()=>api(base+'/question-candidates/options',{method:'PUT',body:JSON.stringify({enabled:e.target.checked})}))}/>로컬 자동 추출</label>{!state.local&&<p>API 후보 추출은 버튼을 눌렀을 때만 전사를 전송합니다.</p>}<button disabled={busy||!!running} onClick={()=>void act(()=>api(base+'/question-candidates',{method:'POST',body:JSON.stringify({automatic:false})}))}>후보 추출</button>
    {state.job&&<JobProgress job={state.job} onChange={()=>void refresh()}/>} {state.job?.status==='done'&&!state.cards.length&&<p>최근 전사에 질문 후보가 없습니다.</p>}{error&&<p role="alert">{error}</p>}
    {state.cards.filter(c=>!c.dismissed).slice(0,showAll?undefined:20).map(c=><article className="quiz-item" key={c.id}><h3>{c.prompt}</h3><blockquote>{c.quote}</blockquote><SourceLink id={c.source_id} label="질문이 나온 전사"/>{c.pinned&&<span> · 고정됨</span>}{editing?.id===c.id?<form onSubmit={e=>{e.preventDefault();void act(async()=>{await api(base+'/question-cards/'+c.id,{method:'PATCH',body:JSON.stringify({prompt:editing.prompt})});setEditing(null);});}}><label>질문 수정<textarea maxLength={2000} required value={editing.prompt} onChange={e=>setEditing({...editing,prompt:e.target.value})}/></label><button disabled={busy}>수정 저장</button><button type="button" onClick={()=>setEditing(null)}>취소</button></form>:<button disabled={busy||!!c.answer_job_id} onClick={()=>setEditing({id:c.id,prompt:c.prompt})}>수정</button>}
      <button disabled={busy} onClick={()=>void act(()=>api(base+'/question-cards/'+c.id,{method:'PATCH',body:JSON.stringify({pinned:!c.pinned})}))}>{c.pinned?'고정 해제':'고정'}</button><button disabled={busy} onClick={()=>void act(()=>api(base+'/question-cards/'+c.id,{method:'PATCH',body:JSON.stringify({dismissed:true})}))}>무시</button><button disabled={busy} onClick={()=>void act(async()=>{await api(base+'/question-cards/'+c.id+'/answer',{method:'POST',body:JSON.stringify({scope:{session_id:session.id,mode:session.course_id?'course':'current'}})});setSelected(c.id);})}>{c.answer_job_id?'답변 보기':'답변 실행'}</button>{selected===c.id&&c.answer_job_id&&<CardAnswer jobId={c.answer_job_id}/>}</article>)}
    {state.cards.filter(c=>!c.dismissed).length>20&&<button onClick={()=>setShowAll(!showAll)}>{showAll?'최근 20개만 보기':'나머지 질문 보기'}</button>}
  </details>;
}
