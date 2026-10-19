import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'vite';

test('review edits survive a reload and are isolated by recognition id',async()=>{
 const values=new Map<string,string>();
 Object.defineProperty(globalThis,'location',{configurable:true,value:new URL('http://localhost/')});
 Object.defineProperty(globalThis,'window',{configurable:true,value:{localStorage:{getItem:(k:string)=>values.get(k)??null,setItem:(k:string,v:string)=>values.set(k,v)}}});
 const server=await createServer({configFile:false,server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
 try{
  let drafts=await server.ssrLoadModule('/src/handwriting-drafts.ts');
  assert.equal(await drafts.loadReviewDraft('one'),null);
  await drafts.saveReviewDraft('one','교착 상태',4,'writer',true);
  server.moduleGraph.invalidateAll();drafts=await server.ssrLoadModule('/src/handwriting-drafts.ts');
  assert.equal(await drafts.loadReviewDraft('one'),'교착 상태');assert.equal(await drafts.loadReviewDraft('other'),null);
  await drafts.saveReviewDraft('one','교착 상태 확인',4,'writer',false);
  assert.equal(await drafts.loadReviewDraft('one'),null);
 }finally{await server.close();}
});

test('native review edits use the existing acknowledged draft store and report failures',async()=>{
 Object.defineProperty(globalThis,'location',{configurable:true,value:new URL('solasi-app://app/')});
 const uploads=new Map<string,{bytes:number[];key:string}>(),saved=new Map<string,any>();let fail=false;
 Object.defineProperty(globalThis,'window',{configurable:true,value:{webkit:{messageHandlers:{solasi:{async postMessage(m:any){
  const body=m.body?JSON.parse(m.body):{};let result:any={};
  if(m.path.startsWith('/api/native/drafts/read')){const query=new URL(m.path,'http://local').searchParams,key=query.get('key')!,after=query.get('after')!;result=[...saved.values()].filter(r=>r.key===key&&r.key>after).slice(0,1);}
  else if(m.path==='/api/native/drafts/uploads'){uploads.set('u',{bytes:[],key:body.journal_key});result={id:'u',chunk_size:512};}
  else if(m.path.endsWith('/commit')){if(fail)return {status:500,text:JSON.stringify({detail:'disk unavailable'})};const row=JSON.parse(Buffer.from(uploads.get('u')!.bytes).toString());saved.set(row.key,row);result={count:1};}
  else if(m.method==='PUT'){const u=uploads.get('u')!;u.bytes.push(...Buffer.from(body.data,'base64'));result={received:u.bytes.length};}
  return {status:200,text:JSON.stringify(result)};
 }}}}}});
 const server=await createServer({configFile:false,server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
 try{const drafts=await server.ssrLoadModule('/src/handwriting-drafts.ts');
  await drafts.saveReviewDraft('one','교착',4,'writer',true);assert.equal(await drafts.loadReviewDraft('one'),'교착');
  fail=true;await assert.rejects(drafts.saveReviewDraft('one','다른 수정',4,'writer',true),/disk unavailable/);
  assert.equal(await drafts.loadReviewDraft('one'),'교착');
 }finally{await server.close();}
});
