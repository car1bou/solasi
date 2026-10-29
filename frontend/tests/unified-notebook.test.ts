import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';
import {fileURLToPath} from 'node:url';

test('notebook and search are persistent peer tabs, while destructive actions stay in an accessible vertical menu',async()=>{
 const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),configFile:false,server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
 try{
  const {default:SessionView}=await server.ssrLoadModule('/src/SessionView.tsx');
  for(const kind of ['lecture','meeting']){
   const html=renderToStaticMarkup(React.createElement(SessionView,{session:{id:'qa',kind,title:'검증',course_id:'c',started_at:'2026-10-29'},course:{id:'c',title:'검증 과목'},onDeleted:async()=>{}}));
   const tabs=html.match(/<div class="segmented session-tabs".*?<\/div>/)?.[0];assert(tabs);
   assert.match(tabs,/>노트<\/button>/);assert.match(tabs,/>검색·개념<\/button>/);assert.doesNotMatch(tabs,/회차 노트|자료·필기/);
   assert.equal((tabs.match(/role="tab"/g)||[]).length,5);assert.equal((tabs.match(/tabindex="0"/g)||[]).length,1);assert.match(tabs,/aria-controls=/);
   const menu=html.match(/<details class="session-management">.*?<\/details>/)?.[0];assert(menu);
   assert.match(menu,/aria-label="기록 메뉴"/);assert.match(menu,/<svg/);assert.doesNotMatch(menu,/더보기|검색·개념|회차 노트/);assert.match(menu,/이 회차 원음 정리/);
   assert.equal((html.match(/aria-label="메모"/g)||[]).length,1);
  }
 }finally{await server.close();}
});
