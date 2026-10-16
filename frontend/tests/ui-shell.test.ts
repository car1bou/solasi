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
