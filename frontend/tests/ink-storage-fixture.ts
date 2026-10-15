import {PageDraft} from '../src/page-drafts';
import {inkPath} from '../src/ink';
import type {InkStroke,PageDocument} from '../src/types';

const results=document.querySelector<HTMLPreElement>('#results')!;
const runId=new URLSearchParams(location.search).get('id')||'manual';
const prefix='solasi-ink-fixture:'+runId+':';
const ink:InkStroke[]=[{id:'fixture-pressure-stroke',tool:'pen',color:'#254f3f',width:.02,opacity:.8,input:'pen',points:[{x:.1,y:.5,pressure:0,tilt_x:-12,tilt_y:24},{x:.9,y:.5,pressure:1,tilt_x:12,tilt_y:-24}]}];
const content={text:'재시작 복구 fixture '+runId,ink};
let offline=false,putCount=0;
const remote=new Map<string,PageDocument>();
function documentFor(asset:string):PageDocument{return{id:'fixture-document',course_id:'ink-fixture',asset_id:asset,document_sha256:'fixture-hash',page:1,revision:1,text:'fixture server v1',ink:[],source_id:'fixture-source',updated_at:'2026-10-15T00:00:00Z'};}
function context(asset:string){return{key:JSON.stringify(['ink-fixture',asset,'fixture-hash',1]),path:`/courses/ink-fixture/assets/${asset}/pages/1/document`};}
function open(asset:string){const {key,path}=context(asset);return new PageDraft(key,path,'fixture-hash');}
function check(condition:unknown,message:string):asserts condition{if(!condition)throw new Error(message);results.textContent+='\nPASS '+message;}
const same=(a:unknown,b:unknown)=>JSON.stringify(a)===JSON.stringify(b);
const pause=(ms:number)=>new Promise(resolve=>setTimeout(resolve,ms));
async function loaded(store:PageDraft){if(store.state.loaded)return;await new Promise<void>((resolve,reject)=>{const timeout=setTimeout(()=>{unsubscribe();reject(new Error('PageDraft did not load within 5 seconds'));},5000);const unsubscribe=store.subscribe(()=>{if(store.state.loaded){clearTimeout(timeout);unsubscribe();resolve();}});});}
async function rows(key:string){
  const database=await new Promise<IDBDatabase>((resolve,reject)=>{const request=indexedDB.open('solasi-page-drafts',1);request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);});
  try{return await new Promise<any[]>((resolve,reject)=>{const transaction=database.transaction('drafts','readonly'),request=transaction.objectStore('drafts').getAll();let value:any[]=[];request.onsuccess=()=>{value=request.result.filter(row=>row.key===key||row.key.startsWith(key+'::'));};transaction.oncomplete=()=>resolve(value);transaction.onabort=()=>reject(transaction.error);transaction.onerror=()=>reject(transaction.error);});}finally{database.close();}
}
async function persisted(key:string,predicate:(row:any)=>boolean){for(let i=0;i<100;i++){const all=await rows(key),main=all.find(row=>row.key===key);if(main&&predicate(main))return all;await pause(20);}throw new Error('Expected IndexedDB transaction did not complete');}
globalThis.fetch=async(input,options)=>{
  const url=String(input);
  if(url==='/api/client')return Response.json({csrf_token:'ink-fixture-only'});
  if(offline)return Response.json({detail:'fixture offline'},{status:503});
  const asset=url.match(/\/assets\/([^/]+)/)?.[1];
  if(!asset)return Response.json({detail:'unexpected fixture route'},{status:404});
  const current=remote.get(asset)||documentFor(asset);
  if(url.endsWith('/document')&&!url.includes('/pages/'))return Response.json({sha256:'fixture-hash'});
  if(options?.method==='PUT'){
    putCount++;const body=JSON.parse(String(options.body));
    if(body.expected_revision!==current.revision)return Response.json({detail:'fixture revision conflict'},{status:409});
    const next={...current,text:body.text,ink:body.ink,revision:current.revision+1};remote.set(asset,next);return Response.json(next);
  }
  return Response.json(current);
};
document.querySelector('#ink')!.innerHTML=`<path d="${inkPath(ink[0],100,200)}" fill="#254f3f" opacity=".8"/>`;
async function run(){
  results.textContent='Running real IndexedDB checks';offline=false;putCount=0;
  const asset='ink-'+runId+'-'+crypto.randomUUID(),{key}=context(asset);
  const first=open(asset);await loaded(first);
  check(!first.state.storageError,'IndexedDB opened without a storage error');
  offline=true;first.change(content);await first.save();
  const saved=await persisted(key,row=>row.dirty&&same(row.ink,ink)&&row.text===content.text);
  check(saved.some(row=>row.key!==key&&row.dirty&&same(row.ink,ink)),'failed server write has a real IndexedDB recovery journal');
  const offlineReload=open(asset);await loaded(offlineReload);
  check(offlineReload.state.status==='failed'&&same(offlineReload.state.ink,ink)&&offlineReload.state.text===content.text,'fresh PageDraft recovers exact pressure/tilt geometry while offline');
  offline=false;remote.set(asset,{...documentFor(asset),revision:2,text:'other editor v2'});
  await first.refresh();
  check(first.state.status==='conflict'&&first.state.revision===1&&first.state.server?.revision===2,'conflict keeps the local base revision');
  first.change({...content,text:content.text+' edited during conflict'});
  await persisted(key,row=>row.text.endsWith('edited during conflict'));
  const reload=open(asset);await loaded(reload);await pause(750);
  check(reload.state.status==='conflict'&&reload.state.revision===1&&putCount===0,'reloading a conflict cannot silently overwrite the newer server revision');
  offline=true;await reload.refresh();offline=false;await reload.save();
  check(reload.state.status==='conflict'&&putCount===0,'failed refresh cannot bypass explicit conflict resolution');
  reload.resolve(false);
  await persisted(key,row=>row.dirty===false&&row.text==='other editor v2'&&row.backup?.text.endsWith('edited during conflict'));
  check(reload.state.backup?.text.endsWith('edited during conflict'),'using server content preserves the displaced local copy');
  const recoverable=open(asset);await loaded(recoverable);
  check(recoverable.state.recovered.some(row=>same(row.ink,ink)),'another writer journal remains available after choosing server');
  const journal=recoverable.state.recovered.find(row=>same(row.ink,ink))!;
  recoverable.recover(journal);await recoverable.save();
  await persisted(key,row=>!row.dirty&&same(row.ink,ink));
  check(same(remote.get(asset)?.ink,ink),'recovering a journal can save the exact exported geometry to the server fixture');
  results.textContent+='\nDONE: browser storage/logic checks passed. App termination still requires prepare/restart/verify.';
}
async function prepare(){
  results.textContent='Preparing restart draft';const asset='restart-'+runId,{key}=context(asset);const store=open(asset);await loaded(store);offline=true;store.change(content);await store.save();await persisted(key,row=>row.dirty&&same(row.ink,ink));
  localStorage.setItem(prefix+'restart-key',asset);
  check(true,'dirty draft and recovery journal transaction completed; quit the fixture browser/app and reopen this same URL, then Verify');
}
async function verify(){
  results.textContent='Verifying after restart';const asset=localStorage.getItem(prefix+'restart-key');check(!!asset,'restart fixture identity survived');offline=true;const store=open(asset);await loaded(store);
  check(store.state.text===content.text&&same(store.state.ink,ink),'text, normalized points, pressure and tilt survived the app/browser restart');
  const all=await rows(context(asset).key);check(all.some(row=>row.key!==context(asset).key&&row.dirty),'recovery journal survived the app/browser restart');
  results.textContent+='\nDONE: restart check passed in this browser profile and origin.';
}
for(const [id,action]of [['run',run],['prepare',prepare],['verify',verify]] as const)document.querySelector<HTMLButtonElement>('#'+id)!.onclick=()=>{void action().catch(error=>{results.textContent+='\nFAIL '+String(error);});};
document.querySelector<HTMLButtonElement>('#download')!.onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify({course_id:'ink-fixture',asset_id:'fixture',document_sha256:'fixture-hash',page:1,...content},null,2)],{type:'application/json'})),anchor=document.createElement('a');anchor.href=url;anchor.download='ink-fixture.json';anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
