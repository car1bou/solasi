import SummarySection from './SummarySection';
import React,{useEffect,useState} from 'react';
import QuestionView from './QuestionView';
import type {Artifact,QuizQuestion} from './QuestionView';
import type {Session} from './types';
import {api} from './api';
import SourceLink from './SourceLink';
import JobProgress from './JobProgress';
import type {Job} from './types';

type Attempt={id:string;quiz_id:string;question_id:string;submitted_answer:string;grade:string|null;original_grade:string|null;explanation:string;status:string;error:string|null;metadata:{job_id?:string};overridden:boolean;history:{revision:number;grade:string;explanation:string}[]};
const grades:Record<string,string>={correct:'정답',partial:'부분 정답',incorrect:'오답'};

function QuizItem({quiz,question,onUpdated}:{quiz:Artifact;question:QuizQuestion;onUpdated:()=>Promise<void>}){
  const [answer,setAnswer]=useState(''),[attempts,setAttempts]=useState<Attempt[]>([]),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const [editing,setEditing]=useState<Attempt|null>(null),[grade,setGrade]=useState('partial'),[reason,setReason]=useState('');
  const [job,setJob]=useState<Job<{attempt_id:string}>|null>(null);
  const active=!!job&&['queued','running'].includes(job.status),working=busy||active;
  async function refresh(){const rows=(await api<Attempt[]>('/sessions/'+quiz.session_id+'/review')).filter(a=>a.quiz_id===quiz.id&&a.question_id===question.id);setAttempts(rows);const latest=rows[0];setJob(latest?.metadata.job_id?await api<Job<{attempt_id:string}>>('/jobs/'+latest.metadata.job_id):null);}
  useEffect(()=>{refresh().catch(e=>setError(e.message));},[quiz.id,question.id]);
  useEffect(()=>{if(!job||!active)return;let live=true;const timer=setInterval(async()=>{try{const updated=await api<NonNullable<typeof job>>('/jobs/'+job.id);if(!live)return;setJob(updated);if(!['queued','running'].includes(updated.status)){await refresh();await onUpdated();}}catch(e){if(live)setError((e as Error).message);}},700);return()=>{live=false;clearInterval(timer);};},[job?.id,job?.status]);
  async function submit(e:React.FormEvent){e.preventDefault();setBusy(true);setError('');try{const result=await api<Attempt|Job<{attempt_id:string}>>('/quizzes/'+quiz.id+'/attempts',{method:'POST',body:JSON.stringify({question_id:question.id,answer})});if('kind' in result)setJob(result);await refresh();await onUpdated();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  async function override(e:React.FormEvent){e.preventDefault();if(!editing)return;setBusy(true);setError('');try{await api<Attempt>('/attempts/'+editing.id,{method:'PATCH',body:JSON.stringify({grade,explanation:reason})});setEditing(null);await refresh();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  return <article className="quiz-item"><h3>{question.prompt}</h3>{question.external_extension&&<p>외부 참고 확장 문제</p>}<form onSubmit={submit}>{question.kind==='choice'?<fieldset><legend>답안 선택</legend>{question.options.map((option,i)=><label className="checkbox-line" key={i}><input type="radio" name={question.id} value={'ABCDEF'[i]} checked={answer==='ABCDEF'[i]} onChange={e=>setAnswer(e.target.value)} disabled={working} required/>{'ABCDEF'[i]}. {option}</label>)}</fieldset>:<label>답안<textarea value={answer} onChange={e=>setAnswer(e.target.value)} maxLength={10000} required disabled={working}/></label>}<button disabled={working}>{active?'채점 대기·진행 중':busy?'처리 중':'답안 제출·재풀이'}</button></form>{error&&<p role="alert">{error}</p>}{job&&<JobProgress job={job} onChange={updated=>{setJob(updated);void refresh().catch(e=>setError(e.message));}}/>}
    {question.answer&&<details><summary>정답·채점 기준·해설</summary><pre className="source-text">{question.answer+'\n'+question.rubric+'\n'+question.explanation}</pre></details>}
    {question.evidence_ids.map(id=><SourceLink key={id} id={id} label={quiz.evidence.find(e=>e.ref.id===id)?.label||'근거'}/>)}
    {attempts.map(a=><div key={a.id}><p>{grades[a.grade||'']||({failed:'채점 실패',cancelled:'채점 취소',interrupted:'채점 중단'}[a.status])||'채점 중'}{a.overridden?' · 사용자 수정':''} · 제출 답안: {a.submitted_answer}</p><pre className="source-text">{a.explanation||a.error}</pre><button disabled={working} onClick={()=>{setEditing(a);setGrade(a.grade||'partial');setReason(a.explanation);}}>판정 수정</button>{a.history.length>0&&<details><summary>원래 판정·수정 이력</summary><p>{grades[a.original_grade||'']||'원래 판정 없음'}</p>{a.history.map(h=><p key={h.revision}>{'v'+h.revision+' · '+grades[h.grade]+' · '+h.explanation}</p>)}</details>}</div>)}
    {editing&&<form onSubmit={override}><label>수정 판정<select value={grade} onChange={e=>setGrade(e.target.value)}>{Object.entries(grades).map(([k,v])=><option value={k} key={k}>{v}</option>)}</select></label><label>수정 이유<textarea value={reason} onChange={e=>setReason(e.target.value)} required maxLength={10000}/></label><button disabled={working}>수정 저장</button><button type="button" onClick={()=>setEditing(null)}>취소</button></form>}
  </article>;
}

export default function StudyView({session,artifactId}:{session:Session;artifactId?:string|null}){
  const [kind,setKind]=useState<'summary'|'quiz'>('summary');
  useEffect(()=>{if(artifactId)setKind('quiz');},[artifactId]);
  return <div><div className="segmented"><button aria-pressed={kind==='summary'} onClick={()=>setKind('summary')}>전체 요약</button><button aria-pressed={kind==='quiz'} onClick={()=>setKind('quiz')}>퀴즈·풀이</button></div><QuestionView key={kind} session={session} kind={kind} artifactId={kind==='quiz'?artifactId:null} renderArtifact={(saved,refresh)=><><h3>AI {kind==='summary'?'요약':'퀴즈'}</h3>{saved.body.covered_source_ids&&<p>처리한 원문 {saved.body.covered_source_ids.length}개 · 최종 인용 {saved.body.cited_source_ids?.length??saved.body.covered_source_ids.length}개</p>}{(saved.body.merged||!!saved.body.selection_incomplete_parts?.length)&&<p>{saved.body.selection_incomplete_parts?.length?'최종 선택 불완전 · 누락한 구간 요약을 함께 표시':'구간 요약 처리 완료'} · {saved.body.merge_steps}회</p>}{!!saved.body.unquoted_sources?.length&&<details><summary>직접 인용하지 않은 원문 {saved.body.unquoted_sources.length}개 · 누락 여부 확인</summary>{saved.body.unquoted_sources.map((q,i)=><blockquote key={i}><pre className="source-text">{q.text}</pre>{q.evidence_ids.map(id=><SourceLink key={id} id={id} label={saved.evidence.find(e=>e.ref.id===id)?.label||'원문'}/>)}</blockquote>)}</details>}{saved.body.part_sections&&<details><summary>원래 구간 요약</summary>{saved.body.part_sections.map((s,i)=><SummarySection key={i} section={s} evidence={saved.evidence}/>)}</details>}{saved.body.sections?.map((section,i)=><SummarySection key={i} section={section} evidence={saved.evidence}/>)}{saved.body.questions?.map(q=><QuizItem key={q.id} quiz={saved} question={q} onUpdated={refresh}/>)}<p>{saved.metadata.model+' · '+saved.metadata.elapsed_ms+'ms'}</p>{saved.metadata.warning&&<p>{saved.metadata.warning}</p>}</>}/></div>;
}
