import React,{useState} from 'react';
import QuestionView from './QuestionView';
import SourceLink from './SourceLink';
import {api} from './api';
import {navigate} from './native-lifecycle';
import {useCloseGuard} from './use-close-guard';
import type {Session} from './types';

type Note={source_id:string;text:string;anchor_ms:number|null};
export default function NoteAugmentView({session,note,dirty,onApplied}:{session:Session;note:Note;dirty:boolean;onApplied:()=>Promise<void>}){
  const [anchor,setAnchor]=useState(note.anchor_ms),[edited,setEdited]=useState<{id:string;text:string}|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  useCloseGuard('메모 보강 수정',busy||edited!==null);
  return <details><summary>전사로 메모 보강</summary><p>저장 시점 주변의 확정 전사로 보강안을 만듭니다. 원래 메모는 유지합니다.</p>
    <label>메모 시점 (초)<input type="number" min="0" step="0.1" value={anchor===null?'':anchor/1000} onChange={e=>{const next=e.target.value===''?null:Math.round(Number(e.target.value)*1000);navigate(()=>setAnchor(next));}}/></label>
    {dirty&&<p>작성 중인 메모를 먼저 저장하세요.</p>}{anchor===null?<p>메모의 녹음 시점을 입력하세요.</p>:<div hidden={dirty}><QuestionView session={session} kind="note" noteSourceId={note.source_id} anchorMs={anchor} renderArtifact={a=><article><h3>AI 보강안</h3><label>적용할 보강 메모<textarea maxLength={20000} disabled={busy||a.confirmed} value={edited?.id===a.id?edited.text:a.body.addition||''} onChange={e=>setEdited(e.target.value===(a.body.addition||'')?null:{id:a.id,text:e.target.value})} rows={5}/></label>{a.evidence.filter(e=>a.body.evidence_ids?.includes(e.ref.id)).map(e=><SourceLink key={e.ref.id} id={e.ref.id} label={e.label}/>)}<button disabled={busy||a.confirmed} onClick={()=>void(async()=>{setBusy(true);setError('');try{await api('/artifacts/'+a.id+'/apply-note',{method:'POST',body:JSON.stringify({addition:edited?.id===a.id?edited.text:a.body.addition})});setEdited(null);await onApplied();}catch(e){setError((e as Error).message);}finally{setBusy(false);}})()}>{a.confirmed?'적용됨':'확인하고 메모에 추가'}</button></article>}/></div>}
    {edited&&<button disabled={busy} onClick={()=>setEdited(null)}>보강 수정 되돌리기</button>}
    {error&&<p role="alert">{error}</p>}
  </details>;
}
