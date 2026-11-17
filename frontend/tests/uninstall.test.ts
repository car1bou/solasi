import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';

test('uninstall entry offers native category choices and preparation instead of direct deletion',async()=>{
 const server=await createServer({configFile:false,server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
 try{
  const {UninstallForm}=await server.ssrLoadModule('/src/UninstallSettings.tsx');
  const html=renderToStaticMarkup(React.createElement(UninstallForm,{onBegin:()=>{},busy:false,error:''}));
  assert.match(html,/앱 안의 선택창에서.*보존.*삭제/);
  assert.match(html,/>설치 삭제…</);
  assert.match(html,/필기·문서/);assert.match(html,/녹음/);assert.match(html,/전사·AI 결과/);
  assert.match(html,/선택을 바꾸면 다시 검증/);
  assert.doesNotMatch(html,/>삭제 실행</);
  const busy=renderToStaticMarkup(React.createElement(UninstallForm,{onBegin:()=>{},busy:true,error:'준비 실패'}));
  assert.match(busy,/<fieldset disabled="">/);assert.match(busy,/role="alert"/);
 }finally{await server.close();}
});


test('reset entry explains retained app and cleared records/models with guarded execution',async()=>{
 const server=await createServer({configFile:false,server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
 try{
  const {UninstallForm}=await server.ssrLoadModule('/src/UninstallSettings.tsx');
  const html=renderToStaticMarkup(React.createElement(UninstallForm,{reset:true,onBegin:()=>{},busy:false,error:''}));
  assert.match(html,/>앱 초기화…</);assert.match(html,/앱은 유지/);
  assert.match(html,/전용 AI 모델·추가 엔진/);assert.match(html,/보존 파일 검증/);assert.match(html,/필기·문서/);
  assert.doesNotMatch(html,/>초기화 실행</);assert.doesNotMatch(html,/원래 보관함과 앱을 삭제/);
 }finally{await server.close();}
});
