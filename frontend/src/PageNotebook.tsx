import React,{useEffect,useId,useMemo,useRef,useState,useSyncExternalStore} from 'react';
import type {DocumentMetadata,DocumentPage,InkPoint,InkStroke} from './types';
import {pageDraft} from './page-drafts';
import {clamp,eraseInk,inkBounds,inkPath,inside} from './ink';
import type {Bounds,Point} from './ink';

type Tool='pen'|'highlighter'|'stroke-eraser'|'partial-eraser'|'lasso'|'pan';
type Gesture={id:number;kind:Tool|'move'|'resize';origin:Point;base:InkStroke[];work:InkStroke[];stroke?:InkStroke;polygon:Point[];bounds?:Bounds;screen:Point;scroll:Point};
const InkMark=React.memo(function InkMark({stroke,width,height}:{stroke:InkStroke;width:number;height:number}){return <path d={inkPath(stroke,width,height)} fill={stroke.color} opacity={stroke.opacity} pointerEvents="none"/>;});
const labels:Record<Tool,string>={pen:'펜',highlighter:'형광펜','stroke-eraser':'획 지우기','partial-eraser':'부분 지우기',lasso:'올가미',pan:'이동'};
const statusLabels={loading:'불러오는 중',saved:'저장됨',pending:'저장 대기',saving:'저장 중',failed:'저장 실패 · 초안 보존',conflict:'충돌 · 초안 보존'};
function download(filename:string,value:unknown){const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'})),anchor=document.createElement('a');anchor.href=url;anchor.download=filename;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
export default function PageNotebook({courseId,document:metadata,page,filename}:{courseId:string;document:DocumentMetadata;page:DocumentPage;filename:string}){
  const noteId=useId();
  const store=useMemo(()=>pageDraft(courseId,metadata.asset_id,metadata.sha256,page.page),[courseId,metadata.asset_id,metadata.sha256,page.page]);
  const state=useSyncExternalStore(store.subscribe,store.snapshot),latest=useRef(state),lastOwnInk=useRef<InkStroke[]|null>(null);latest.current=state;
  const [tool,setTool]=useState<Tool>('pen'),[color,setColor]=useState('#254f3f'),[width,setWidth]=useState(.0025),[opacity,setOpacity]=useState(1),[eraserSize,setEraserSize]=useState(.014);
  const [zoom,setZoom]=useState(1),[rotation,setRotation]=useState(0),[notesOpen,setNotesOpen]=useState(true),[imageReady,setImageReady]=useState(false),[imageError,setImageError]=useState(''),[inputError,setInputError]=useState('');
  const [preview,setPreview]=useState<InkStroke[]|null>(null),[liveStroke,setLiveStroke]=useState<InkStroke|null>(null),[polygon,setPolygon]=useState<Point[]>([]),[selected,setSelected]=useState<string[]>([]);
  const [history,setHistory]=useState<{past:InkStroke[][];future:InkStroke[][]}>({past:[],future:[]});
  const svg=useRef<SVGSVGElement>(null),viewport=useRef<HTMLDivElement>(null),gesture=useRef<Gesture|null>(null),touches=useRef(new Map<number,Point>()),pinch=useRef<{distance:number;zoom:number}|null>(null);
  const displayed=preview||state.ink,selection=inkBounds(displayed.filter(stroke=>selected.includes(stroke.id)));
  useEffect(()=>{if(state.ink!==lastOwnInk.current){cancelGesture();setHistory({past:[],future:[]});setSelected([]);}},[state.ink]);
  useEffect(()=>{const refresh=()=>{void store.refresh();};window.addEventListener('focus',refresh);return()=>window.removeEventListener('focus',refresh);},[store]);
  useEffect(()=>{const flush=()=>{void store.save();};const before=(event:BeforeUnloadEvent)=>{flush();if(!['saved','loading'].includes(store.state.status)){event.preventDefault();event.returnValue='';}};const cancel=()=>cancelGesture();window.addEventListener('beforeunload',before);window.addEventListener('blur',cancel);return()=>{flush();window.removeEventListener('beforeunload',before);window.removeEventListener('blur',cancel);};},[store]);
  function commit(ink:InkStroke[],base=latest.current.ink){
    if(base!==latest.current.ink){cancelGesture();setInputError('다른 창의 필기가 갱신되어 진행 중이던 입력을 취소했습니다. 최신 내용에서 다시 입력하세요.');return;}
    if(JSON.stringify(ink)===JSON.stringify(base))return;
    if(ink.length>2000||ink.reduce((sum,s)=>sum+s.points.length,0)>100000){setInputError('페이지당 2,000획·10만 점까지 저장할 수 있습니다. 일부 필기를 지우거나 다른 페이지를 사용하세요.');return;}
    lastOwnInk.current=ink;setHistory(current=>({past:[...current.past.slice(-39),base],future:[]}));store.change({text:latest.current.text,ink});
  }
  function undo(redo=false){if(gesture.current)return;if(latest.current.ink!==lastOwnInk.current){setHistory({past:[],future:[]});return;}const from=redo?history.future:history.past;if(!from.length)return;const current=latest.current.ink,ink=from[from.length-1];setHistory(redo?{past:[...history.past,current],future:from.slice(0,-1)}:{past:from.slice(0,-1),future:[...history.future,current]});setSelected([]);lastOwnInk.current=ink;store.change({text:latest.current.text,ink});}
  useEffect(()=>{function key(event:KeyboardEvent){if(!viewport.current?.getClientRects().length)return;const element=event.target as HTMLElement;if(element.closest('input,textarea,select,[contenteditable="true"]'))return;if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==='z'){event.preventDefault();undo(event.shiftKey);}if(event.key==='Escape'){cancelGesture();setSelected([]);}}window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key);});
  function coordinates(event:{clientX:number;clientY:number}):Point{const matrix=svg.current?.getScreenCTM();if(!matrix)return{x:0,y:0};const point=new DOMPoint(event.clientX,event.clientY).matrixTransform(matrix.inverse());return{x:clamp(point.x/page.width),y:clamp(point.y/page.height)};}
  function inkPoint(event:PointerEvent|React.PointerEvent):InkPoint{return{...coordinates(event),pressure:event.pointerType==='pen'?clamp(event.pressure):.5,...(event.pointerType==='pen'?{tilt_x:clamp(event.tiltX,-90,90),tilt_y:clamp(event.tiltY,-90,90)}:{})};}
  function cancelGesture(){gesture.current=null;setPreview(null);setLiveStroke(null);setPolygon([]);touches.current.clear();pinch.current=null;}
  function down(event:React.PointerEvent<SVGSVGElement>){
    if(!state.loaded||!imageReady)return;
    if(event.pointerType==='touch'){
      if(gesture.current?.stroke?.input==='pen')return;
      touches.current.set(event.pointerId,{x:event.clientX,y:event.clientY});
      if(touches.current.size===2){const [a,b]=[...touches.current.values()];pinch.current={distance:Math.hypot(a.x-b.x,a.y-b.y),zoom};gesture.current=null;setPreview(null);setLiveStroke(null);setPolygon([]);event.currentTarget.setPointerCapture(event.pointerId);event.preventDefault();return;}
    }else if(gesture.current)return;
    event.preventDefault();event.currentTarget.setPointerCapture(event.pointerId);setInputError('');
    const origin=coordinates(event),eraser=event.button===2||event.button===5||(event.buttons&32)!==0;
    let kind:Gesture['kind']=event.pointerType==='touch'?'pan':eraser?'stroke-eraser':tool;
    const role=(event.target as SVGElement).getAttribute('data-action');
    if(kind==='lasso'&&selection&&role)kind=role==='resize'?'resize':'move';
    const next:Gesture={id:event.pointerId,kind,origin,base:state.ink,work:state.ink,polygon:[origin],screen:{x:event.clientX,y:event.clientY},scroll:{x:viewport.current?.scrollLeft||0,y:viewport.current?.scrollTop||0},bounds:selection||undefined};
    if(kind==='pen'||kind==='highlighter'){
      if(state.ink.length>=2000||state.ink.reduce((sum,s)=>sum+s.points.length,0)>=100000){setInputError('페이지 필기 한도에 도달했습니다. 일부 필기를 지워 주세요.');return;}
      next.stroke={id:crypto.randomUUID(),tool:kind,color,width,opacity,input:event.pointerType==='pen'?'pen':'mouse',points:[inkPoint(event)]};setLiveStroke(next.stroke);
    }else if(kind==='stroke-eraser'||kind==='partial-eraser'){next.work=eraseInk(next.work,origin,eraserSize,kind==='partial-eraser',page.height/page.width);setPreview(next.work);}
    else if(kind==='lasso'){setSelected([]);setPolygon([origin]);}
    gesture.current=next;
  }
  function move(event:React.PointerEvent<SVGSVGElement>){
    if(event.pointerType==='touch'&&touches.current.has(event.pointerId)){
      touches.current.set(event.pointerId,{x:event.clientX,y:event.clientY});
      if(touches.current.size>=2&&pinch.current){const [a,b]=[...touches.current.values()];setZoom(clamp(pinch.current.zoom*Math.hypot(a.x-b.x,a.y-b.y)/Math.max(1,pinch.current.distance),.5,3));event.preventDefault();return;}
    }
    const g=gesture.current;if(!g||g.id!==event.pointerId)return;event.preventDefault();
    const point=coordinates(event);
    if(g.kind==='pan'){if(viewport.current){viewport.current.scrollLeft=g.scroll.x-(event.clientX-g.screen.x);viewport.current.scrollTop=g.scroll.y-(event.clientY-g.screen.y);}return;}
    if(g.stroke){
      const coalesced=event.nativeEvent.getCoalescedEvents?.(),samples=coalesced?.length?coalesced:[event.nativeEvent],points=[...g.stroke.points],used=g.base.reduce((sum,s)=>sum+s.points.length,0);
      for(const sample of samples){const next=inkPoint(sample),last=points[points.length-1];if(Math.hypot((next.x-last.x)*page.width,(next.y-last.y)*page.height)>.35&&used+points.length<100000)points.push(next);}
      g.stroke={...g.stroke,points};setLiveStroke(g.stroke);
    }else if(g.kind==='stroke-eraser'||g.kind==='partial-eraser'){const distance=Math.hypot(point.x-g.origin.x,(point.y-g.origin.y)*page.height/page.width),steps=Math.max(1,Math.ceil(distance/(eraserSize*.6)));for(let i=1;i<=steps;i++)g.work=eraseInk(g.work,{x:g.origin.x+(point.x-g.origin.x)*i/steps,y:g.origin.y+(point.y-g.origin.y)*i/steps},eraserSize,g.kind==='partial-eraser',page.height/page.width);g.origin=point;setPreview(g.work);}
    else if(g.kind==='lasso'){g.polygon=[...g.polygon,point];setPolygon(g.polygon);}
    else if(g.bounds){const bounds=g.bounds,dx=clamp(point.x-g.origin.x,-bounds.x,1-bounds.x-bounds.width),dy=clamp(point.y-g.origin.y,-bounds.y,1-bounds.y-bounds.height),sx=clamp((point.x-bounds.x)/bounds.width,.05,(1-bounds.x)/bounds.width),sy=clamp((point.y-bounds.y)/bounds.height,.05,(1-bounds.y)/bounds.height);g.work=g.base.map(stroke=>selected.includes(stroke.id)?{...stroke,points:stroke.points.map(p=>({...p,x:clamp(g.kind==='move'?p.x+dx:bounds.x+(p.x-bounds.x)*sx),y:clamp(g.kind==='move'?p.y+dy:bounds.y+(p.y-bounds.y)*sy)}))}:stroke);setPreview(g.work);}
  }
  function up(event:React.PointerEvent<SVGSVGElement>){
    touches.current.delete(event.pointerId);if(touches.current.size<2)pinch.current=null;
    const g=gesture.current;if(!g||g.id!==event.pointerId)return;gesture.current=null;
    if(g.stroke)commit([...g.base,g.stroke],g.base);else if(g.kind==='lasso')setSelected(g.base.filter(stroke=>stroke.points.some(point=>inside(point,g.polygon))).map(stroke=>stroke.id));else if(g.kind!=='pan')commit(g.work,g.base);
    setPreview(null);setLiveStroke(null);setPolygon([]);
  }
  function chooseTool(value:Tool){cancelGesture();setTool(value);if(value==='pen'){setWidth(.0025);setOpacity(1);}if(value==='highlighter'){setWidth(.018);setOpacity(.35);}if(value!=='lasso')setSelected([]);}
  const baseWidth=680*zoom,baseHeight=baseWidth*page.height/page.width,swapped=rotation%180!==0;
  return <section className="page-notebook" aria-label={filename+' '+page.page+'쪽 메모와 필기'}>
    <div className="notebook-heading"><strong>{page.page}쪽</strong><span role="status" className={'save-status '+state.status}>{statusLabels[state.status]}{state.revision>0?' · v'+state.revision:''}</span><button disabled={!state.loaded||state.status==='saved'||state.status==='conflict'} onClick={()=>void store.save()}>지금 저장</button><button aria-expanded={notesOpen} onClick={()=>setNotesOpen(!notesOpen)}>{notesOpen?'메모 접기':'메모 열기'}</button></div>
    <div className="ink-toolbar" role="toolbar" aria-label="필기 도구">
      {(Object.keys(labels) as Tool[]).map(value=><button key={value} aria-pressed={tool===value} onClick={()=>chooseTool(value)}>{labels[value]}</button>)}
      <button aria-label="필기 실행 취소" disabled={!history.past.length} onClick={()=>undo()}>↶</button><button aria-label="필기 다시 실행" disabled={!history.future.length} onClick={()=>undo(true)}>↷</button>
      <label>색<input type="color" value={color} onChange={e=>setColor(e.target.value)}/></label><label>굵기<input type="range" min="0.0005" max="0.04" step="0.0005" value={width} onChange={e=>setWidth(Number(e.target.value))}/></label><label>불투명도<input type="range" min="0.05" max="1" step="0.05" value={opacity} onChange={e=>setOpacity(Number(e.target.value))}/></label>
      {tool.includes('eraser')&&<label>지우개 크기<input type="range" min="0.003" max="0.06" step="0.001" value={eraserSize} onChange={e=>setEraserSize(Number(e.target.value))}/></label>}
      <label>확대<select value={zoom} onChange={e=>setZoom(Number(e.target.value))}>{[.5,.75,1,1.25,1.5,2,3].map(value=><option key={value} value={value}>{Math.round(value*100)}%</option>)}{![.5,.75,1,1.25,1.5,2,3].includes(zoom)&&<option value={zoom}>{Math.round(zoom*100)}%</option>}</select></label><button onClick={()=>{cancelGesture();setRotation(value=>(value+90)%360);}}>회전 {rotation}°</button>
      {!!selected.length&&<button onClick={()=>{commit(state.ink.filter(stroke=>!selected.includes(stroke.id)));setSelected([]);}}>선택 {selected.length}획 삭제</button>}
    </div>
    <p className="ink-help">펜·마우스로 필기 · 손가락으로 이동/두 손가락 확대 · 올가미 선택 후 이동, 오른쪽 아래 점으로 크기 조절 · ⌘Z/⌘⇧Z</p>
    {(state.error||state.storageError||inputError||imageError)&&<div role="alert" className="notebook-error">{state.error&&<p>{state.error}</p>}{state.storageError&&<p>{state.storageError}</p>}{inputError&&<p>{inputError}</p>}{imageError&&<p>{imageError}</p>}{state.status==='failed'&&<button onClick={()=>store.retry()}>다시 불러오기·저장</button>}<button onClick={()=>download('페이지-'+page.page+'-초안.json',{course_id:courseId,asset_id:metadata.asset_id,document_sha256:metadata.sha256,page:page.page,text:state.text,ink:state.ink})}>현재 초안 내보내기</button></div>}
    {state.status==='conflict'&&state.server&&<section className="conflict-panel"><h3>저장 충돌</h3><p>현재 초안과 서버 v{state.server.revision}을 모두 보존합니다. 선택하지 않은 내용은 비교용 사본으로 남깁니다.</p><details><summary>서버 메모·필기 확인</summary><pre className="source-text">{state.server.text||'(빈 메모)'}</pre><p>{state.server.ink.length}획</p><svg className="conflict-ink-preview" viewBox={`0 0 ${page.width} ${page.height}`} aria-label="서버 필기 미리보기">{state.server.ink.map(stroke=><InkMark key={stroke.id} stroke={stroke} width={page.width} height={page.height}/>)}</svg><button onClick={()=>download('서버-페이지-'+page.page+'.json',state.server)}>서버 내용 내보내기</button></details><button onClick={()=>store.resolve(true)}>내 초안을 다음 버전으로 저장</button><button onClick={()=>{store.resolve(false);setHistory({past:[],future:[]});}}>서버 내용 사용</button></section>}
    {!!state.recovered.length&&<details className="draft-backup"><summary>다른 창·이전 실행의 미저장 초안 {state.recovered.length}개 보존됨</summary>{state.recovered.map(draft=><div key={draft.key}><p>{draft.ink.length}획 · {draft.text.length}자{draft.updatedAt?' · '+new Date(draft.updatedAt).toLocaleString('ko-KR'):''}</p><button onClick={()=>download('복구-페이지-'+page.page+'.json',draft)}>초안 내보내기</button><button onClick={()=>{store.recover(draft);setHistory({past:[],future:[]});}}>현재 편집으로 복구</button></div>)}</details>}
    {state.backup&&<details className="draft-backup"><summary>충돌 해결 전 사본 보관됨</summary><p>{state.backup.ink.length}획 · {state.backup.text.length}자</p><button onClick={()=>download('보관-페이지-'+page.page+'.json',state.backup)}>보관 사본 내보내기</button></details>}
    <div className={'notebook-layout'+(notesOpen?'':' notes-closed')}>
      <div className="page-viewport" ref={viewport} onWheel={event=>{if(event.ctrlKey||event.metaKey){event.preventDefault();setZoom(value=>clamp(value*Math.exp(-event.deltaY*.002),.5,3));}}}>
        <div className="page-rotation-frame" style={{width:swapped?baseHeight:baseWidth,height:swapped?baseWidth:baseHeight}}>
          <div className="ink-page" style={{width:baseWidth,height:baseHeight,transform:`translate(-50%,-50%) rotate(${rotation}deg)`}}>
            <img draggable={false} alt={filename+' '+page.page+'쪽 원본'} src={'/api/assets/'+metadata.asset_id+'/pages/'+page.page+'?document_sha256='+encodeURIComponent(metadata.sha256)} onLoad={()=>{setImageReady(true);setImageError('');}} onError={()=>{setImageReady(false);setImageError('원본 페이지를 열 수 없습니다. 파일 접근 권한·원본 변경 상태를 확인하고 자료를 다시 여세요.');}}/>
            {imageReady&&state.loaded&&<svg ref={svg} viewBox={`0 0 ${page.width} ${page.height}`} className={'ink-surface tool-'+tool} onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={cancelGesture} onLostPointerCapture={event=>{if(gesture.current?.id===event.pointerId)cancelGesture();}} onContextMenu={event=>event.preventDefault()} aria-label="페이지 필기 영역" role="img">
              {displayed.map(stroke=><InkMark key={stroke.id} stroke={stroke} width={page.width} height={page.height}/>)}
              {liveStroke&&<path d={inkPath(liveStroke,page.width,page.height)} fill={liveStroke.color} opacity={liveStroke.opacity} pointerEvents="none"/>}
              {!!polygon.length&&<path d={'M'+polygon.map(p=>p.x*page.width+','+p.y*page.height).join('L')} fill="#4a91bb22" stroke="#387ba1" strokeWidth={1.5/zoom} strokeDasharray="5 4" pointerEvents="none"/>}
              {tool==='lasso'&&selection&&<g><rect data-action="move" x={selection.x*page.width-3} y={selection.y*page.height-3} width={selection.width*page.width+6} height={selection.height*page.height+6} fill="#459fcb15" stroke="#387ba1" strokeWidth={1.5/zoom} strokeDasharray="5 4"/><circle data-action="resize" cx={(selection.x+selection.width)*page.width} cy={(selection.y+selection.height)*page.height} r={7/zoom} fill="#387ba1" stroke="white" strokeWidth={1.5/zoom}/></g>}
            </svg>}
          </div>
        </div>
      </div>
      {notesOpen&&<aside className="page-notes"><label htmlFor={noteId}>{page.page}쪽 메모<textarea id={noteId} rows={16} maxLength={200000} disabled={!state.loaded} value={state.text} onChange={event=>store.change({text:event.target.value,ink:state.ink})}/></label><p className="muted">입력한 메모는 과목 검색 근거로 사용됩니다. 손글씨는 별도 잉크로 보관됩니다.</p></aside>}
    </div>
  </section>;
}
