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

test('confirmed ink without an OCR box still displays its saved strokes',async()=>{
  const server=await createServer({configFile:false,server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
  try{
    const {SourceImage}=await server.ssrLoadModule('/src/SourceLink.tsx');
    const source={image_url:'/page.png',ref:{kind:'ink_note',page:1,bbox:null,source_width:600,source_height:800},ink_snapshot:[{id:'line',tool:'pen',color:'#123456',width:.01,opacity:1,input:'pen',points:[{x:.1,y:.2,pressure:.5},{x:.5,y:.3,pressure:.7}]}]};
    const html=renderToStaticMarkup(React.createElement(SourceImage,{source}));
    assert.match(html,/<svg/);assert.match(html,/<path/);assert.match(html,/#123456/);assert.doesNotMatch(html,/<rect/);
    source.ref.bbox=[.1,.2,.4,.1] as any;
    assert.match(renderToStaticMarkup(React.createElement(SourceImage,{source})),/<rect/);
  }finally{await server.close();}
});

test('source image and ink overlay keep the same box in short windows',async()=>{
 const {readFile}=await import('node:fs/promises');
 const css=await readFile(new URL('../src/styles.css',import.meta.url),'utf8');
 assert.match(css,/\.source-dialog \.ink-region-preview img\s*\{[^}]*max-height:\s*none/);
 assert.match(css,/\.source-dialog \.ink-region-preview img\s*\{[^}]*height:\s*auto/);
});

test('recognition model identities wrap inside a narrow review panel',async()=>{
 const {readFile}=await import('node:fs/promises');
 const css=await readFile(new URL('../src/styles.css',import.meta.url),'utf8');
 assert.match(css,/\.knowledge-candidate\s*\{[^}]*overflow-wrap:\s*anywhere/);
});
