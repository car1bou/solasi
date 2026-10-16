import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';

test('workspace keeps keyboard entry, visible course label and expandable readiness',async()=>{
  const server=await createServer({configFile:false,server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
  try{
    const {default:App}=await server.ssrLoadModule('/src/App.tsx');
    const html=renderToStaticMarkup(React.createElement(App));
    assert.match(html,/href="#workspace"/);
    assert.match(html,/<main id="workspace" tabindex="-1"/);
    assert.match(html,/<label for="course-title">새 과목<\/label>/);
    assert.match(html,/<input id="course-title"/);
    assert.match(html,/aria-label="Solasi 홈"/);
    assert.equal((html.match(/src="\/solasi-icon.png"/g)||[]).length,1);
    assert.match(html,/<details><summary>/);
    assert.match(html,/확인 중…/);
    assert.doesNotMatch(html,/0 \/ 0 준비됨/);
  }finally{await server.close();}
});

test('summary instructions have an action-specific label while answers keep the question label',async()=>{
  const server=await createServer({configFile:false,server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
  try{
    const {default:QuestionView}=await server.ssrLoadModule('/src/QuestionView.tsx');
    const draw=(kind:string)=>renderToStaticMarkup(React.createElement(QuestionView,{session:{id:'fixture'},kind}));
    assert.match(draw('summary'),/<label>요약 지침<textarea/);
    assert.match(draw('answer'),/<label>질문<textarea/);
  }finally{await server.close();}
});

test('long summary shows prepared work before its first result and never resets saved work to zero',async()=>{
  const server=await createServer({configFile:false,server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
  try{
    const {SummaryProgress}=await server.ssrLoadModule('/src/QuestionView.tsx');
    assert.equal(typeof SummaryProgress,'function');
    const draw=(status:string,result:unknown=null,request:unknown={summary_parts:[[],[],[],[],[]]})=>renderToStaticMarkup(React.createElement(SummaryProgress,{job:{status,result,request}}));
    assert.match(draw('running'),/완료 구간 0\/5/);
    assert.match(draw('running',{completed_parts:2,total_parts:5}),/완료 구간 2\/5/);
    assert.match(draw('failed',{completed_parts:2,total_parts:5}),/완료 구간 2\/5/);
    assert.equal(draw('done',{id:'saved'}),'');
    assert.equal(draw('running',null,{}),'');
  }finally{await server.close();}
});
