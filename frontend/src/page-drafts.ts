import {api,ApiError} from './api';
import type {DocumentMetadata,InkStroke,PageDocument} from './types';

type Content={text:string;ink:InkStroke[]};
type Draft=Content&{key:string;revision:number;token:string;backup?:Content;dirty?:boolean;updatedAt?:number};
type Recovery=Content&{key:string;revision:number;updatedAt?:number};
export type PageDraftState=Content&{loaded:boolean;revision:number;status:'loading'|'saved'|'pending'|'saving'|'failed'|'conflict';error:string;storageError:string;server:PageDocument|null;backup?:Content;recovered:Recovery[]};
let database:Promise<IDBDatabase>|undefined;
function db(){return database??=new Promise<IDBDatabase>((resolve,reject)=>{const request=indexedDB.open('solasi-page-drafts',1);request.onupgradeneeded=()=>request.result.createObjectStore('drafts',{keyPath:'key'});request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);});}
async function stored<T>(mode:IDBTransactionMode,operation:(store:IDBObjectStore)=>IDBRequest<T>):Promise<T>{const database=await db();return new Promise((resolve,reject)=>{const transaction=database.transaction('drafts',mode),request=operation(transaction.objectStore('drafts'));let result:T;request.onsuccess=()=>{result=request.result;};transaction.oncomplete=()=>resolve(result!);transaction.onerror=()=>reject(transaction.error);transaction.onabort=()=>reject(transaction.error);});}
async function writeDraft(draft:Draft,journalKey:string){const database=await db();return new Promise<void>((resolve,reject)=>{const transaction=database.transaction('drafts','readwrite'),store=transaction.objectStore('drafts');store.put(draft);if(draft.dirty)store.put({...draft,key:journalKey});else store.delete(journalKey);transaction.oncomplete=()=>resolve();transaction.onerror=()=>reject(transaction.error);transaction.onabort=()=>reject(transaction.error);});}
function equal(a:Content,b:Content){return a.text===b.text&&JSON.stringify(a.ink)===JSON.stringify(b.ink);}
const stores=new Map<string,PageDraft>();
export function pageDraft(courseId:string,assetId:string,hash:string,page:number){const key=JSON.stringify([courseId,assetId,hash,page]);let store=stores.get(key);if(!store){store=new PageDraft(key,`/courses/${courseId}/assets/${assetId}/pages/${page}/document`,hash);stores.set(key,store);}return store;}

export class PageDraft{
  state:PageDraftState={text:'',ink:[],loaded:false,revision:0,status:'loading',error:'',storageError:'',server:null,recovered:[]};
  private listeners=new Set<()=>void>();
  private token='';
  private writer=crypto.randomUUID();
  private timer:ReturnType<typeof setTimeout>|undefined;
  private saving=false;
  private storageQueue:Promise<unknown>=Promise.resolve();
  private key:string;
  private path:string;
  private hash:string;
  constructor(key:string,path:string,hash:string){this.key=key;this.path=path;this.hash=hash;void this.load();}
  subscribe=(listener:()=>void)=>{const first=this.listeners.size===0;this.listeners.add(listener);if(first&&this.state.loaded)void this.refresh();return()=>{this.listeners.delete(listener);};};
  snapshot=()=>this.state;
  private update(next:Partial<PageDraftState>){this.state={...this.state,...next};this.listeners.forEach(listener=>listener());}
  private persist(){const draft:Draft={key:this.key,revision:this.state.revision,text:this.state.text,ink:this.state.ink,token:this.token,backup:this.state.backup,dirty:this.state.status!=='saved',updatedAt:Date.now()};this.storageQueue=this.storageQueue.catch(()=>{}).then(()=>writeDraft(draft,this.key+'::'+this.writer)).then(()=>true).catch(()=>{this.update({storageError:'앱 초안 저장소에 접근할 수 없습니다. 서버 저장 완료를 확인한 후 이동하세요.'});return false;});return this.storageQueue;}
  private async load(){
    let draft:Draft|undefined,recovered:Draft[]=[];
    try{draft=await stored('readonly',store=>store.get(this.key));recovered=await stored('readonly',store=>store.getAll(IDBKeyRange.bound(this.key+'::',this.key+'::\uffff')));}catch{this.update({storageError:'앱 초안 저장소에 접근할 수 없습니다.'});}
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
    if(content.text.length>200000||content.ink.length>2000||points>100000||new TextEncoder().encode(JSON.stringify(content.ink)).byteLength>8*1024*1024){this.update({status:'failed',error:'페이지 저장 한도(메모 20만 자, 2,000획·10만 점·8MiB)를 초과했습니다. 초안을 내보내고 내용을 줄여 주세요.'});return;}
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
  recover(draft:Recovery){this.update({backup:{text:this.state.text,ink:this.state.ink},recovered:this.state.recovered.filter(row=>row.key!==draft.key)});this.change({text:draft.text,ink:draft.ink});void this.persist().then(saved=>saved?stored('readwrite',store=>store.delete(draft.key)):undefined).catch(()=>{});}
  retry(){if(!this.state.loaded)void this.load();else void this.save();}
}
