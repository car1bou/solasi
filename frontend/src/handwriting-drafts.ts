import {nativeApp} from './api';
import {readNativeDrafts,transferDraft} from './draft-migration';

type ReviewDraft={key:string;text:string;dirty:boolean};
const writes=new Map<string,Promise<void>>();
const draftKey=(id:string)=>'handwriting-review:'+id;
export async function loadReviewDraft(id:string):Promise<string|null>{
 const key=draftKey(id);
 const row=nativeApp()?(await readNativeDrafts<ReviewDraft>(key)).find(r=>r.key===key):JSON.parse(window.localStorage.getItem(key)||'null');
 return row?.dirty&&typeof row.text==='string'?row.text:null;
}
export function saveReviewDraft(id:string,text:string,revision:number,writer:string,dirty:boolean):Promise<void>{
 const key=draftKey(id),row={key,text,ink:[],revision,token:crypto.randomUUID(),dirty,updatedAt:Date.now()};
 const next=(writes.get(key)||Promise.resolve()).catch(()=>{}).then(async()=>{
  if(nativeApp())await transferDraft(row,'write',key+'::'+writer);
  else window.localStorage.setItem(key,JSON.stringify(row));
 });
 writes.set(key,next);return next;
}
