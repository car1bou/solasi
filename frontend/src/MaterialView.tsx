import React,{useEffect,useState} from 'react';
import NoteAugmentView from './NoteAugmentView';
import MaterialLibrary from './MaterialLibrary';
import {api} from './api';
import {navigate} from './native-lifecycle';
import {useCloseGuard} from './use-close-guard';
import type {Session,Course} from './types';
type Note={text:string;version:number;source_id:string;anchor_ms:number|null};
function SessionNote({session}:{session:Session}){
  const [saved,setSaved]=useState<Note|null>(null),[note,setNote]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const [loaded,setLoaded]=useState(false),[loadAttempt,setLoadAttempt]=useState(0);
  useCloseGuard('메모',busy||note!==(saved?.text||''));
  async function refresh(){const result=await api<{note:Note|null}>('/sessions/'+session.id+'/materials');setSaved(result.note);return result.note;}
  useEffect(()=>{let live=true;setError('');api<{note:Note|null}>('/sessions/'+session.id+'/materials').then(result=>{if(live){setSaved(result.note);setNote(result.note?.text||'');setLoaded(true);}}).catch(e=>{if(live)setError(e.message);});return()=>{live=false;};},[session.id,loadAttempt]);
  async function save(){if(!navigate(()=>{},['메모']))return;setBusy(true);setError('');try{await api('/sessions/'+session.id+'/note',{method:'PUT',body:JSON.stringify({text:note})});await refresh();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  return <><section className="session-note-panel"><div className="subheading"><h2>메모</h2><span className="muted">{saved?'v'+saved.version:''}</span></div>{!loaded&&!error&&<p role="status">메모 불러오는 중…</p>}<textarea disabled={busy||!loaded} aria-label="메모" rows={12} value={note} onChange={e=>setNote(e.target.value)}/><div className="actions"><button disabled={busy||!loaded||note===(saved?.text||'')} onClick={()=>void save()}>저장</button>{loaded&&note!==(saved?.text||'')&&<button disabled={busy} onClick={()=>setNote(saved?.text||'')}>메모 입력 되돌리기</button>}</div>{saved&&<NoteAugmentView key={saved.source_id} session={session} note={saved} dirty={note!==saved.text} onApplied={async()=>{const result=await refresh();setNote(current=>current===saved.text?result?.text||'':current);}}/>}</section>{error&&<div role="alert" className="notebook-error">{error}{!loaded&&<button onClick={()=>setLoadAttempt(value=>value+1)}>메모 다시 불러오기</button>}</div>}</>;
}

export default function MaterialView({session,course,mode='all'}:{session:Session;course?:Course;mode?:'all'|'material'|'note'}){
  if(mode==='all')return <MaterialLibrary session={session} course={course} notePanel={<SessionNote key={session.id} session={session}/>}/>;
  return <div><div hidden={mode==='note'}><MaterialLibrary session={session} course={course}/></div><div hidden={mode==='material'}><SessionNote session={session}/></div></div>;
}
