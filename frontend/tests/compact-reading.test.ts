import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';

test('embedded notebook panels retain review controls without nested disclosure, and other callers retain accordions',async()=>{
 const server=await createServer({configFile:false,server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
 try{
  const {default:Review}=await server.ssrLoadModule('/src/HandwritingReview.tsx');
  const {default:Related}=await server.ssrLoadModule('/src/RelatedKnowledge.tsx');
  for(const embedded of [false,true]){
   const review=renderToStaticMarkup(React.createElement(Review,{courseId:'c',assetId:'a',page:1,digest:'sha',revision:1,saved:false,width:600,height:800,embedded}));
   const related=renderToStaticMarkup(React.createElement(Related,{courseId:'c',embedded}));
   for(const html of [review,related])assert.match(html,embedded?/^<section class="knowledge-panel embedded"><h3>/:/^<details class="knowledge-panel"><summary>/);
   assert.match(review,/확인한 인식문만 검색·답변 근거/);
   assert.match(review,/필기를 저장한 뒤 인식/);
   assert.match(review,/<button disabled="">손글씨 인식/);
   assert.match(related,/후보는 개념을 자동으로 합치지 않습니다/);
  }
 }finally{await server.close();}
});
test('reader precedes long optional help while keyboard instructions remain attached to sentences',async()=>{
 const server=await createServer({configFile:false,server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
 try{
  const {TranscriptScript}=await server.ssrLoadModule('/src/TranscriptView.tsx');
  const html=renderToStaticMarkup(React.createElement(TranscriptScript,{sessionId:'qa',segments:[{id:'a',chunk_id:'r:0',recording_id:'r',start_ms:0,end_ms:1000,text:'실제 읽기 문장',original_text:'실제 읽기 문장',revision:1,final:1}],reviews:[],refresh:async()=>{},review:async()=>{}}));
  assert.equal((html.match(/id="transcript-help-qa"/g)||[]).length,1);
  assert.match(html,/aria-describedby="transcript-help-qa"/);
  assert.match(html,/<details class="transcript-usage"><summary>대본 사용 안내/);
  assert(html.indexOf('class="transcript-script"')<html.indexOf('class="transcript-usage"'));
  assert.match(html,/단어별 시각이 없어/);
  assert.match(html,/내보낸 파일에 원음이 포함되지는 않습니다/);
  assert.match(html,/TXT 내보내기/);
 }finally{await server.close();}
});
