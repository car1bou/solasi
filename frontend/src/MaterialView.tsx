import React,{useEffect,useState} from 'react';
import NoteAugmentView from './NoteAugmentView';
import MaterialLibrary from './MaterialLibrary';
import {api} from './api';
import type {Session,Course} from './types';
type Note={text:string;version:number;source_id:string;anchor_ms:number|null};
export default function MaterialView({session,course,mode='all'}:{session:Session;course?:Course;mode?:'all'|'material'|'note'}){
  const [saved,setSaved]=useState<Note|null>(null),[note,setNote]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  async function refresh(){const result=await api<{note:Note|null}>('/sessions/'+session.id+'/materials');setSaved(result.note);return result.note;}
  useEffect(()=>{let live=true;api<{note:Note|null}>('/sessions/'+session.id+'/materials').then(result=>{if(live){setSaved(result.note);setNote(result.note?.text||'');}}).catch(e=>{if(live)setError(e.message);});return()=>{live=false;};},[session.id]);
  async function save(){setBusy(true);setError('');try{await api('/sessions/'+session.id+'/note',{method:'PUT',body:JSON.stringify({text:note})});await refresh();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  return <div className={mode==='all'?'material-grid':''}>{mode!=='note'&&<MaterialLibrary session={session} course={course}/>}{mode!=='material'&&<section className="card"><div className="subheading"><h2>회차 노트</h2><span className="muted">{saved?'v'+saved.version:''}</span></div><textarea aria-label="회차 노트" rows={12} value={note} onChange={e=>setNote(e.target.value)}/><div className="actions"><button disabled={busy||note===(saved?.text||'')} onClick={()=>void save()}>저장</button></div>{saved&&<NoteAugmentView key={saved.source_id} session={session} note={saved} dirty={note!==saved.text} onApplied={async()=>{const result=await refresh();setNote(current=>current===saved.text?result?.text||'':current);}}/>}</section>}{error&&<p role="alert" className="notebook-error">{error}</p>}</div>;
}
