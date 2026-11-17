import React,{useEffect,useRef,useState} from 'react';
import {api,downloadJSON} from './api';
import {navigate} from './native-lifecycle';
import {useCloseGuard} from './use-close-guard';
import SourceLink from './SourceLink';
import type {Course,Session,CourseScope,SessionScope,Evidence} from './types';

type Memory={id:string;kind:string;text:string;quote:string;status:string;manual:number;revision:number;created_at:string;updated_at:string;thread_id?:string|null;source_message_id?:string|null};
type Thread={id:string;title:string;summary_error?:string|null;updated_at:string};
type ChatArtifact={body:{basis?:string;evidence_ids?:string[];citations?:{source_id:string}[];sections?:{evidence_ids?:string[]}[];uncertainty?:string};evidence:Evidence[];metadata:{context_omitted?:boolean;memory_used?:boolean;model:string}};
type Message={id:string;ordinal:number;role:'user'|'assistant';text:string;created_at:string;job_id:string|null;job_status:string|null;job_error:string|null;artifact?:ChatArtifact};
type Conversation=Thread&{messages:Message[];has_more:boolean;epoch:string};
type State={enabled:boolean;provider:string;course_id:string|null;memories:Memory[]};

export function ChatComposer({prompt,setPrompt,onSubmit,external,includeMemory,setIncludeMemory,enabled,busy,running}:{prompt:string;setPrompt:(s:string)=>void;onSubmit:(e:React.FormEvent)=>void;external:boolean;includeMemory:boolean;setIncludeMemory:(v:boolean)=>void;enabled:boolean;busy:boolean;running:boolean}){
 return <form className="study-composer" onSubmit={onSubmit}>
  <label>질문<textarea value={prompt} onChange={e=>setPrompt(e.target.value)} maxLength={10000} required rows={3} disabled={busy||running} placeholder="지난 공부를 이어가거나, 궁금한 내용을 질문하세요."/></label>
  {external&&<p className="muted">외부 API에 현재 질문과 선택한 자료가 전송됩니다. 이전 맥락은 아래 항목을 선택할 때만 함께 보냅니다.</p>}
  <label className="checkbox-line"><input type="checkbox" checked={includeMemory&&enabled} disabled={busy||running||!enabled} onChange={e=>setIncludeMemory(e.target.checked)}/>{external?'이전 대화·과목 학습 기억 함께 보내기':'이전 대화·과목 학습 기억 활용'}</label>
  {!enabled&&<p className="muted">이전 맥락 사용·자동 정리가 일시 정지되어 있습니다. 새 대화 원문은 계속 저장됩니다.</p>}
  <div className="actions"><button className="primary" disabled={busy||running||!prompt.trim()}>대화 보내기</button>{prompt&&<button type="button" disabled={busy||running} onClick={()=>setPrompt('')}>입력 지우기</button>}</div>
  {running&&<p role="status">답변 생성 중… 다른 화면에서도 작업은 이어집니다.</p>}
 </form>;
}

const kindLabels:Record<string,string>={topic:'학습 주제',progress:'공부한 지점',difficulty:'어려웠던 내용',question:'미해결 질문',quiz:'퀴즈 관찰'};
const statusLabels:Record<string,string>={active:'진행 중',resolved:'해결됨',review:'확인 필요'};
export function MessageEvidence({artifact}:{artifact:ChatArtifact}){
 const ids=artifact.body.evidence_ids??artifact.body.citations?.map(c=>c.source_id)??artifact.body.sections?.flatMap(s=>s.evidence_ids??[])??[];
 return <>{artifact.evidence.filter(e=>ids.includes(e.ref.id)).map(e=><SourceLink key={e.ref.id} id={e.ref.id} label={e.label}/>)}</>;
}
export function mergeConversation(old:Conversation|null,row:Conversation){
 return old?.id===row.id&&old.epoch===row.epoch&&old.messages.length>40?{...row,messages:[...old.messages.filter(m=>m.ordinal<(row.messages[0]?.ordinal??0)),...row.messages]}:row;
}
export function memoryEditBody(owned:Record<string,string>,draft:Pick<Memory,'revision'>,text:string,status:string){return {...owned,text,status,revision:draft.revision};}
export function MemoryCard({item,busy,onEdit,onDelete,onOpen}:{item:Memory;busy:boolean;onEdit:()=>void;onDelete:()=>void;onOpen:()=>void}){
 return <article className="study-memory-item">
  <div className="subheading"><strong>{kindLabels[item.kind]||item.kind}</strong><span className="badge">{statusLabels[item.status]||item.status}</span></div>
  <p>{item.text}</p><p className="muted">{item.manual?'내가 확인한 기억':'자동 정리'} · {new Date(item.updated_at).toLocaleString('ko-KR')}</p>
  <details><summary>근거 보기</summary><blockquote>{item.quote}</blockquote>{item.thread_id&&<button disabled={busy} onClick={onOpen}>대화 열기</button>}</details>
  <div className="actions"><button disabled={busy} onClick={onEdit}>수정</button><button disabled={busy} onClick={onDelete}>기억 삭제</button></div>
 </article>;
}

