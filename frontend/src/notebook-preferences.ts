import {api,nativeApp} from './api.ts';
import type {InkStroke} from './types.ts';

export type NotebookTool='pen'|'highlighter'|'stroke-eraser'|'partial-eraser'|'lasso'|'pan';
export type NotebookTools={tool:NotebookTool;eraserMode?:'stroke-eraser'|'partial-eraser';penColor:string;penWidth:number;penOpacity:number;highlighterColor:string;highlighterWidth:number;highlighterOpacity:number;eraserSize:number};
export type NotebookView={zoomMode:'fit'|'manual';zoom:number;rotation:number;notesOpen:boolean};
export const defaultTools:NotebookTools={tool:'pen',penColor:'#254f3f',penWidth:.0025,penOpacity:1,highlighterColor:'#254f3f',highlighterWidth:.018,highlighterOpacity:.35,eraserSize:.014};
export const defaultView:NotebookView={zoomMode:'fit',zoom:1,rotation:0,notesOpen:true};
const cache=new Map<string,unknown>(),writes=new Map<string,Promise<boolean>>();
const toolNames:NotebookTool[]=['pen','highlighter','stroke-eraser','partial-eraser','lasso','pan'];
const inRange=(value:unknown,min:number,max:number)=>typeof value==='number'&&Number.isFinite(value)&&value>=min&&value<=max;
export function notebookColor(value:unknown){return typeof value==='string'&&/^#[0-9a-f]{6}$/i.test(value)?value.toLowerCase():null;}
function tools(value:unknown):NotebookTools{
  const row=value as NotebookTools|null;
  return row&&toolNames.includes(row.tool)&&(row.eraserMode===undefined||['stroke-eraser','partial-eraser'].includes(row.eraserMode))&&[row.penColor,row.highlighterColor].every(color=>notebookColor(color)!==null)&&[row.penWidth,row.highlighterWidth].every(width=>inRange(width,.0005,.04))&&[row.penOpacity,row.highlighterOpacity].every(opacity=>inRange(opacity,.05,1))&&inRange(row.eraserSize,.003,.06)?{...row}:{...defaultTools};
}
function view(value:unknown):NotebookView{
  const row=value as NotebookView|null;
  return row&&['fit','manual'].includes(row.zoomMode)&&inRange(row.zoom,.1,3)&&[0,90,180,270].includes(row.rotation)&&typeof row.notesOpen==='boolean'?{...row}:{...defaultView};
}
async function read(key:string){
  if(cache.has(key))return cache.get(key);
  const value=nativeApp()?(await api<{value:unknown}>('/native/preferences/'+encodeURIComponent(key))).value:JSON.parse(window.localStorage.getItem('solasi.'+key)||'null');
  cache.set(key,value);return value;
}
function save(key:string,value:NotebookTools|NotebookView){
  cache.set(key,value);
  const pending=(writes.get(key)||Promise.resolve(true)).then(async()=>{
    if(cache.get(key)!==value)return true;
    try{if(nativeApp())await api('/native/preferences/'+encodeURIComponent(key),{method:'PUT',body:JSON.stringify({value})});else window.localStorage.setItem('solasi.'+key,JSON.stringify(value));return true;}catch{return false;}
  });
  writes.set(key,pending);return pending;
}
const viewKey=(asset:string,hash:string)=>'notebook-view:'+asset+':'+hash;
export async function loadNotebookPreferences(asset:string,hash:string){
  const [savedTools,savedView]=await Promise.allSettled([read('notebook-tools'),read(viewKey(asset,hash))]);
  const warnings=[savedTools.status==='rejected'?'필기 도구 설정을 불러오지 못해 도구 기본값으로 시작했습니다.':'',savedView.status==='rejected'?'이 자료의 보기 설정을 불러오지 못해 폭에 맞춤으로 시작했습니다.':''].filter(Boolean);
  return {tools:tools(savedTools.status==='fulfilled'?savedTools.value:null),view:view(savedView.status==='fulfilled'?savedView.value:null),warning:warnings.join(' ')};
}
export const saveNotebookTools=(value:NotebookTools)=>save('notebook-tools',value);
export const saveNotebookView=(asset:string,hash:string,value:NotebookView)=>save(viewKey(asset,hash),value);
export async function flushNotebookPreferences(){await Promise.all([...writes.values()]);}
export function notebookZoom(value:NotebookView,page:{width:number;height:number},availableWidth:number){
  if(value.zoomMode==='manual'||availableWidth<=0)return value.zoom;
  return Math.max(.1,Math.min(3,availableWidth/(value.rotation%180?680*page.height/page.width:680)));
}
export function notebookExport(filename:string,identity:{course_id:string;asset_id:string;document_sha256:string;page:number},content:{revision:number;status:string;text:string;ink:InkStroke[]}){
  const name=filename.replace(/\.[^.]+$/,'').replace(/[\\/:*?"<>|]/g,'_').slice(0,40)||'자료',saved=content.status==='saved';
  return {filename:`${name}-${identity.document_sha256.slice(0,8)}-p${identity.page}-v${content.revision}-${saved?'saved':'draft'}.json`,value:{format:'solasi-page-notebook-v1',...identity,base_revision:content.revision,saved,text:content.text,ink:content.ink}};
}
