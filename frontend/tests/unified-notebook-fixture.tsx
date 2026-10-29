// Isolated QA harness: production UI + real IndexedDB; synthetic API documents and audio only.
import React,{useEffect,useState} from 'react';
import {createRoot} from 'react-dom/client';
import MaterialView from '../src/MaterialView';
import {EmptyTranscriptRange,TranscriptScript} from '../src/TranscriptView';
import {navigate} from '../src/native-lifecycle';
import {pageDraft,flushPageDrafts} from '../src/page-drafts';
import {rememberMaterialView} from '../src/material-selection';
import type {Asset,Course,DocumentMetadata,PageDocument,Session} from '../src/types';
import '../src/styles.css';

const course:Course={id:'f'.repeat(32),title:'Synthetic QA course',description:'Fixture only'};
const session:Session={id:'e'.repeat(32),kind:'lecture',title:'통합 PDF 노트 검증',course_id:course.id,lecture_no:1,started_at:'2026-10-29T09:00:00Z',recording_status:'stopped'};
const asset:Asset={id:'d'.repeat(32),filename:'QA Synthetic Two Pages.pdf',kind:'pdf',version:1,status:'ready',source_status:'current',error:null,extraction:null};
const hash='c'.repeat(64),storageKey='solasi-unified-notebook-qa-20261029';
const metadata:DocumentMetadata={asset_id:asset.id,sha256:hash,total_pages:2,pages:[1,2].map(page=>({page,width:600,height:800,rotation:0,ref:{id:'qa-page-'+page,kind:'material',version:1,asset_id:asset.id,page,document_sha256:hash}}))};
type Remote={pages:PageDocument[];history:PageDocument[];note:{text:string;version:number;source_id:string;anchor_ms:null}};
function initial():Remote{return {pages:[1,2].map(page=>({id:'qa-document-'+page,course_id:course.id,asset_id:asset.id,document_sha256:hash,page,revision:1,text:page===1?'기존 1쪽 메모: 이 내용은 글상자와 별도 보존됩니다.':'기존 2쪽 메모',ink:page===1?[{id:'qa-existing-pen',tool:'pen',color:'#2563eb',width:.005,opacity:1,input:'pen',points:[{x:.13,y:.30,pressure:.5},{x:.32,y:.35,pressure:.7},{x:.47,y:.30,pressure:.5}]}]:[],source_id:'qa-page-note-'+page,updated_at:'2026-10-29T09:00:00Z'})),history:[],note:{text:'기존 회차 노트: PDF 페이지 메모와 분리된 버전입니다.',version:1,source_id:'qa-session-note-v1',anchor_ms:null}};}
const remote:Remote=JSON.parse(localStorage.getItem(storageKey)||'null')||initial();
const persist=()=>localStorage.setItem(storageKey,JSON.stringify(remote));persist();
let offline=false,delaySources=false;
const pendingSources:(()=>void)[]=[],requests:string[]=[];
function quietWav(){const count=8000*30,buffer=new ArrayBuffer(44+count*2),view=new DataView(buffer);const text=(offset:number,value:string)=>[...value].forEach((c,i)=>view.setUint8(offset+i,c.charCodeAt(0)));text(0,'RIFF');view.setUint32(4,36+count*2,true);text(8,'WAVE');text(12,'fmt ');view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,8000,true);view.setUint32(28,16000,true);view.setUint16(32,2,true);view.setUint16(34,16,true);text(36,'data');view.setUint32(40,count*2,true);return URL.createObjectURL(new Blob([buffer],{type:'audio/wav'}));}
const wav=quietWav();
const json=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json'}});
window.fetch=async(input,options={})=>{
  const raw=input instanceof Request?input.url:String(input),url=new URL(raw,location.href),path=url.pathname,method=options.method||'GET';
  if(url.origin!==location.origin||!path.startsWith('/api/'))throw new Error('Fixture blocks external or unexpected fetch: '+url.href);
  if(offline)throw new TypeError('QA: synthetic API is offline; IndexedDB remains available.');
  requests.push(method+' '+path);if(requests.length>30)requests.shift();
  if(path==='/api/client'||path==='/api/bootstrap')return json({csrf_token:'fixture-token'});
  if(path===`/api/sessions/${session.id}/materials`)return json({assets:[asset],note:remote.note});
  if(path===`/api/assets/${asset.id}/document`)return json(metadata);
  const pagePath=path.match(new RegExp(`^/api/courses/${course.id}/assets/${asset.id}/pages/([12])/document$`));
  if(pagePath){const page=Number(pagePath[1]),current=remote.pages[page-1];
    if(method==='GET'){const revision=Number(url.searchParams.get('revision'));return json(revision?remote.history.find(row=>row.page===page&&row.revision===revision)||current:current);}
    if(method==='PUT'){const body=JSON.parse(String(options.body));if(body.document_sha256!==hash||body.expected_revision!==current.revision)return json({detail:'Fixture revision conflict'},409);remote.history.push(structuredClone(current));const next={...current,text:body.text,ink:body.ink,revision:current.revision+1,updated_at:new Date().toISOString()};remote.pages[page-1]=next;persist();return json(next);}
  }
  if(path===`/api/sessions/${session.id}/note`&&method==='PUT'){const body=JSON.parse(String(options.body)),version=remote.note.version+1;remote.note={text:body.text,version,source_id:'qa-session-note-v'+version,anchor_ms:null};persist();return json(remote.note);}
  if(path.endsWith('/handwriting')&&method==='GET')return json([]);
  if(path==='/api/knowledge/suggestions')return json([]);
  if(path.startsWith('/api/sources/qa-segment-')){if(delaySources)await new Promise<void>(resolve=>pendingSources.push(resolve));const second=path.includes('second');return json({open_url:wav,seek_seconds:second?6:2,end_seconds:second?8:4});}
  return json({detail:'Fixture endpoint intentionally unavailable: '+method+' '+path+' (no model or real vault)'},501);
};
rememberMaterialView('/sessions/'+session.id,{selected:asset.id,page:1});
const segments=[{id:'qa-segment-first',chunk_id:'qa-chunk-1',recording_id:'qa-recording',start_ms:2000,end_ms:4000,text:'첫 번째 합성 전사 구간.',original_text:'첫 번째 합성 전사 구간.',revision:1,final:1},{id:'qa-segment-second',chunk_id:'qa-chunk-2',recording_id:'qa-recording',start_ms:6000,end_ms:8000,text:'두 번째 합성 전사 구간.',original_text:'두 번째 합성 전사 구간.',revision:1,final:1}];
function Fixture(){
  const [tab,setTab]=useState<'notebook'|'audio'>('notebook'),[message,setMessage]=useState(''),[trace,setTrace]=useState(''),[isOffline,setOffline]=useState(false),[isDelayed,setDelayed]=useState(false);
  useEffect(()=>{const blocked=(event:Event)=>setMessage((event as CustomEvent<string>).detail),moved=()=>setMessage('Navigation succeeded; playback interruption event emitted.');window.addEventListener('solasi-navigation-blocked',blocked);window.addEventListener('solasi-navigated',moved);const timer=setInterval(()=>{const drafts=[1,2].map(page=>{const state=pageDraft(course.id,asset.id,hash,page).snapshot();return {page,loaded:state.loaded,status:state.status,revision:state.revision,memo:state.text,penIds:state.ink.filter(s=>s.tool!=='text').map(s=>s.id),textBoxes:state.ink.filter(s=>s.tool==='text'),recovered:state.recovered.length,error:state.error};});const audio=[...document.querySelectorAll('audio')].map(a=>({label:a.getAttribute('aria-label'),paused:a.paused,time:Number(a.currentTime.toFixed(2)),volume:a.volume,readyState:a.readyState}));setTrace(JSON.stringify({observedCurrentPage:(document.querySelector('.page-jump input') as HTMLInputElement|null)?.value||null,offline,pendingSourceReplies:pendingSources.length,audio,drafts,remotePages:remote.pages.map(p=>({page:p.page,revision:p.revision,text:p.text,ink:p.ink})),remoteSessionNote:remote.note,remoteHistoryCount:remote.history.length,recentRequests:requests.slice(-10)},null,2));},350);return()=>{clearInterval(timer);window.removeEventListener('solasi-navigation-blocked',blocked);window.removeEventListener('solasi-navigated',moved);};},[]);
  return <main id="workspace" style={{maxWidth:1280,margin:'0 auto',padding:'16px'}}><h1>통합 노트 · 합성 QA 보관함</h1><p>실제 MaterialView·PageNotebook·PlaybackAudio / 합성 2쪽 PDF 이미지 / 합성 무음 WAV 30초 / 이 브라우저의 실제 IndexedDB. 실제 보관함·녹음·모델·외부 요청 없음.</p>
    <div role="tablist" aria-label="QA 화면" className="segmented session-tabs"><button role="tab" aria-selected={tab==='notebook'} onClick={()=>{if(tab!=='notebook')navigate(()=>setTab('notebook'));}}>통합 노트</button><button role="tab" aria-selected={tab==='audio'} onClick={()=>{if(tab!=='audio')navigate(()=>setTab('audio'));}}>빈 전사 · 재생 검증</button></div>
    {message&&<p role="status">{message}</p>}
    <div hidden={tab!=='notebook'}><MaterialView course={course} session={session}/></div>
    <div hidden={tab!=='audio'}><section className="card"><h2>실제 빈 전사 컴포넌트</h2><p>구간을 펼쳐 재생한 뒤 통합 노트로 이동하고 trace의 paused를 확인하세요.</p><EmptyTranscriptRange range={{id:'qa-empty',start_ms:0,end_ms:30000,audio_url:wav,seek_seconds:0}} reviews={[]} review={async()=>{setMessage('Fixture: inference disabled; no model ran.');}}/></section><section className="card"><h2>실제 전사 선택 · 연속 재생</h2><p>문장을 선택해 듣기를 누르세요. 아래 source 응답 지연을 켜고 듣기 → 노트 이동 → 지연 해제로 숨겨진 async 결과를 확인할 수 있습니다.</p><TranscriptScript sessionId={session.id} segments={segments} reviews={[]} refresh={async()=>{}} review={async()=>{}}/></section></div>
    <details style={{marginTop:20,border:'1px solid var(--line)',padding:12}}><summary>QA 결함 주입 · 저장소 trace</summary><div className="actions"><button onClick={()=>{document.documentElement.dataset.theme='light';}}>QA 라이트</button><button onClick={()=>{document.documentElement.dataset.theme='dark';}}>QA 다크</button><button onClick={()=>{offline=!offline;setOffline(offline);}}>합성 API {isOffline?'온라인 복원':'오프라인 전환'}</button><button onClick={()=>{delaySources=!delaySources;setDelayed(delaySources);if(!delaySources)pendingSources.splice(0).forEach(resolve=>resolve());}}>source 응답 {isDelayed?'지연 해제':'지연 켜기'}</button><button onClick={()=>{void flushPageDrafts().then(()=>setMessage('실제 IndexedDB 초안 저장 완료')).catch(error=>setMessage(String(error)));}}>IndexedDB 초안 flush</button><button onClick={()=>{void flushPageDrafts().then(()=>{offline=false;location.reload();}).catch(error=>setMessage(String(error)));}}>초안 flush 후 온라인 새로고침</button></div><p>아래 값은 실제 DOM·PageDraft snapshot·합성 원격 저장소 관측값입니다. PASS를 자동 선언하지 않습니다. 오프라인은 API 요청에만 적용되고 페이지 이미지·IndexedDB는 유지됩니다.</p><pre id="qa-trace" style={{maxHeight:520,overflow:'auto',fontSize:12,whiteSpace:'pre-wrap'}}>{trace}</pre></details>
  </main>;
}
createRoot(document.getElementById('root')!).render(<Fixture/>);
