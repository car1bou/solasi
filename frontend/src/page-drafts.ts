import {api,ApiError,nativeApp} from './api';
import {notebookExportIssue} from './notebook-export';
import {readNativeDrafts,transferDraft} from './draft-migration';
import type {DraftExport} from './draft-migration';
import type {DocumentMetadata,InkStroke,PageDocument} from './types';

type Content={text:string;ink:InkStroke[]};
type Draft=Content&{key:string;revision:number;token:string;backup?:Content;dirty?:boolean;updatedAt?:number};
type Recovery=Content&{key:string;revision:number;updatedAt?:number;inProgress?:boolean};
export type PageDraftState=Content&{loaded:boolean;revision:number;status:'loading'|'saved'|'pending'|'saving'|'failed'|'conflict';error:string;storageError:string;server:PageDocument|null;backup?:Content;recovered:Recovery[]};
let database:Promise<IDBDatabase>|undefined;
function db(){return database??=new Promise<IDBDatabase>((resolve,reject)=>{const request=indexedDB.open('solasi-page-drafts',1);request.onupgradeneeded=()=>request.result.createObjectStore('drafts',{keyPath:'key'});request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);});}
async function stored<T>(mode:IDBTransactionMode,operation:(store:IDBObjectStore)=>IDBRequest<T>):Promise<T>{const database=await db();return new Promise((resolve,reject)=>{const transaction=database.transaction('drafts',mode),request=operation(transaction.objectStore('drafts'));let result:T;request.onsuccess=()=>{result=request.result;};transaction.oncomplete=()=>resolve(result!);transaction.onerror=()=>reject(transaction.error);transaction.onabort=()=>reject(transaction.error);});}
async function writeDraft(draft:Draft,journalKey:string){if(nativeApp()){await transferDraft(draft,'write',journalKey);return;}const database=await db();return new Promise<void>((resolve,reject)=>{const transaction=database.transaction('drafts','readwrite'),store=transaction.objectStore('drafts');store.put(draft);if(draft.dirty)store.put({...draft,key:journalKey});else store.delete(journalKey);transaction.oncomplete=()=>resolve();transaction.onerror=()=>reject(transaction.error);transaction.onabort=()=>reject(transaction.error);});}
async function deleteJournal(key:string){if(nativeApp())await api('/native/drafts/journal?key='+encodeURIComponent(key),{method:'DELETE'});else await stored('readwrite',store=>store.delete(key));}
async function writeCheckpoint(draft:Draft,key:string){if(nativeApp())await transferDraft(draft,'checkpoint',key);else await stored('readwrite',store=>store.put({...draft,key,inProgress:true}));}
function equal(a:Content,b:Content){return a.text===b.text&&JSON.stringify(a.ink)===JSON.stringify(b.ink);}
const stores=new Map<string,PageDraft>();
export function pageDraft(courseId:string,assetId:string,hash:string,page:number){const key=JSON.stringify([courseId,assetId,hash,page]);let store=stores.get(key);if(!store){store=new PageDraft(key,`/courses/${courseId}/assets/${assetId}/pages/${page}/document`,hash);stores.set(key,store);}return store;}
export function notebookPDFIssue(courseId:string,assetId:string,hash:string){
  const pages=[];
  for(const [key,store]of stores){const [course,asset,digest,page]=JSON.parse(key);if(course===courseId&&asset===assetId&&digest===hash)pages.push({page,...store.snapshot()});}
  return notebookExportIssue(pages);
}
export async function flushPageDrafts(){for(const store of stores.values())if(!await store.flushStorage())throw new Error('페이지 초안을 저장하지 못했습니다. 창을 유지하고 저장 상태를 확인하세요.');}
export function resumePageDrafts(){for(const store of stores.values())store.resumeStorage();}
export async function exportPageDrafts(vaultId:string,theme:DraftExport['theme'],unsavedInputs:unknown[]):Promise<DraftExport>{
  if(nativeApp())throw new Error('이전 화면의 초안 저장소에서 내보내기를 실행하세요.');
  for(const store of stores.values())if(!await store.flushStorage())throw new Error('초안 저장이 끝나지 않아 이전을 중단했습니다.');
  return {version:1,vault_id:vaultId,origin:location.origin,theme,drafts:await stored('readonly',store=>store.getAll()),unsaved_inputs:unsavedInputs};
}

