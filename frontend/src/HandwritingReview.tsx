import React,{useEffect,useRef,useState} from 'react';
import {api} from './api';
import SourceLink from './SourceLink';
import {useCloseGuard} from './use-close-guard';
import {inkPath} from './ink';
import {loadReviewDraft,saveReviewDraft} from './handwriting-drafts';
import type {InkStroke,PageDocument} from './types';
import type {Job} from './types';
type Candidate={page_revision:number;id:string;ink_hash:string;status:'candidate'|'approved'|'rejected'|'stale';text:string;approved_text:string|null;source_id:string|null;engine:string;result:{regions:{bbox:number[];text:string}[]}};
function InkPreview({item,path,digest,assetId,page,width,height}:{item:Candidate;path:string;digest:string;assetId:string;page:number;width:number;height:number}){
 const [ink,setInk]=useState<InkStroke[]>([]),[error,setError]=useState('');
 useEffect(()=>{let live=true;api<PageDocument>(path.replace('/handwriting','/document')+'?document_sha256='+digest+'&revision='+item.page_revision).then(doc=>{if(live)setInk(doc.ink);}).catch(e=>{if(live)setError(e.message);});return()=>{live=false;};},[path,digest,item.id,item.page_revision]);
 return <>{error&&<p role="status">원래 필기를 불러오지 못했습니다: {error}</p>}<div className="ink-region-preview"><img alt={page+'쪽 원본과 인식 당시 필기'} src={'/api/assets/'+assetId+'/pages/'+page+'?document_sha256='+digest}/><svg viewBox={'0 0 '+width+' '+height} preserveAspectRatio="none" aria-hidden="true">{ink.map(stroke=><path key={stroke.id} d={inkPath(stroke,width,height)} fill={stroke.color} opacity={stroke.opacity}/>)}{item.result.regions.map((r,n)=><rect key={n} x={r.bbox[0]*width} y={r.bbox[1]*height} width={r.bbox[2]*width} height={r.bbox[3]*height}/>)}</svg></div></>;
}
export default function HandwritingReview({courseId,assetId,page,digest,revision,saved,width,height,imported=false}:{courseId:string;assetId:string;page:number;digest:string;revision:number;saved:boolean;width:number;height:number;imported?:boolean}){
 const [items,setItems]=useState<Candidate[]>([]),[drafts,setDrafts]=useState<Record<string,string>>({}),[job,setJob]=useState<Job<{paused_reason?:string}>|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const restored=useRef<Record<string,string>>({}),loaded=useRef(new Set<string>()),writer=useRef(crypto.randomUUID());
 const [draftError,setDraftError]=useState('');
 const path='/courses/'+courseId+'/assets/'+assetId+'/pages/'+page+'/handwriting';
 const dirty=items.some(item=>item.status==='candidate'&&drafts[item.id]!==undefined&&drafts[item.id]!==item.text);
 useCloseGuard('손글씨 인식문 수정',dirty);
 const running=!!job&&['queued','running'].includes(job.status);
 async function readRows(){const rows=await api<Candidate[]>(path+'?document_sha256='+digest);await Promise.all(rows.filter(r=>r.status!=='approved'&&!loaded.current.has(r.id)).map(async r=>{const text=await loadReviewDraft(r.id);if(text!==null)restored.current[r.id]=text;loaded.current.add(r.id);}));return rows;}
 async function persist(item:Candidate,text:string,dirty=true){try{await saveReviewDraft(item.id,text,item.page_revision,writer.current,dirty);setDraftError('');}catch(e){setDraftError('검토 초안 저장 실패: '+(e as Error).message);}}
 async function refresh(){const rows=await readRows();setItems(rows);setDrafts(old=>Object.fromEntries(rows.map(r=>[r.id,old[r.id]??restored.current[r.id]??r.approved_text??r.text])));}
 useEffect(()=>{let live=true,polling=false;async function read(){if(polling)return;polling=true;try{const rows=await readRows();if(live){setItems(rows);setDrafts(old=>Object.fromEntries(rows.map(r=>[r.id,old[r.id]??restored.current[r.id]??r.approved_text??r.text])));}}catch(e){if(live)setError((e as Error).message);}finally{polling=false;}}void read();const timer=setInterval(()=>void read(),3000);return()=>{live=false;clearInterval(timer);};},[path,digest,revision]);
 useEffect(()=>{if(!job||!running)return;let live=true,polling=false;const timer=setInterval(async()=>{if(polling)return;polling=true;try{const row=await api<Job<{paused_reason?:string}>>('/jobs/'+job.id);if(!live)return;setJob(row);if(row.status==='done')await refresh();if(row.error)setError(row.error);}catch(e){if(live)setError((e as Error).message);}finally{polling=false;}},700);return()=>{live=false;clearInterval(timer);};},[job?.id,job?.status,path,digest]);
 async function act(fn:()=>Promise<void>){setBusy(true);setError('');try{await fn();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 return <details className="knowledge-panel"><summary>손글씨 인식·검토{items.some(i=>i.status==='candidate')?' · 확인 대기':''}</summary>
 <p className="muted">{imported?'원본 페이지의 손글씨와 덧쓴 펜 필기를 로컬에서 읽습니다.':'저장된 펜 필기를 로컬에서 읽습니다.'} 확인한 인식문만 검색·답변 근거로 사용합니다. 영문·수식·도형은 원본과 대조하세요. 도형 관계를 자동으로 확정하지 않습니다.</p>
 <button disabled={!saved||busy||running||dirty} onClick={()=>void act(async()=>setJob(await api<Job<{paused_reason?:string}>>(path,{method:'POST',body:JSON.stringify({document_sha256:digest,force:true})})))}>빠른 인식 · Vision</button><button disabled={!saved||busy||running||dirty} onClick={()=>void act(async()=>setJob(await api<Job<{paused_reason?:string}>>(path,{method:'POST',body:JSON.stringify({document_sha256:digest,force:true,engine:'local'})})))}>로컬 Qwen으로 인식</button><p className="muted">로컬 Qwen은 더 오래 걸리며 항상 더 정확한 것은 아닙니다. 자동 처리는 Vision을 사용합니다.</p>
 {!saved&&<p role="status">필기를 저장한 뒤 인식할 수 있습니다.</p>}{running&&<p role="status">{job?.result?.paused_reason||'손글씨 인식 중…'}</p>}{error&&<p role="alert">{error}</p>}{draftError&&<p role="alert">{draftError}</p>}
 {items.map(item=><section key={item.id} className="knowledge-candidate"><p>{({candidate:'검토 대기',approved:'확인한 손글씨',rejected:'거절됨',stale:'필기 변경됨'}[item.status])} · {item.engine}</p>
 <InkPreview item={item} path={path} digest={digest} assetId={assetId} page={page} width={width} height={height}/>
 {item.status==='candidate'?<><label>인식문 확인·수정<textarea value={drafts[item.id]??item.text} onChange={e=>{const text=e.target.value;setDrafts({...drafts,[item.id]:text});void persist(item,text);}} maxLength={200000} rows={4}/></label>{!item.text&&<p>읽은 글자가 없습니다. 원본을 확인해 입력하거나 거절하세요.</p>}<div className="actions"><button disabled={busy||!saved||!(drafts[item.id]??'').trim()} onClick={()=>void act(async()=>{await api('/courses/'+courseId+'/handwriting/'+item.id+'/approve',{method:'PUT',body:JSON.stringify({text:drafts[item.id],expected_ink_hash:item.ink_hash})});await persist(item,drafts[item.id],false);await refresh();})}>확인하고 지식에 추가</button><button disabled={busy} onClick={()=>void act(async()=>{await api('/courses/'+courseId+'/handwriting/'+item.id+'/reject',{method:'POST'});await refresh();})}>거절</button></div></>:<><p className="muted">{item.approved_text!==null?'확인한 인식문':drafts[item.id]!==undefined&&drafts[item.id]!==item.text?'보존된 검토 초안 · 지식에 반영되지 않음':'원래 인식문'}</p><pre className="source-text">{item.approved_text??drafts[item.id]??item.text}</pre></>}
 {item.source_id&&<SourceLink id={item.source_id} label="당시 필기·인식문 확인"/>}</section>)}
 </details>;
}
