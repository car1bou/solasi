import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';

test('material recovery offers only actions matching the source state and preserves handwriting approval',async()=>{
 const server=await createServer({configFile:false,server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
 try{
  const {default:Recovery}=await server.ssrLoadModule('/src/MaterialRecovery.tsx');
  const draw=(source_status:string,status='ready',handwritten=false,busy=false)=>renderToStaticMarkup(React.createElement(Recovery,{asset:{filename:'강의.pdf',source_status,status,handwritten},busy,onCheck:()=>{},onReconnect:()=>{},onExtract:()=>{}}));
  assert.equal(draw('current'),'');
  for(const status of ['missing','denied']){const html=draw(status);assert.match(html,/원본 다시 찾기/);assert.match(html,/같은 내용의 원본 파일 하나/);assert.doesNotMatch(html,/>재추출</);assert.match(html,/과거 출처는 보존/);}
  assert.match(draw('changed'),/원본 확인/);assert.match(draw('changed'),/>재추출</);
  assert.match(draw('current','stale'),/검색용 원문 갱신 필요/);
  assert.doesNotMatch(draw('changed','ready',true),/>재추출</);
  assert.equal((draw('missing','ready',false,true).match(/disabled=""/g)||[]).length,2);
 }finally{await server.close();}
});

test('technical missing-path details fold while recovery rejection stays immediately visible',async()=>{
 const server=await createServer({configFile:false,server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
 try{
  const {MaterialError}=await server.ssrLoadModule('/src/MaterialRecovery.tsx');
  const draw=(message:string)=>renderToStaticMarkup(React.createElement(MaterialError,{message}));
  const html=draw('원본 파일 접근·내용을 확인하세요: [Errno 2] /long/original.pdf');
  assert.match(html,/<details[^>]*><summary>원본 파일을 열 수 없습니다/);assert.doesNotMatch(html,/<details[^>]*open/);assert.match(html,/long\/original.pdf/);
  assert.match(draw('기존 원본과 내용이 다릅니다'),/<p role="alert"[^>]*>기존 원본과 내용이 다릅니다<\/p>/);
 }finally{await server.close();}
});
