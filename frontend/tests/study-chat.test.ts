import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';

test('conversation composer describes external opt-in and remains accessible while generating',async()=>{
 const server=await createServer({configFile:false,server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
 try{
  const {ChatComposer}=await server.ssrLoadModule('/src/StudyChat.tsx');
  const props={prompt:'어제 공부한 내용을 이어서',setPrompt:()=>{},onSubmit:()=>{},external:true,includeMemory:false,setIncludeMemory:()=>{},enabled:true,busy:false,running:false};
  const html=renderToStaticMarkup(React.createElement(ChatComposer,props));
  assert.match(html,/이전 대화·과목 학습 기억 함께 보내기/);
  assert.match(html,/외부 API/);assert.doesNotMatch(html,/checked=""/);
  assert.match(html,/<label[^>]*>질문/);assert.match(html,/대화 보내기/);
  const running=renderToStaticMarkup(React.createElement(ChatComposer,{...props,running:true}));
  assert.match(running,/disabled=""/);assert.match(running,/role="status"/);
 }finally{await server.close();}
});

test('learning memory shows provenance and explicit correction and deletion controls',async()=>{
 const server=await createServer({configFile:false,server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
 try{
  const {MemoryCard}=await server.ssrLoadModule('/src/StudyChat.tsx');
  const item={id:'memory',kind:'difficulty',text:'독립과 상호배타가 헷갈림',quote:'독립이 헷갈려요',status:'active',manual:0,revision:1,created_at:'2026-11-17T00:00:00Z',updated_at:'2026-11-17T00:00:00Z',thread_id:'thread'};
  const html=renderToStaticMarkup(React.createElement(MemoryCard,{item,busy:false,onEdit:()=>{},onDelete:()=>{},onOpen:()=>{}}));
  assert.match(html,/자동 정리/);assert.match(html,/근거/);assert.match(html,/독립이 헷갈려요/);
  assert.match(html,/수정/);assert.match(html,/기억 삭제/);assert.match(html,/대화 열기/);
  const corrected=renderToStaticMarkup(React.createElement(MemoryCard,{item:{...item,manual:1,status:'resolved'},busy:false,onEdit:()=>{},onDelete:()=>{},onOpen:()=>{}}));
  assert.match(corrected,/내가 확인한 기억/);assert.match(corrected,/해결됨/);
 }finally{await server.close();}
});

test('legacy answer citation rendering and epoch changes do not crash or retain deleted text',async()=>{
 const server=await createServer({configFile:false,server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
 try{
  const {MessageEvidence,mergeConversation,memoryEditBody}=await server.ssrLoadModule('/src/StudyChat.tsx');
  const artifact={body:{answer:'예전 답변',citations:[{source_id:'source'}],uncertainty:''},evidence:[{ref:{id:'source'},label:'교재',text:'원문'}],metadata:{model:'test'}};
  const html=renderToStaticMarkup(React.createElement(MessageEvidence,{artifact}));assert.match(html,/교재/);
  const old={id:'thread',epoch:'0:1',messages:[{ordinal:1,text:'삭제할 개인 내용'},...Array.from({length:40},(_,i)=>({ordinal:i+2,text:'남은 내용'}))]};
  const fresh={id:'thread',epoch:'0:2',messages:[{ordinal:41,text:'현재 내용'}]};
  assert.deepEqual(mergeConversation(old,fresh).messages,fresh.messages);
  const body=memoryEditBody({course_id:'course'},{revision:1},'내 수정','resolved');
  assert.equal(body.revision,1);
 }finally{await server.close();}
});
