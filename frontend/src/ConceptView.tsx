import React,{useEffect,useState} from 'react';
import {api} from './api';
import SourceLink from './SourceLink';
import JobProgress from './JobProgress';
import type {Job} from './types';
import type {Session,SourceRef,Evidence,SearchResult,Term} from './types';

type ConceptDetail={term:Term;related_evidence:Evidence[];related_quizzes:{quiz_id:string;question:{prompt:string};attempts:{grade:string|null;submitted_answer:string;explanation:string}[]}[]};
export default function ConceptView({session,onQuestion,onQuiz}:{session:Session;onQuestion:(prompt:string)=>void;onQuiz:(id:string)=>void}) {
  const [query,setQuery]=useState(''),[mode,setMode]=useState<'course'|'current'|'selected'>(session.course_id?'course':'current');
  const [lectures,setLectures]=useState<Session[]>([]),[selected,setSelected]=useState<string[]>([session.id]);
  const [result,setResult]=useState<SearchResult|null>(null),[terms,setTerms]=useState<Term[]>([]);
  const [canonical,setCanonical]=useState(''),[aliases,setAliases]=useState(''),[explanation,setExplanation]=useState(''),[termId,setTermId]=useState<string|null>(null);
  const [refs,setRefs]=useState<SourceRef[]>([]),[detail,setDetail]=useState<ConceptDetail|null>(null);
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[status,setStatus]=useState('');
  const [searchJob,setSearchJob]=useState<Job<SearchResult>|null>(null);
  const searchActive=!!searchJob&&['queued','running'].includes(searchJob.status),working=busy||searchActive;
  const [index,setIndex]=useState<{ready:boolean;model?:string;unindexed_chunks?:number}|null>(null),[indexJob,setIndexJob]=useState<{id:string;status:string;error:string|null;result:{completed_chunks?:number;total_chunks?:number;paused_reason?:string}|null}|null>(null);
  useEffect(()=>{let live=true;Promise.all([api<Term[]>('/sessions/'+session.id+'/terms'),api<Session[]>('/sessions')]).then(([items,all])=>{if(live){setTerms(items);setLectures(all.filter(s=>s.kind==='lecture'&&s.course_id===session.course_id&&session.course_id!==null));}}).catch(e=>{if(live)setError(e.message);});return()=>{live=false;};},[session.id]);
  useEffect(()=>{api<typeof index>('/index/status').then(setIndex).catch(e=>setError(e.message));},[]);
  useEffect(()=>{let live=true;api<(Job<SearchResult>&{request:{query:string;scope:{mode:typeof mode;lecture_ids:string[]}}})[]>('/sessions/'+session.id+'/jobs').then(jobs=>{if(!live)return;const job=jobs.find(j=>j.kind==='search');if(job){setSearchJob(job);setQuery(job.request.query);setMode(job.request.scope.mode);setSelected(job.request.scope.lecture_ids);if(job.status==='done'&&job.result)setResult(job.result);}}).catch(e=>{if(live)setError(e.message);});return()=>{live=false;};},[session.id]);
  useEffect(()=>{if(!searchJob||!searchActive)return;let live=true;const timer=setInterval(async()=>{try{const updated=await api<Job<SearchResult>>('/jobs/'+searchJob.id);if(!live)return;setSearchJob(updated);if(updated.status==='done'&&updated.result)setResult(updated.result);}catch(e){if(live)setError((e as Error).message);}},700);return()=>{live=false;clearInterval(timer);};},[searchJob?.id,searchJob?.status]);
  useEffect(()=>{if(!indexJob||!['queued','running'].includes(indexJob.status))return;const timer=setInterval(async()=>{try{const updated=await api<NonNullable<typeof indexJob>>('/jobs/'+indexJob.id);setIndexJob(updated);if(updated.status==='done')setIndex(await api<typeof index>('/index/status'));}catch(e){setError((e as Error).message);}},700);return()=>clearInterval(timer);},[indexJob?.id,indexJob?.status]);
  async function rebuild(){setBusy(true);setError('');try{setIndexJob(await api<NonNullable<typeof indexJob>>('/index/rebuild',{method:'POST',body:JSON.stringify({session_id:session.id,model:'embeddinggemma'})}));}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  async function search(e:React.FormEvent){
    e.preventDefault();setBusy(true);setError('');setStatus('');
    try{const result=await api<SearchResult|Job<SearchResult>>('/sessions/'+session.id+'/search',{method:'POST',body:JSON.stringify({query,scope:{session_id:session.id,mode,lecture_ids:mode==='selected'?selected:[]}})});if('kind' in result){setSearchJob(result);setResult(null);}else{setSearchJob(null);setResult(result);}}catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  function toggle(ref:SourceRef){setRefs(old=>old.some(r=>r.id===ref.id)?old.filter(r=>r.id!==ref.id):[...old,ref]);}
  function reset(){setTermId(null);setCanonical('');setAliases('');setExplanation('');setRefs([]);setDetail(null);setStatus('');}
  async function open(term:Term){
    setError('');setBusy(true);
    try{const saved=await api<ConceptDetail>('/sessions/'+session.id+'/terms/'+term.id);setDetail(saved);setTermId(term.id);setCanonical(saved.term.canonical);setAliases(saved.term.aliases.join(', '));setExplanation(saved.term.explanation);setRefs(saved.term.evidence);setStatus('');}catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  async function save(e:React.FormEvent){
    e.preventDefault();setBusy(true);setError('');setStatus('');
    try{const term=await api<Term>('/sessions/'+session.id+'/terms',{method:'PUT',body:JSON.stringify({term_id:termId,canonical,aliases:aliases.split(',').map(t=>t.trim()).filter(Boolean),explanation,evidence:refs})});setTermId(term.id);setTerms(await api<Term[]>('/sessions/'+session.id+'/terms'));setDetail(await api<ConceptDetail>('/sessions/'+session.id+'/terms/'+term.id));setStatus('저장됨 · v'+term.revision);}catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  const visibleIds=new Set(result?.evidence.map(e=>e.ref.id)||[]);
  return <div>
    <section className="card"><h2>자료·전사 검색</h2><p role="status">{index?.ready?'의미 색인 준비됨 · '+index.model+(index.unindexed_chunks?' · 새 원문 재색인 필요':''):'의미 색인 준비 전'}</p><button type="button" disabled={working||!!indexJob&&['queued','running'].includes(indexJob.status)} onClick={()=>void rebuild()}>의미 색인 갱신</button>{indexJob&&<div role="status"><p>{indexJob.status==='done'?'색인 완료':indexJob.result?.paused_reason||({queued:'색인 대기',running:'색인 중',failed:'색인 실패',cancelled:'색인 취소',interrupted:'색인 중단'}[indexJob.status])}{indexJob.result?.total_chunks?' · '+indexJob.result.completed_chunks+'/'+indexJob.result.total_chunks:''}</p>{indexJob.error&&<p role="alert">{indexJob.error}</p>}{['queued','running'].includes(indexJob.status)&&<button type="button" onClick={()=>api<NonNullable<typeof indexJob>>('/jobs/'+indexJob.id+'/cancel',{method:'POST'}).then(setIndexJob).catch(e=>setError(e.message))}>색인 취소</button>}</div>}<form onSubmit={search}>
      <label>검색 범위<select value={mode} disabled={working} onChange={e=>setMode(e.target.value as typeof mode)}><option value="current">현재 기록</option>{session.course_id&&<><option value="course">같은 과목 전체</option><option value="selected">회차 선택</option></>}</select></label>
      {mode==='selected'&&<fieldset className="concept-options"><legend>검색 회차</legend>{lectures.map(s=><label key={s.id}><input type="checkbox" checked={selected.includes(s.id)} disabled={working} onChange={e=>setSelected(old=>e.target.checked?[...old,s.id]:old.filter(id=>id!==s.id))}/>{s.lecture_no}회차 · {s.title}</label>)}</fieldset>}
      <label>검색어<input value={query} onChange={e=>setQuery(e.target.value)} disabled={working} required maxLength={2000}/></label><button className="primary" disabled={working}>검색</button>
    </form>{error&&<p role="alert">{error}</p>}{searchJob&&<JobProgress job={searchJob} onChange={setSearchJob}/>}
    {result&&<><p role="status">{result.warning||(result.mode==='hybrid'?'키워드·의미 검색':'키워드 검색')} · {result.evidence.length}개</p>{result.evidence.map(e=><article key={e.ref.id}><SourceLink id={e.ref.id} label={e.label}/><pre className="source-text">{e.text}</pre><label className="concept-check"><input type="checkbox" checked={refs.some(r=>r.id===e.ref.id)} onChange={()=>toggle(e.ref)}/>개념의 근거로 선택</label></article>)}</>}
    </section>
    <section className="card"><div className="subheading"><h2>{session.course_id?'과목 개념':'기록 개념'}</h2><button type="button" onClick={reset} disabled={working}>새 개념</button></div>
      <div className="concept-options">{terms.map(term=><button type="button" key={term.id} disabled={working} onClick={()=>void open(term)}>{term.canonical} · v{term.revision}</button>)}</div>
      <form onSubmit={save}><label>표준 표기<input value={canonical} onChange={e=>setCanonical(e.target.value)} required disabled={working} maxLength={120}/></label><label>별칭 · 쉼표로 구분<input value={aliases} onChange={e=>setAliases(e.target.value)} disabled={working} maxLength={3600}/></label><label>정의·메모<textarea value={explanation} onChange={e=>setExplanation(e.target.value)} disabled={working} maxLength={10000} rows={4}/></label>
      <p>선택 근거 {refs.length}개</p>{refs.filter(ref=>!visibleIds.has(ref.id)).map(ref=><div key={ref.id}><SourceLink id={ref.id} label={'저장된 근거 · v'+ref.version}/><button type="button" disabled={working} onClick={()=>toggle(ref)}>선택 해제</button></div>)}
      <button className="primary" disabled={working}>개념 저장</button>{status&&<p role="status">{status}</p>}</form>
      {detail&&<section><button type="button" onClick={()=>onQuestion(detail.term.canonical+' 개념을 이전 수업과 연결해서 설명해 주세요.')}>개념 질문</button><h3>관련 자료·전사</h3>{detail.related_evidence.map(e=><article key={e.ref.id}><SourceLink id={e.ref.id} label={e.label}/><pre className="source-text">{e.text}</pre></article>)}<h3>관련 문제·풀이</h3>{detail.related_quizzes?.map((item,i)=><div key={i}><button type="button" onClick={()=>onQuiz(item.quiz_id)}>{item.question.prompt}</button>{item.attempts.map((a,n)=><p key={n}>{a.grade||'미채점'} · {a.submitted_answer} · {a.explanation}</p>)}</div>)}</section>}
    </section>
  </div>;
}