export class PageDraft{
  state:PageDraftState={text:'',ink:[],loaded:false,revision:0,status:'loading',error:'',storageError:'',server:null,recovered:[]};
  private listeners=new Set<()=>void>();
  private token='';
  private writer=crypto.randomUUID();
  private timer:ReturnType<typeof setTimeout>|undefined;
  private saving=false;
  private recovering=false;
  private storageQueue:Promise<boolean>=Promise.resolve(true);
  private stroke:{key:string;base:InkStroke[];ink:InkStroke[]}|undefined;
  private strokeStored:typeof this.stroke;
  private strokeTimer:ReturnType<typeof setTimeout>|undefined;
  private strokeAt=0;
  private strokeBusy=false;
  private strokeWrite:Promise<boolean>=Promise.resolve(true);
  private strokeCleanup:Promise<void>=Promise.resolve();
  private key:string;
  private path:string;
  private hash:string;
  constructor(key:string,path:string,hash:string){this.key=key;this.path=path;this.hash=hash;void this.load();}
  subscribe=(listener:()=>void)=>{const first=this.listeners.size===0;this.listeners.add(listener);if(first&&this.state.loaded)void this.refresh();return()=>{this.listeners.delete(listener);};};
  snapshot=()=>this.state;
  async flushStorage(){clearTimeout(this.timer);if(this.stroke){this.queueStroke(true);if(!await this.strokeWrite)return false;if(this.stroke!==this.strokeStored){this.queueStroke(true);if(!await this.strokeWrite)return false;}}await this.strokeCleanup;return this.state.loaded&&this.state.status!=='saved'?await this.persist():await this.storageQueue;}
  resumeStorage(){if(this.state.status==='pending')this.schedule();}
  private update(next:Partial<PageDraftState>){this.state={...this.state,...next};this.listeners.forEach(listener=>listener());}
  checkpointStroke(base:InkStroke[],stroke:InkStroke){
    if(!this.state.loaded||base!==this.state.ink||!['pen','highlighter'].includes(stroke.tool))return;
    const key=this.key+'::stroke-'+this.writer+'-'+stroke.id;
    this.stroke={key,base,ink:[...base,stroke]};this.queueStroke();
  }
  private queueStroke(force=false){
    const stroke=this.stroke;if(!stroke||this.strokeBusy||stroke===this.strokeStored)return;
    if(stroke.base!==this.state.ink){this.endStroke(false);return;}
    const delay=force?0:Math.max(0,250-(Date.now()-this.strokeAt));
    if(delay){this.strokeTimer??=setTimeout(()=>{this.strokeTimer=undefined;this.queueStroke(true);},delay);return;}
    clearTimeout(this.strokeTimer);this.strokeTimer=undefined;this.strokeAt=Date.now();this.strokeBusy=true;
    const draft:Draft={key:this.key,revision:this.state.revision,text:this.state.text,ink:stroke.ink,token:this.token,dirty:true,updatedAt:Date.now()};
    this.strokeWrite=writeCheckpoint(draft,stroke.key).then(()=>{this.strokeStored=stroke;return true;}).catch(()=>{this.update({storageError:'그리던 획의 복구 사본을 기록하지 못했습니다. 획을 마친 뒤 저장 상태를 확인하세요.'});return false;}).finally(()=>{this.strokeBusy=false;if(this.stroke&&this.stroke!==stroke)this.queueStroke();});
  }
  endStroke(completed:boolean){
    const stroke=this.stroke;if(!stroke)return;this.stroke=undefined;clearTimeout(this.strokeTimer);this.strokeTimer=undefined;
    const pending=this.strokeWrite,durable=this.storageQueue;
    this.strokeCleanup=this.strokeCleanup.catch(()=>{}).then(async()=>{await pending;if(completed&&!await durable)return;await deleteJournal(stroke.key);}).catch(()=>{this.update({storageError:'진행 중 필기 복구 사본을 정리하지 못했습니다. 원래 필기와 사본은 보존됩니다.'});});
  }
  private persist(){const draft:Draft={key:this.key,revision:this.state.revision,text:this.state.text,ink:this.state.ink,token:this.token,backup:this.state.backup,dirty:this.state.status!=='saved',updatedAt:Date.now()};this.storageQueue=this.storageQueue.catch(()=>{}).then(()=>writeDraft(draft,this.key+'::'+this.writer)).then(()=>true).catch(()=>{this.update({storageError:'앱 초안 저장소에 접근할 수 없습니다. 서버 저장 완료를 확인한 후 이동하세요.'});return false;});return this.storageQueue;}
  private async load(){
    let draft:Draft|undefined,recovered:Draft[]=[];
    try{if(nativeApp()){const rows=await readNativeDrafts<Draft>(this.key);draft=rows.find(row=>row.key===this.key);recovered=rows.filter(row=>row.key!==this.key);}else{draft=await stored('readonly',store=>store.get(this.key));recovered=await stored('readonly',store=>store.getAll(IDBKeyRange.bound(this.key+'::',this.key+'::\uffff')));}}catch{this.update({storageError:'앱 초안 저장소에 접근할 수 없습니다.'});}
    try{
      const server=await api<PageDocument>(this.path+'?document_sha256='+encodeURIComponent(this.hash));
      this.token=draft?.token||crypto.randomUUID();
      this.update({recovered:recovered.filter((row,index,all)=>!equal(row,server)&&(!draft||!equal(row,draft))&&all.findIndex(other=>equal(row,other))===index)});
      if(draft&&draft.dirty!==false&&!equal(draft,server)){
        const conflict=draft.revision!==server.revision;
        this.update({loaded:true,text:draft.text,ink:draft.ink,revision:draft.revision,server,status:conflict?'conflict':'pending',backup:draft.backup,error:conflict?'다른 편집 내용이 저장되어 있습니다. 두 내용을 확인한 후 선택하세요.':''});
        if(!conflict)this.schedule();
      }else this.update({loaded:true,text:server.text,ink:server.ink,revision:server.revision,server,status:'saved',backup:draft?.backup});
    }catch(e){this.token=draft?.token||crypto.randomUUID();this.update({loaded:!!draft,text:draft?.text||'',ink:draft?.ink||[],revision:draft?.revision||0,status:'failed',backup:draft?.backup,recovered,error:(e as Error).message});}
  }
  async refresh(){if(!this.state.loaded||this.saving)return;try{const server=await api<PageDocument>(this.path+'?document_sha256='+encodeURIComponent(this.hash));if(this.saving||server.revision===this.state.revision)return;if(this.state.status==='saved'||equal(this.state,server)){this.update({text:server.text,ink:JSON.stringify(this.state.ink)===JSON.stringify(server.ink)?this.state.ink:server.ink,revision:server.revision,server,status:'saved',error:''});}else this.update({server,status:'conflict',error:'다른 창에서 저장한 내용과 현재 초안을 확인하세요.'});await this.persist();}catch(e){this.update({status:this.state.status==='conflict'?'conflict':'failed',error:'최신 페이지 버전 대조 실패: '+(e as Error).message});}}
  change(content:Content){
    this.token=crypto.randomUUID();
    this.update({...content,status:this.state.status==='conflict'?'conflict':'pending',error:this.state.status==='conflict'?this.state.error:''});
    void this.persist();if(this.state.status!=='conflict')this.schedule();
  }
  private schedule(){clearTimeout(this.timer);this.timer=setTimeout(()=>void this.save(),650);}
  async save(){
    clearTimeout(this.timer);
    if(this.saving||!this.state.loaded||this.state.status==='conflict'||this.state.status==='saved')return;
    const content={text:this.state.text,ink:this.state.ink},token=this.token,revision=this.state.revision;
    const points=content.ink.reduce((sum,stroke)=>sum+stroke.points.length,0);
    if(content.text.length+content.ink.reduce((sum,stroke)=>sum+(stroke.tool==='text'?stroke.text.length:0),0)>200000||content.ink.length>2000||points>100000||new TextEncoder().encode(JSON.stringify(content.ink)).byteLength>8*1024*1024){this.update({status:'failed',error:'페이지 저장 한도(메모 20만 자, 2,000획·10만 점·8MiB)를 초과했습니다. 초안을 내보내고 내용을 줄여 주세요.'});return;}
    this.saving=true;this.update({status:'saving',error:''});
    try{
      const server=await api<PageDocument>(this.path,{method:'PUT',body:JSON.stringify({document_sha256:this.hash,expected_revision:revision,...content})});
      this.update({server,revision:server.revision,status:this.token===token?'saved':'pending'});
      await this.persist();
    }catch(e){
      if(e instanceof ApiError&&e.status===409){
        let server:PageDocument|null=null;try{const metadata=await api<DocumentMetadata>('/assets/'+(JSON.parse(this.key) as string[])[1]+'/document');if(metadata.sha256===this.hash)server=await api<PageDocument>(this.path+'?document_sha256='+encodeURIComponent(this.hash));}catch{}
        this.update({status:'conflict',server,error:server?'다른 편집 내용이 저장되어 있습니다. 두 내용을 확인한 후 선택하세요.':'원본 PDF 버전이 바뀌었습니다. 초안을 내보내고 자료를 다시 여세요. 이전 버전 필기는 보존됩니다.'});
      }else this.update({status:'failed',error:(e as Error).message});
      await this.persist();
    }finally{this.saving=false;if(this.state.status==='pending')this.schedule();}
  }
  resolve(useLocal:boolean){const server=this.state.server;if(!server||server.document_sha256!==this.hash)return;
    this.token=crypto.randomUUID();
    this.update(useLocal?{revision:server.revision,status:'pending',error:'',backup:{text:server.text,ink:server.ink}}:{text:server.text,ink:server.ink,revision:server.revision,status:'saved',error:'',backup:{text:this.state.text,ink:this.state.ink}});
    void this.persist();if(useLocal)void this.save();
  }
  async recover(draft:Recovery){
    if(this.recovering)return;
    if(this.saving){this.update({error:'페이지 저장이 끝난 뒤 복구 후보를 다시 적용하세요.'});return;}
    this.recovering=true;
    const current={text:this.state.text,ink:this.state.ink};
    try{
      const conflict=draft.inProgress&&(draft.revision!==this.state.revision||JSON.stringify(draft.ink.slice(0,-1))!==JSON.stringify(current.ink));
      if(conflict){
        const backup:Draft={...current,key:this.key+'::before-recovery-'+crypto.randomUUID(),revision:this.state.revision,token:crypto.randomUUID(),dirty:true,updatedAt:Date.now(),backup:this.state.backup};
        await writeDraft(backup,backup.key+'::'+this.writer);
        this.update({recovered:[...this.state.recovered,backup]});
        if(this.saving||this.state.ink!==current.ink||this.state.text!==current.text){this.update({error:'복구 준비 중 편집 내용이 바뀌었습니다. 두 사본을 보존했으니 다시 확인하세요.'});return;}
      }
      this.update({...(draft.inProgress&&!conflict?{}:{backup:current}),recovered:this.state.recovered.filter(row=>row.key!==draft.key)});
      if(conflict){this.token=crypto.randomUUID();this.update({text:draft.text,ink:draft.ink,revision:draft.revision,status:'conflict',error:'그리던 획의 기준 페이지가 달라졌습니다. 현재 필기와 복구 후보를 비교한 뒤 선택하세요.'});}
      else this.change({text:draft.inProgress?current.text:draft.text,ink:draft.ink});
      if(await this.persist())await deleteJournal(draft.key);
    }catch{this.update({storageError:'복구 처리를 완료하지 못했습니다. 현재 내용과 복구 사본의 저장 상태를 확인한 뒤 다시 시도하세요.'});}
    finally{this.recovering=false;}
  }
  retry(){if(!this.state.loaded)void this.load();else void this.save();}
}
