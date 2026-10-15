import React, {useEffect, useState} from 'react';
import QuestionView from './QuestionView';
import NoteAugmentView from './NoteAugmentView';
import {api} from './api';
import type {Session, Asset, PageContent} from './types';

type Materials = {assets:Asset[];note:{text:string;version:number;source_id:string;anchor_ms:number|null}|null};
const sources:Record<string,string> = {current:'',changed:'원본 변경',missing:'파일 없음',denied:'접근 권한 필요'};
const statuses:Record<string,string> = {queued:'대기',running:'추출 중',ready:'추출됨',partial:'일부 추출',failed:'추출 실패'};
export default function MaterialView({session,mode='all'}:{session:Session;mode?:'all'|'material'|'note'}) {
  const [materials,setMaterials] = useState<Materials>({assets:[],note:null});
  const [note,setNote] = useState('');
  const [error,setError] = useState('');
  const [busy,setBusy] = useState(false);
  const [selected,setSelected] = useState<{asset:Asset;page:PageContent}|null>(null);
  const [vision,setVision]=useState<string|null>(null);
  const [box,setBox] = useState<number[]|null>(null);
  async function refresh() {
    const result = await api<Materials>('/sessions/'+session.id+'/materials');
    setMaterials(result);
    setSelected(previous=>previous&&result.assets.find(a=>a.id===previous.asset.id)?.version!==previous.asset.version?null:previous);
    return result;
  }
  useEffect(()=>{
    let active = true;
    let timer:ReturnType<typeof setTimeout>;
    async function poll(first=false) {
      try {
        const result = await api<Materials>('/sessions/'+session.id+'/materials');
        if (!active) return;
        setMaterials(result);
        setSelected(previous=>previous&&result.assets.find(a=>a.id===previous.asset.id)?.version!==previous.asset.version?null:previous);
        if (first) setNote(result.note?.text||'');
        timer = setTimeout(()=>void poll(),1500);
      } catch (e) {if(active)setError((e as Error).message);}
    }
    void poll(true);
    return ()=>{active=false;clearTimeout(timer);};
  },[session.id]);
  async function connectFiles() {
    setBusy(true);setError('');
    try {await api('/sessions/'+session.id+'/files/select',{method:'POST'});await refresh();}
    catch(e){setError((e as Error).message);}
    finally{setBusy(false);}
  }
  async function save() {
    setBusy(true);setError('');
    try{await api('/sessions/'+session.id+'/note',{method:'PUT',body:JSON.stringify({text:note})});await refresh();}
    catch(e){setError((e as Error).message);}
    finally{setBusy(false);}
  }
  async function retry(asset:Asset) {
    setError('');
    try {
      await api('/sessions/'+session.id+'/assets/'+asset.id+'/extract',{method:'POST'});
      await refresh();
    }catch(e){setError((e as Error).message);}
  }
  return <div className="material-grid">
    {mode!=='note'&&<section className="card">
      <div className="subheading"><h2>자료</h2><button disabled={busy} onClick={()=>void connectFiles()}>파일 연결</button></div>
      <ul className="material-list">{materials.assets.map(asset=><li key={asset.id}>
        <div className="subheading"><a href={'/api/assets/'+asset.id+'/original'} target="_blank" rel="noopener noreferrer">{asset.filename}</a><span className="muted">{sources[asset.source_status]||statuses[asset.status]||asset.status}</span></div>
        {asset.error&&<p role="alert">{asset.error}</p>}
        {(asset.status==='failed'||asset.status==='partial'||asset.source_status==='changed')&&<button onClick={()=>void retry(asset)}>재추출</button>}
        {asset.extraction?.pages.map(page=><button className="page-button" key={page.page} onClick={()=>{setSelected({asset,page});setBox(null);setVision(null);}}>{page.page}쪽</button>)}
        {asset.extraction?.page_errors.map((e,i)=><p className="muted" key={i}>{e.page?e.page+'쪽 · ':''}{e.message}</p>)}
      </li>)}</ul>
      {selected&&<div className="page-view">
        <div className="subheading"><h3>{selected.asset.filename} · {selected.page.page}쪽</h3><button aria-label="페이지 닫기" onClick={()=>setSelected(null)}>×</button></div>
        {['pdf','png','jpg'].includes(selected.asset.kind)&&materials.assets.find(a=>a.id===selected.asset.id)?.source_status==='current'&&<div className="page-image">
          <img alt={selected.asset.filename+' '+selected.page.page+'쪽'} src={'/api/assets/'+selected.asset.id+'/pages/'+selected.page.page}/>
          {box&&selected.page.width>0&&<span className="source-box" style={{left:100*box[0]/selected.page.width+'%',top:100*box[1]/selected.page.height+'%',width:100*box[2]/selected.page.width+'%',height:100*box[3]/selected.page.height+'%'}}/>}
      </div>}
        {['pdf','png','jpg'].includes(selected.asset.kind)&&<div><button onClick={()=>setVision(selected.page.ref.id)}>이 페이지에 질문</button>{selected.asset.extraction?.images.filter(image=>image.ref.page===selected.page.page).map(image=><button key={image.id} onClick={()=>{setBox(image.ref.bbox||null);setVision(image.ref.id);}}>그림 {Number(image.id)+1}에 질문</button>)}</div>}
        {vision&&<QuestionView key={vision} session={session} kind="vision" imageId={vision}/>}
        {selected.page.items.some(item=>item.confidence!==null)&&<span className="badge">OCR</span>}
        <pre className="source-text">{selected.page.text}</pre>
        {selected.page.items.map((item,i)=><button className="text-item" key={i} onClick={()=>setBox(item.bbox)}>{item.text}</button>)}
      </div>}
    </section>}
    {mode!=='material'&&<section className="card"><div className="subheading"><h2>노트</h2><span className="muted">{materials.note?'v'+materials.note.version:''}</span></div>
      <textarea aria-label="노트" rows={12} value={note} onChange={e=>setNote(e.target.value)}/>
      <div className="actions"><button disabled={busy||note===(materials.note?.text||'')} onClick={()=>void save()}>저장</button></div>
      {materials.note&&<NoteAugmentView key={materials.note.source_id} session={session} note={materials.note} dirty={note!==materials.note.text} onApplied={async()=>{const result=await refresh();setNote(current=>current===materials.note?.text?result.note?.text||'':current);}}/>}
    </section>}
    {error&&<p role="alert" className="error-banner">{error}</p>}
  </div>;
}
