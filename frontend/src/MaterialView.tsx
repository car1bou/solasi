import React,{useEffect,useState} from 'react';
import NoteAugmentView from './NoteAugmentView';
import MaterialLibrary from './MaterialLibrary';
import {api} from './api';
import {navigate} from './native-lifecycle';
import {useCloseGuard} from './use-close-guard';
import type {Session,Course} from './types';
type Note={text:string;version:number;source_id:string;anchor_ms:number|null};
export default function MaterialView({session,course,mode='all'}:{session:Session;course?:Course;mode?:'all'|'material'|'note'}){
  const [saved,setSaved]=useState<Note|null>(null),[note,setNote]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const [loaded,setLoaded]=useState(false),[loadAttempt,setLoadAttempt]=useState(0);
  useCloseGuard('회차 노트',busy||note!==(saved?.text||''));
  async function refresh(){const result=await api<{note:Note|null}>('/sessions/'+session.id+'/materials');setSaved(result.note);return result.note;}
  useEffect(()=>{let live=true;setError('');api<{note:Note|null}>('/sessions/'+session.id+'/materials').then(result=>{if(live){setSaved(result.note);setNote(result.note?.text||'');setLoaded(true);}}).catch(e=>{if(live)setError(e.message);});return()=>{live=false;};},[session.id,loadAttempt]);
  async function save(){if(!navigate(()=>{},['회차 노트']))return;setBusy(true);setError('');try{await api('/sessions/'+session.id+'/note',{method:'PUT',body:JSON.stringify({text:note})});await refresh();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  return <div className={mode==='all'?'material-grid':''}><div hidden={mode==='note'}><MaterialLibrary session={session} course={course}/></div>{<section className="card" hidden={mode==='material'}><div className="subheading"><h2>회차 노트</h2><span className="muted">{saved?'v'+saved.version:''}</span></div>{!loaded&&!error&&<p role="status">노트 불러오는 중…</p>}<textarea disabled={busy||!loaded} aria-label="회차 노트" rows={12} value={note} onChange={e=>setNote(e.target.value)}/><div className="actions"><button disabled={busy||!loaded||note===(saved?.text||'')} onClick={()=>void save()}>저장</button>{loaded&&note!==(saved?.text||'')&&<button disabled={busy} onClick={()=>setNote(saved?.text||'')}>노트 입력 되돌리기</button>}</div>{saved&&<NoteAugmentView key={saved.source_id} session={session} note={saved} dirty={note!==saved.text} onApplied={async()=>{const result=await refresh();setNote(current=>current===saved.text?result?.text||'':current);}}/>}</section>}{error&&<div role="alert" className="notebook-error">{error}{!loaded&&<button onClick={()=>setLoadAttempt(value=>value+1)}>노트 다시 불러오기</button>}</div>}</div>;
}
