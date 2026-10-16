import React,{useEffect,useRef,useState} from 'react';
import {api} from './api';
import type {Asset,Course,DocumentMetadata,Session} from './types';
import PageNotebook from './PageNotebook';
import {navigate} from './native-lifecycle';
import QuestionView from './QuestionView';
import {materialView,rememberMaterialView,connectedMaterialView} from './material-selection';
const sources:Record<string,string>={current:'',changed:'원본 변경',missing:'파일 없음',denied:'접근 권한 필요'};
const statuses:Record<string,string>={queued:'대기',running:'추출 중',ready:'추출됨',partial:'일부 추출',failed:'추출 실패',stale:'원본 변경 · 재추출 필요'};
export default function MaterialLibrary({session,course}:{session?:Session;course?:Course}){
  const path=session?'/sessions/'+session.id:'/courses/'+course!.id;
  const [view,setView]=useState(()=>materialView(path)),{selected,page}=view;
  const [assets,setAssets]=useState<Asset[]>([]),[metadata,setMetadata]=useState<DocumentMetadata|null>(null),[question,setQuestion]=useState<'explain'|'answer'|'summary'|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[documentLoading,setDocumentLoading]=useState(false);
  useEffect(()=>{rememberMaterialView(path,view);},[path,view]);
  function setPage(next:number|((current:number)=>number)){setView(current=>({...current,page:typeof next==='function'?next(current.page):next}));}
  function selectMaterial(id:string){if(selected!==id)navigate(()=>{setView({selected:id,page:1});setQuestion(null);});}
  const metadataGeneration=useRef(0),currentMetadata=useRef<DocumentMetadata|null>(null);
  const asset=assets.find(row=>row.id===selected),documentPage=metadata?.pages.find(row=>row.page===page);
  async function refresh(){const result=await api<{assets:Asset[]}>(path+'/materials');setAssets(result.assets);return result;}
  useEffect(()=>{let live=true,timer:ReturnType<typeof setTimeout>;async function poll(){try{const result=await api<{assets:Asset[]}>(path+'/materials');if(!live)return;setAssets(result.assets);if(result.assets.some(a=>['queued','running'].includes(a.status)))timer=setTimeout(()=>void poll(),1500);}catch(e){if(live)setError((e as Error).message);}}void poll();return()=>{live=false;clearTimeout(timer);};},[path,busy]);
  async function openDocument(){if(!asset||!['pdf','png','jpg','jpeg'].includes(asset.kind))return;const generation=++metadataGeneration.current;setDocumentLoading(true);setError('');try{const result=await api<DocumentMetadata>('/assets/'+asset.id+'/document');if(metadataGeneration.current!==generation)return;if(currentMetadata.current?.asset_id===asset.id&&currentMetadata.current.sha256!==result.sha256){if(!navigate(()=>{}))return;setError('원본 내용이 변경되어 새 문서를 열었습니다. 이전 버전 메모·필기는 보존되며 새 원본 위에는 표시하지 않습니다.');}currentMetadata.current=result;setMetadata(result);setPage(current=>result.pages.some(row=>row.page===current)?current:result.pages[0]?.page||1);}catch(e){if(metadataGeneration.current===generation){setError((e as Error).message);}}finally{if(metadataGeneration.current===generation)setDocumentLoading(false);}}
  useEffect(()=>{if(currentMetadata.current?.asset_id!==selected){setMetadata(null);setQuestion(null);}void openDocument();return()=>{metadataGeneration.current++;};},[selected,asset?.version,asset?.source_status]);
  useEffect(()=>{const check=()=>{if(asset)void openDocument();};window.addEventListener('focus',check);return()=>window.removeEventListener('focus',check);},[asset?.id]);
  async function act(operation:()=>Promise<unknown>){setBusy(true);setError('');try{await operation();await refresh();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  async function connectFiles(){if(!navigate(()=>{}))return;await act(async()=>{const files=await api<{asset:Asset}[]>(path+'/files/select',{method:'POST'});setView(current=>connectedMaterialView(current,files));if(files.length)setQuestion(null);});}
  return <section className="material-library">
    <div className="subheading"><h2>{course&&!session?'과목 자료·필기':'자료'}</h2><button disabled={busy} onClick={()=>void connectFiles()}>{busy?'처리 중…':'파일 연결'}</button></div>
    {error&&<p role="alert" className="notebook-error">{error}</p>}
    {!assets.length&&<div className="empty-state"><h3>자료를 연결하세요</h3><p>PDF 원본을 열고 페이지별 메모·필기를 남길 수 있습니다.</p></div>}
    <ul className="material-list course-material-list">{assets.map(row=><li key={row.id} className={selected===row.id?'selected':''}><div><button className="material-title" aria-pressed={selected===row.id} onClick={()=>selectMaterial(row.id)}>{row.filename}</button><span className="muted">{sources[row.source_status]||statuses[row.status]||row.status}</span></div><div className="material-actions"><a href={'/api/assets/'+row.id+'/original'} target="_blank" rel="noopener noreferrer">원본 열기</a>{(row.status==='failed'||row.status==='partial'||row.status==='stale'||row.source_status==='changed')&&<button disabled={busy} onClick={()=>void act(()=>api(path+'/assets/'+row.id+'/extract',{method:'POST'}))}>재추출</button>}</div>{row.error&&<p role="alert">{row.error} · 원본이 열리면 페이지 보기와 필기를 계속 사용할 수 있습니다.</p>}</li>)}</ul>
    {asset&&<div className="selected-material"><div className="subheading"><h3>{asset.filename}</h3><button onClick={()=>void openDocument()} disabled={documentLoading}>원본 상태 새로고침</button></div>
      {documentLoading&&<p role="status">원본 페이지 확인 중…</p>}
      {metadata&&<><div className="page-navigation"><button disabled={page<=1} onClick={()=>navigate(()=>{setPage(page-1);setQuestion(null);})}>이전 쪽</button><label>페이지<select value={page} onChange={event=>{const next=Number(event.target.value);navigate(()=>{setPage(next);setQuestion(null);});}}>{metadata.pages.map(row=><option key={row.page} value={row.page}>{row.page} / {metadata.total_pages}</option>)}</select></label><button disabled={page>=metadata.total_pages} onClick={()=>navigate(()=>{setPage(page+1);setQuestion(null);})}>다음 쪽</button><span className="muted">원본 {metadata.total_pages}쪽</span></div>
        {documentPage&&(course&&asset.kind==='pdf'?<PageNotebook key={[course.id,asset.id,metadata.sha256,page].join(':')} courseId={course.id} document={metadata} page={documentPage} filename={asset.filename}/>:<div className="page-image original-page"><img alt={asset.filename+' '+page+'쪽 원본'} src={'/api/assets/'+asset.id+'/pages/'+page+'?document_sha256='+metadata.sha256}/>{asset.kind==='pdf'&&!course&&<p className="muted">과목에 속한 강의 자료는 과목의 페이지 메모·필기를 함께 사용합니다.</p>}</div>)}
        <div className="page-ai-actions"><button aria-pressed={question==='explain'} onClick={()=>navigate(()=>setQuestion(question==='explain'?null:'explain'))}>페이지 설명</button><button aria-pressed={question==='answer'} onClick={()=>navigate(()=>setQuestion(question==='answer'?null:'answer'))}>이 페이지에 질문</button>{course&&<button aria-pressed={question==='summary'} onClick={()=>navigate(()=>setQuestion(question==='summary'?null:'summary'))}>자료 전체 요약</button>}</div>
        {question&&documentPage&&<QuestionView key={[asset.id,metadata.sha256,page,question].join(':')} {...(course?{course,scope:{course_id:course.id,mode:'course' as const,asset_id:asset.id,document_sha256:metadata.sha256,...(question!=='summary'?{page}:{})}}:{session,scope:{session_id:session!.id,mode:'current' as const,asset_id:asset.id,page,document_sha256:metadata.sha256}})} kind={question==='explain'?'vision':question} imageId={question==='explain'?documentPage.ref.id:undefined} initialPrompt={question==='answer'?'이 페이지의 핵심 내용을 근거로 답해 주세요.':undefined}/>}
      </>}
      {!metadata&&!documentLoading&&!['pdf','png','jpg','jpeg'].includes(asset.kind)&&<p>텍스트 자료는 원본 열기에서 확인할 수 있고 검색·질문에 사용됩니다.</p>}
    </div>}
  </section>;
}
