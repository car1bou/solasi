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
