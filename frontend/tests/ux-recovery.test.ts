import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';

test('course and lecture summaries expose processed coverage and unquoted original sources',async()=>{
  const server=await createServer({configFile:false,cacheDir:'../.local-state/ux-test-vite',server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
  try{
    const {default:SummaryCoverage}=await server.ssrLoadModule('/src/SummaryCoverage.tsx');
    const markup=renderToStaticMarkup(React.createElement(SummaryCoverage,{saved:{body:{summary_format:'excerpts-v1',covered_source_ids:['a','b'],cited_source_ids:['a'],selection_incomplete_parts:[1],unquoted_sources:[{text:'조건이 만족되면 다음 단계를 진행한다.',evidence_ids:['b']}]},evidence:[{ref:{id:'b'},label:'후반 원문'}]}}));
    assert.match(markup,/처리한 원문 2개 · 최종 인용 1개/);
    assert.match(markup,/핵심 구간 선택 확인 필요/);
    assert.match(markup,/직접 인용하지 않은 원문 1개/);
    assert.match(markup,/조건이 만족되면 다음 단계를 진행한다/);
    assert.match(markup,/후반 원문/);
  }finally{await server.close();}
});

test('recording materials and notes stay mounted when switching between the same session tabs',async()=>{
  const server=await createServer({configFile:false,cacheDir:'../.local-state/ux-test-vite',server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
  try{
    const {default:MaterialView}=await server.ssrLoadModule('/src/MaterialView.tsx');
    for(const mode of ['material','note']){
      const markup=renderToStaticMarkup(React.createElement(MaterialView,{session:{id:'synthetic',kind:'lecture',title:'검증'},mode}));
      assert.match(markup,/aria-label="메모"/);
      assert.match(markup,/class="material-library"/);
      assert.match(markup,/hidden=""/);
    }
  }finally{await server.close();}
});

test('a rejected browser connection is retried and parallel connection attempts share one handshake',async()=>{
  const server=await createServer({configFile:false,cacheDir:'../.local-state/ux-test-vite',server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
  const oldFetch=globalThis.fetch;
  Object.defineProperty(globalThis,'location',{configurable:true,value:{protocol:'http:',hash:'',pathname:'/'}});
  Object.defineProperty(globalThis,'history',{configurable:true,value:{replaceState(){}}});
  let calls=0;
  globalThis.fetch=async()=>{calls++;if(calls===1)throw new Error('temporary connection failure');return new Response(JSON.stringify({csrf_token:'test-token'}));};
  try{
    const {connect,sessionToken}=await server.ssrLoadModule('/src/api.ts');
    await assert.rejects(connect(),/temporary connection failure/);
    await Promise.all([connect(),connect()]);
    assert.equal(calls,2);assert.equal(sessionToken(),'test-token');
  }finally{globalThis.fetch=oldFetch;await server.close();}
});

test('native health errors reject and JSON export distinguishes save from cancellation',async()=>{
  const server=await createServer({configFile:false,cacheDir:'../.local-state/ux-test-vite',server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
  Object.defineProperty(globalThis,'location',{configurable:true,value:{protocol:'solasi-app:'}});
  let cancelled=false;
  Object.defineProperty(globalThis,'window',{configurable:true,value:{webkit:{messageHandlers:{solasi:{postMessage:async(message:{op:string})=>message.op==='export_text'?(cancelled?{cancelled:true}:{saved:true}):{status:503,text:JSON.stringify({detail:'engine unavailable'})}}}}}});
  try{
    const {connect,downloadJSON}=await server.ssrLoadModule('/src/api.ts');
    await assert.rejects(connect(),/engine unavailable/);
    assert.equal(await downloadJSON('page.json',{text:'메모'}),'saved');
    cancelled=true;assert.equal(await downloadJSON('page.json',{}),'cancelled');
  }finally{await server.close();}
});
