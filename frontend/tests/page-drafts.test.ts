import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createServer} from 'vite';
import type {PageDocument} from '../src/types.ts';

test('page draft conflicts keep their base revision and cannot be retried past a failed refresh',async t=>{
  const cacheDir=await mkdtemp(join(tmpdir(),'solasi-page-tests-'));
  const vite=await createServer({configFile:false,cacheDir,optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
  const oldFetch=globalThis.fetch;
  Object.defineProperty(globalThis,'location',{value:new URL('http://127.0.0.1/'),configurable:true});
  Object.defineProperty(globalThis,'history',{value:{replaceState(){}},configurable:true});
  let remote:PageDocument={id:'page-document',course_id:'course',asset_id:'asset',document_sha256:'hash',page:1,revision:1,text:'server v1',ink:[],source_id:'source-v1',updated_at:'2026-10-15T00:00:00Z'};
  let offline=false,puts=0;
  globalThis.fetch=async(input,options)=>{
    if(String(input)==='/api/client')return Response.json({csrf_token:'fixture'});
    if(offline)return Response.json({detail:'fixture offline'},{status:503});
    if(options?.method==='PUT'){puts++;return Response.json({...remote,...JSON.parse(String(options.body)),revision:remote.revision+1});}
    return Response.json(remote);
  };
  try{
    const {PageDraft}=await vite.ssrLoadModule('/src/page-drafts.ts');
    const store=new PageDraft(JSON.stringify(['course','asset','hash',1]),'/fixture-page','hash');
    await new Promise<void>(resolve=>{const unsubscribe=store.subscribe(()=>{if(store.state.loaded){unsubscribe();resolve();}});});
    store.change({text:'local from v1',ink:[]});
    remote={...remote,revision:2,text:'other editor v2',source_id:'source-v2'};
    await store.refresh();
    await t.test('a conflict still references the revision the local editor actually saw',()=>{
      assert.equal(store.state.status,'conflict');
      assert.equal(store.state.revision,1);
      assert.equal(store.state.server.revision,2);
      assert.equal(store.state.text,'local from v1');
    });
    offline=true;
    await store.refresh();
    await t.test('a failed comparison preserves the conflict guard',()=>{
      assert.equal(store.state.status,'conflict');
      assert.match(store.state.error,/fixture offline/);
    });
    offline=false;
    await store.save();
    await t.test('save cannot overwrite a conflict without an explicit resolution',()=>assert.equal(puts,0));
  }finally{
    globalThis.fetch=oldFetch;
    await vite.close();
    await rm(cacheDir,{recursive:true,force:true});
  }
});

test('native close flush waits for journal commits and does not apply a page conflict',async()=>{
  const cacheDir=await mkdtemp(join(tmpdir(),'solasi-close-drafts-'));
  const vite=await createServer({configFile:false,cacheDir,optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
  Object.defineProperty(globalThis,'location',{value:new URL('solasi-app://app/'),configurable:true});
  let commits=0,serverWrites=0,completed=false,release!:()=>void,started!:()=>void;
  const blocked=new Promise<void>(resolve=>{release=resolve;}),firstCommit=new Promise<void>(resolve=>{started=resolve;});
  const remote={id:'page',course_id:'course',asset_id:'asset',document_sha256:'hash',page:1,revision:2,text:'remote',ink:[],source_id:'source',updated_at:'2026-10-16'};
  Object.defineProperty(globalThis,'window',{configurable:true,value:{webkit:{messageHandlers:{solasi:{postMessage:async(message:{path:string;method:string;body?:string})=>{
    const body=message.body?JSON.parse(message.body):{};
    let result:unknown;
    if(message.path.startsWith('/api/native/drafts/read'))result=[];
    else if(message.path==='/api/native/drafts/uploads')result={id:'upload-'+commits,chunk_size:256*1024};
    else if(message.path.endsWith('/commit')||message.path==='/api/native/drafts/snapshot'){commits++;if(commits===1){started();await blocked;}result={count:1,sha256:'checked'};}
    else if(message.path.startsWith('/api/native/drafts/uploads/'))result={received:body.offset+Buffer.from(body.data,'base64').length};
    else {if(message.method==='PUT')serverWrites++;result=remote;}
    return {status:200,text:JSON.stringify(result)};
  }}}}}});
  try{
    const {pageDraft,flushPageDrafts}=await vite.ssrLoadModule('/src/page-drafts.ts');
    const store=pageDraft('course','asset','hash',1);
    await new Promise<void>(resolve=>{const unsubscribe=store.subscribe(()=>{if(store.state.loaded){unsubscribe();resolve();}});});
    store.state={...store.state,status:'conflict'};
    store.change({text:'my unsaved conflict',ink:[]});
    const pending=flushPageDrafts().then(()=>{completed=true;});
    await firstCommit;assert.equal(completed,false);release();await pending;
    assert.equal(commits,2);assert.equal(serverWrites,0);
    assert.equal(store.state.text,'my unsaved conflict');assert.equal(store.state.status,'conflict');
  }finally{release();await vite.close();await rm(cacheDir,{recursive:true,force:true});}
});

test('live stroke journals coalesce, remain separate and require explicit recovery',async()=>{
  const cacheDir=await mkdtemp(join(tmpdir(),'solasi-live-drafts-'));
  const vite=await createServer({configFile:false,cacheDir,optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
  Object.defineProperty(globalThis,'location',{value:new URL('solasi-app://app/'),configurable:true});
  const rows=new Map<string,any>();let puts=0,checkpointCalls=0,release!:()=>void;
  let hold:Promise<void>|undefined,putGate:Promise<void>|undefined,putStarted:(()=>void)|undefined;
  const remote={id:'page',course_id:'course',asset_id:'asset',document_sha256:'hash',page:1,revision:2,text:'existing memo',ink:[],source_id:'source',updated_at:'2026-11-05'};
  Object.defineProperty(globalThis,'window',{configurable:true,value:{webkit:{messageHandlers:{solasi:{postMessage:async(message:{path:string;method:string;body?:string})=>{
    const body=message.body?JSON.parse(message.body):{};let result:any;
    if(message.path.startsWith('/api/native/drafts/read')){const q=new URL('solasi-app://app'+message.path).searchParams;result=[...rows.values()].filter(r=>r.key>q.get('after')!).sort((a,b)=>a.key.localeCompare(b.key)).slice(0,1);}
    else if(message.path.startsWith('/api/native/drafts/journal')){rows.delete(new URL('solasi-app://app'+message.path).searchParams.get('key')!);result={};}
    else if(message.path==='/api/native/drafts/snapshot'){
      const value=body.value;
      if(body.checkpoint){checkpointCalls++;if(hold)await hold;rows.set(body.journal_key,{...value,key:body.journal_key,inProgress:true});}
      else {rows.set(value.key,value);if(value.dirty)rows.set(body.journal_key,{...value,key:body.journal_key});else rows.delete(body.journal_key);}
      result={count:1,sha256:'checked'};
    }else {if(message.method==='PUT'){puts++;putStarted?.();if(putGate)await putGate;Object.assign(remote,{...body,revision:remote.revision+1});}result=remote;}
    return {status:200,text:JSON.stringify(result)};
  }}}}}});
  const loaded=async(store:any)=>{if(!store.state.loaded)await new Promise<void>(resolve=>{const stop=store.subscribe(()=>{if(store.state.loaded){stop();resolve();}});});};
  try{
    const {PageDraft}=await vite.ssrLoadModule('/src/page-drafts.ts');
    const key=JSON.stringify(['course','asset','hash',1]);const store=new PageDraft(key,'/fixture','hash');await loaded(store);
    const base=store.state.ink;
    const stroke={id:'live',tool:'pen',color:'#254f3f',width:.01,opacity:1,input:'pen',points:[{x:.2,y:.3,pressure:.7,tilt_x:12,tilt_y:-4}]};
    hold=new Promise<void>(resolve=>{release=resolve;});
    store.checkpointStroke(base,stroke);
    await new Promise(resolve=>setImmediate(resolve));
    for(let i=0;i<80;i++)store.checkpointStroke(base,{...stroke,points:[...stroke.points,{x:.3+i*.001,y:.4,pressure:.8}]});
    assert.equal(checkpointCalls,1);assert.equal(store.state.status,'saved');assert.equal(store.state.ink,base);assert.equal(puts,0);
    hold=undefined;release();await store.flushStorage();
    assert.ok(checkpointCalls<=2);assert.equal(rows.size,1);assert.equal(puts,0);
    const partial=[...rows.values()][0];assert.equal(partial.ink.at(-1).points.at(-1).x,.379);
    const reopened=new PageDraft(key,'/fixture','hash');await loaded(reopened);
    assert.equal(reopened.state.status,'saved');assert.equal(reopened.state.ink.length,0);assert.equal(reopened.state.recovered.length,1);
    assert.equal(reopened.state.recovered[0].inProgress,true);assert.equal(puts,0);
    await reopened.recover(reopened.state.recovered[0]);await reopened.save();await reopened.flushStorage();
    assert.equal(remote.ink.length,1);assert.deepEqual(remote.ink[0],partial.ink[0]);assert.equal(remote.text,'existing memo');
    assert.equal(reopened.state.backup,undefined,'appending a partial stroke must not replace a previous backup');
    store.endStroke(false);await store.flushStorage();assert.ok(![...rows.values()].some(r=>r.inProgress));

    const normalBase=reopened.state.ink,finalStroke={...stroke,id:'normal',tool:'highlighter',opacity:.35};
    hold=new Promise<void>(resolve=>{release=resolve;});
    reopened.checkpointStroke(normalBase,finalStroke);await new Promise(resolve=>setImmediate(resolve));
    const finalInk=[...normalBase,{...finalStroke,points:[...finalStroke.points,{x:.8,y:.6,pressure:.5}]}];
    reopened.change({text:reopened.state.text,ink:finalInk});reopened.endStroke(true);
    hold=undefined;release();await reopened.flushStorage();
    assert.ok(![...rows.values()].some(r=>r.inProgress),'late partial write must be cleaned after final draft commits');
    assert.deepEqual(rows.get(key).ink,finalInk);await reopened.save();await reopened.flushStorage();
    assert.deepEqual(remote.ink,finalInk);

    const cancelBase=reopened.state.ink,putCount=puts;
    hold=new Promise<void>(resolve=>{release=resolve;});
    reopened.checkpointStroke(cancelBase,{...stroke,id:'cancel'});await new Promise(resolve=>setImmediate(resolve));
    reopened.endStroke(false);hold=undefined;release();await reopened.flushStorage();
    assert.equal(puts,putCount);assert.ok(![...rows.values()].some(r=>r.inProgress));assert.deepEqual(remote.ink,finalInk);

    reopened.checkpointStroke(cancelBase,{...stroke,id:'older-page'});await reopened.flushStorage();
    remote.revision++;
    const other=new PageDraft(key,'/fixture','hash');await loaded(other);
    assert.equal(other.state.recovered.length,1);
    const newerInk=[...other.state.ink,{...stroke,id:'new-unsaved'}];
    other.state={...other.state,backup:{text:'older displaced memo',ink:[]}};
    other.change({text:'new unsaved memo',ink:newerInk});
    await other.recover(other.state.recovered[0]);
    await other.save();await other.flushStorage();
    assert.equal(other.state.status,'conflict');assert.equal(puts,putCount);assert.deepEqual(remote.ink,finalInk);
    const beforeRecovery=other.state.recovered.find((row:any)=>!row.inProgress);
    assert.ok(beforeRecovery,'current content must have its own durable recovery journal before resolving');
    other.resolve(true);await other.flushStorage();
    assert.ok([...rows.values()].some(r=>r.key===beforeRecovery.key&&r.text==='new unsaved memo'&&JSON.stringify(r.ink)===JSON.stringify(newerInk)));
    assert.equal(rows.get(beforeRecovery.key).backup.text,'older displaced memo');
    reopened.endStroke(false);await reopened.flushStorage();
    await new Promise(resolve=>setImmediate(resolve));
    const guard=new PageDraft(key,'/fixture','hash');await loaded(guard);
    guard.checkpointStroke(guard.state.ink,{...stroke,id:'guard'});await guard.flushStorage();
    const guardOther=new PageDraft(key,'/fixture','hash');await loaded(guardOther);
    const candidate=guardOther.state.recovered.find((row:any)=>row.inProgress);assert.ok(candidate);
    let finishPut!:()=>void,startedPut!:()=>void;
    putGate=new Promise<void>(resolve=>{finishPut=resolve;});const putEntered=new Promise<void>(resolve=>{startedPut=resolve;});putStarted=startedPut;
    guardOther.change({text:'save in progress',ink:guardOther.state.ink});const saving=guardOther.save();await putEntered;
    const beforeApply=puts;await guardOther.recover(candidate);
    assert.equal(guardOther.state.text,'save in progress');assert.ok(guardOther.state.recovered.includes(candidate));
    putGate=undefined;putStarted=undefined;finishPut();await saving;await guardOther.flushStorage();
    assert.equal(puts,beforeApply);assert.equal(guardOther.state.status,'saved');assert.equal(remote.text,'save in progress');
    guard.endStroke(false);await guard.flushStorage();
  }finally{release?.();await vite.close();await rm(cacheDir,{recursive:true,force:true});}
});
