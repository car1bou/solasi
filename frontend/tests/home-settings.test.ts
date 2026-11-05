import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';

test('recent error sample groups exact messages without hiding different causes',async()=>{
 const server=await createServer({configFile:false,server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
 try{
  const {KnowledgeErrors}=await server.ssrLoadModule('/src/KnowledgeSettings.tsx');
  const draw=(messages:(string|null)[])=>renderToStaticMarkup(React.createElement(KnowledgeErrors,{errors:messages.map((error,key)=>({key:String(key),error}))}));
  assert.equal(draw([]),'');
  const html=draw(['같은 오류','같은 오류','다른 오류',null,'']);
  assert.match(html,/최근 오류 5건 · 3종류/);
  assert.equal((html.match(/같은 오류/g)||[]).length,1);
  assert.equal((html.match(/2건/g)||[]).length,2);
  assert.match(html,/다른 오류/);assert.match(html,/오류 설명 없음/);
  assert.match(html,/전체 실패 건수와 별개/);assert.doesNotMatch(html,/<details[^>]* open/);
  assert.match(draw(['<script>','<script> ']),/2건 · 2종류/);
  assert.doesNotMatch(draw(['<script>']),/<script>/);
 }finally{await server.close();}
});

test('home starts with recent records and keeps the folded creation form mounted',async()=>{
 const server=await createServer({configFile:false,server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
 try{
  const {default:App}=await server.ssrLoadModule('/src/App.tsx');
  const html=renderToStaticMarkup(React.createElement(App));
  assert.match(html,/<h1>최근 기록<\/h1>/);
  assert.match(html,/aria-expanded="false" aria-controls="home-new-record"/);
  assert.match(html,/<section id="home-new-record"[^>]*hidden=""[^>]*>.*?<input[^>]*placeholder="강의 제목"/);
  assert.match(html,/aria-label="최근 기록 목록"/);
 }finally{await server.close();}
});

test('settings keeps daily controls first and API forms mounted inside closed native disclosures',async()=>{
 const server=await createServer({configFile:false,server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
 try{
  const {default:SettingsView}=await server.ssrLoadModule('/src/SettingsView.tsx');
  const html=renderToStaticMarkup(React.createElement(SettingsView));
  assert.ok(html.indexOf('화면 모드')<html.indexOf('세컨드 브레인'));
  assert.ok(html.indexOf('세컨드 브레인')<html.indexOf('AI 실행'));
  assert.match(html,/<details class="settings-details"><summary>서비스별 API 키 관리<\/summary><div class="key-grid">/);
  assert.equal((html.match(/type="password"/g)||[]).length,3);
  for(const title of ['고급 생성 설정','엔진 설치·관리','모델 설치·관리'])assert.ok(html.includes('<summary>'+title+'</summary>'));
 }finally{await server.close();}
});