export default function StudyChat({session,course,scope,initialPrompt='',seedArtifactId}:{session?:Session;course?:Course;scope?:CourseScope|SessionScope;initialPrompt?:string;seedArtifactId?:string|null}){
 const owned:Record<string,string>=course?{course_id:course.id}:{session_id:session!.id};
 const query=new URLSearchParams(owned).toString(),ownerKey=course?.id||session!.id;
 const [threads,setThreads]=useState<Thread[]>([]),[current,setCurrent]=useState<Conversation|null>(null),[state,setState]=useState<State|null>(null);
 const [prompt,setPrompt]=useState(initialPrompt),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
 const [includeMemory,setIncludeMemory]=useState(false),[confirm,setConfirm]=useState<{kind:'thread'|'memory'|'clear';id?:string}|null>(null);
 const [editing,setEditing]=useState<Memory|null>(null),[editText,setEditText]=useState(''),[editStatus,setEditStatus]=useState('active');
 const selectedId=useRef<string|null>(null),loading=useRef(false),requestId=useRef<string|null>(null),seeded=useRef<string|null>(null);
 const activeOwner=useRef(ownerKey);activeOwner.current=ownerKey;
 useCloseGuard('대화 질문',!!prompt.trim()||busy);
 useCloseGuard('학습 기억 수정',!!editing&&(editText!==editing.text||editStatus!==editing.status));
 const pending=current?.messages.find(m=>m.role==='user'&&['queued','running'].includes(m.job_status||''));
 const external=!!state&&!['local','ollama'].includes(state.provider);

 async function refresh(id=selectedId.current){
  const [list,s]=await Promise.all([api<Thread[]>('/study/threads?'+query),api<State>('/study/state?'+query)]);
  if(activeOwner.current!==ownerKey)return;
  setThreads(list);setState(s);
  const target=id&&list.some(t=>t.id===id)?id:list[0]?.id;
  if(target){const row=await api<Conversation>('/study/threads/'+target+'?'+query);if(activeOwner.current===ownerKey&&(selectedId.current===id||!selectedId.current)){selectedId.current=target;setCurrent(old=>mergeConversation(old,row));}}
  else{selectedId.current=null;setCurrent(null);}
 }
 useEffect(()=>{
  let live=true;selectedId.current=null;setCurrent(null);setThreads([]);setError('');
  async function read(){if(loading.current)return;loading.current=true;try{if(live){await refresh();if(live)setError('');}}catch(e){if(live)setError((e as Error).message);}finally{loading.current=false;}}
  void read();const timer=setInterval(()=>void read(),4000);return()=>{live=false;clearInterval(timer);};
 },[ownerKey]);
 useEffect(()=>{setIncludeMemory(!!state&&['local','ollama'].includes(state.provider));},[state?.provider]);
 useEffect(()=>{if(initialPrompt)setPrompt(initialPrompt);},[initialPrompt]);
 useEffect(()=>{if(!seedArtifactId||seeded.current===seedArtifactId)return;seeded.current=seedArtifactId;void act(async()=>{const created=await api<Thread>('/study/threads',{method:'POST',body:JSON.stringify({...owned,artifact_id:seedArtifactId})});selectedId.current=created.id;await refresh(created.id);});},[seedArtifactId]);
 async function act(fn:()=>Promise<void>){setBusy(true);setError('');setNotice('');try{await fn();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 async function open(id:string){if(!navigate(()=>{}))return;await act(async()=>{selectedId.current=id;setCurrent(await api<Conversation>('/study/threads/'+id+'?'+query));setConfirm(null);});}
 async function create(){if(!navigate(()=>{}))return;await act(async()=>{const row=await api<Thread>('/study/threads',{method:'POST',body:JSON.stringify(owned)});selectedId.current=row.id;await refresh(row.id);});}
 async function send(e:React.FormEvent){
  e.preventDefault();if(!prompt.trim()||pending)return;
  await act(async()=>{
   let id=selectedId.current;
   if(!id){const row=await api<Thread>('/study/threads',{method:'POST',body:JSON.stringify(owned)});id=row.id;selectedId.current=id;}
   const messageId=requestId.current||crypto.randomUUID().replaceAll('-','');requestId.current=messageId;
   await api('/study/threads/'+id+'/messages',{method:'POST',body:JSON.stringify({...owned,prompt,scope:scope||(course?{course_id:course.id,mode:'course'}:{session_id:session!.id,mode:session?.course_id?'course':'current'}),include_memory:includeMemory,request_id:messageId})});
   requestId.current=null;setPrompt('');await refresh(id);
  });
 }
 function changePrompt(value:string){requestId.current=null;setPrompt(value);}
 async function remove(){if(!confirm)return;await act(async()=>{
  if(confirm.kind==='thread')await api('/study/threads/'+confirm.id+'?'+query,{method:'DELETE'});
  else await api('/study/memories'+(confirm.kind==='memory'?'/'+confirm.id:'')+'?course_id='+state!.course_id,{method:'DELETE'});
  if(confirm.kind==='thread')selectedId.current=null;
  setConfirm(null);await refresh();setNotice('삭제했습니다. 이후 자동 정리로 삭제한 기억을 다시 만들지 않습니다.');
 });}
 return <section className="study-chat" aria-label="대화와 학습 기억">
  <section className="card"><div className="subheading"><h2>이어서 공부하기</h2><button disabled={busy||!!pending} onClick={()=>void create()}>새 대화</button></div>
   <p className="muted">대화는 이 기기에 저장됩니다. 학습 기억은 같은 과목에서만 이어집니다.</p>
   {!!threads.length&&<div className="form-row"><label>저장된 대화<select value={current?.id||''} disabled={busy} onChange={e=>void open(e.target.value)}>{threads.map(t=><option key={t.id} value={t.id}>{t.title} · {new Date(t.updated_at).toLocaleDateString('ko-KR')}</option>)}</select></label><button disabled={busy||!current} onClick={()=>setConfirm({kind:'thread',id:current!.id})}>대화 삭제</button></div>}
   {!state&&<p role="status">저장된 대화를 불러오는 중…</p>}
   {error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}
   {current?.has_more&&<button disabled={busy} onClick={()=>void act(async()=>{const earlier=await api<Conversation>('/study/threads/'+current.id+'?'+query+'&before='+current.messages[0].ordinal);setCurrent({...current,has_more:earlier.has_more,messages:[...earlier.messages,...current.messages]});})}>이전 대화 더 보기</button>}
   <div className="study-transcript" role="log" aria-label="저장된 대화" aria-live="polite" aria-busy={!!pending}>
    {!current?.messages.length&&<p className="muted">첫 질문을 남겨 보세요. 다음에 앱을 열어도 이 대화를 이어갈 수 있습니다.</p>}
    {current?.messages.map(m=><article key={m.id} className={'study-message '+m.role}><div className="subheading"><strong>{m.role==='user'?'나':'솔라시'}</strong><time dateTime={m.created_at}>{new Date(m.created_at).toLocaleString('ko-KR')}</time></div><p className="source-text">{m.text}</p>
     {m.artifact&&<><p className="muted">{{sources:'자료 근거',conversation:'대화·학습 맥락',general:'일반 해설 · 강의자료에서 확인되지 않음'}[m.artifact.body.basis||'sources']} · {m.artifact.metadata.model}</p><MessageEvidence artifact={m.artifact}/>{m.artifact.body.uncertainty&&<p>{m.artifact.body.uncertainty}</p>}{m.artifact.metadata.context_omitted&&<p className="muted">입력 예산에 맞춰 과거 맥락·근거 일부를 생략했습니다.</p>}</>}
     {m.role==='user'&&m.job_error&&<p role="alert">{m.job_error}</p>}
     {m.role==='user'&&['failed','cancelled','interrupted'].includes(m.job_status||'')&&<button disabled={busy||!!pending} onClick={()=>void act(async()=>{await api('/study/threads/'+current.id+'/retry',{method:'POST',body:JSON.stringify({...owned,job_id:m.job_id})});await refresh();})}>이 질문 재시도</button>}
    </article>)}
   </div>
   {pending&&<button disabled={busy} onClick={()=>void act(async()=>{await api('/jobs/'+pending.job_id+'/cancel',{method:'POST'});await refresh();})}>생성 취소</button>}
   <ChatComposer prompt={prompt} setPrompt={changePrompt} onSubmit={e=>void send(e)} external={external} includeMemory={includeMemory} setIncludeMemory={setIncludeMemory} enabled={state?.enabled??false} busy={busy||!state} running={!!pending}/>
   {current&&<button disabled={busy} onClick={()=>void act(async()=>{const pages:Message[]=[];let before:number|undefined;for(;;){const page=await api<Conversation>('/study/threads/'+current.id+'?'+query+'&limit=100'+(before?'&before='+before:''));pages.unshift(...page.messages);if(!page.has_more)break;before=page.messages[0].ordinal;}const result=await downloadJSON('솔라시-대화-'+current.id+'.json',{title:current.title,messages:pages,learning_memory:state?.memories||[]});setNotice(result==='cancelled'?'내보내기를 취소했습니다.':'대화 내보내기를 완료했습니다.');})}>대화·학습 기억 내보내기</button>}
  </section>
  {state?.course_id&&<section className="card"><details><summary>이 과목의 학습 기억 · {state.memories.length}개</summary><p className="muted">자동 정리는 오류가 있을 수 있습니다. 기억을 고치거나 해결됨으로 바꿀 수 있습니다. 페이지 열람만으로 학습 완료를 판단하지 않습니다.</p>
   {!state.memories.length&&<p>아직 정리된 기억이 없습니다. 공부한 지점이나 어려움을 대화에 남기면 로컬 AI가 유휴 시간에 정리합니다.</p>}
   {state.memories.map(item=>editing?.id===item.id?<form className="study-memory-item" key={item.id} onSubmit={e=>{e.preventDefault();void act(async()=>{await api('/study/memories/'+item.id,{method:'PATCH',body:JSON.stringify(memoryEditBody(owned,editing!,editText,editStatus))});setEditing(null);await refresh();});}}><label>기억 수정<textarea value={editText} maxLength={2000} required onChange={e=>setEditText(e.target.value)}/></label><label>상태<select value={editStatus} onChange={e=>setEditStatus(e.target.value)}><option value="active">진행 중</option><option value="resolved">해결됨</option><option value="review">확인 필요</option></select></label><div className="actions"><button disabled={busy}>기억 저장</button><button type="button" disabled={busy} onClick={()=>setEditing(null)}>수정 취소</button></div></form>:<MemoryCard key={item.id} item={item} busy={busy} onEdit={()=>{setEditing(item);setEditText(item.text);setEditStatus(item.status);}} onDelete={()=>setConfirm({kind:'memory',id:item.id})} onOpen={()=>void open(item.thread_id!)}/>)}
   {threads.some(t=>t.summary_error)&&<><p role="alert">일부 대화의 자동 정리에 실패했습니다. 대화 원문은 보존되어 있습니다.</p>{threads.filter(t=>t.summary_error).map(t=><p key={t.id}>{t.summary_error}</p>)}<button disabled={busy} onClick={()=>void act(async()=>{await api('/study/retry-memory',{method:'POST',body:JSON.stringify(owned)});await refresh();})}>자동 정리 재시도</button></>}
   {!!state.memories.length&&<button disabled={busy} onClick={()=>setConfirm({kind:'clear'})}>이 과목의 학습 기억 비우기</button>}
  </details></section>}
  {confirm&&<section className="card study-confirm" role="alert"><h3>{confirm.kind==='thread'?'대화를 삭제할까요?':confirm.kind==='clear'?'이 과목의 학습 기억을 비울까요?':'이 기억을 삭제할까요?'}</h3><p>{confirm.kind==='thread'?'이 대화의 질문·답변과 여기에서 만든 기억을 함께 지웁니다.':'대화 원문은 남습니다. 이전 대화에서 삭제한 기억을 자동으로 다시 만들지 않습니다. 기억 변경 전의 맥락은 다음 답변에 자동 적용하지 않습니다.'} 진행 중인 관련 작업은 취소됩니다. 이미 외부 API에 보낸 내용은 회수할 수 없습니다.</p><div className="actions"><button disabled={busy} onClick={()=>void remove()}>확인하고 삭제</button><button disabled={busy} onClick={()=>setConfirm(null)}>취소</button></div></section>}
 </section>;
}
