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
    else if(message.path.endsWith('/commit')){commits++;if(commits===1){started();await blocked;}result={count:1,sha256:'checked'};}
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
