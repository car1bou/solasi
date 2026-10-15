import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';

test('review excerpts hide unverified labels while clear lecture conditions keep theirs',async()=>{
  const server=await createServer({configFile:false,server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
  try{
    const {default:SummarySection}=await server.ssrLoadModule('/src/SummarySection.tsx');
    const section={title:'원문 발췌',text:'제가 외동입니다.',subject:'그런 점',event_type:'expectation',review_required:true,evidence_ids:[],quotes:[]};
    const draw=(data:typeof section)=>renderToStaticMarkup(React.createElement(SummarySection,{section:data,evidence:[]}));
    const excerpt=draw(section);assert.match(excerpt,/제가 외동입니다/);assert.match(excerpt,/원문 발췌 · 생성 해석 확인 필요/);assert.doesNotMatch(excerpt,/그런 점|· 기대/);
    const invalidTitle=draw({...section,title:'원문 가정·조건 발췌',event_type:'hypothesis'});assert.doesNotMatch(invalidTitle,/가정|조건/);
    const clear=draw({...section,title:'보존 조건',text:'마찰이 없다고 가정하면 에너지가 보존됩니다.',subject:'마찰',event_type:'condition',review_required:false});
    assert.match(clear,/마찰 · 조건/);assert.doesNotMatch(clear,/생성 해석 확인 필요/);
  }finally{await server.close();}
});
