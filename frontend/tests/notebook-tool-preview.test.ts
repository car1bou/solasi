import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';

test('tool preview uses applied settings, rendering changes without modifying the tools',async()=>{
 const server=await createServer({configFile:false,server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
 try{
  const {default:Preview}=await server.ssrLoadModule('/src/NotebookToolPreview.tsx');
  const {defaultTools}=await server.ssrLoadModule('/src/notebook-preferences.ts');
  const tools={...defaultTools,tool:'pen',penColor:'#123456',penWidth:.004,penOpacity:.8};
  const before=structuredClone(tools);
  const render=(changes={})=>renderToStaticMarkup(React.createElement(Preview,{tools:{...tools,...changes}}));
  const pen=render();assert.match(pen,/aria-hidden="true"/);assert.match(pen,/<path[^>]*fill="#123456" opacity="0.8"/);
  const highlighter=render({tool:'highlighter',highlighterColor:'#ffcc00',highlighterOpacity:.3});
  assert.match(highlighter,/<path[^>]*fill="#ffcc00" opacity="0.3"/);
  assert.notEqual(render({penWidth:.02}),pen);
  const text=render({tool:'text',textSize:.05});assert.match(text,/font-size:34px/);assert.match(text,/가 Aa/);assert.match(text,/color:#123456/);
  for(const tool of ['stroke-eraser','partial-eraser']){
   const eraser=render({tool,eraserSize:.02});assert.match(eraser,/<circle[^>]*r="13.6"/);assert.doesNotMatch(eraser,/<path|foreignObject/);
  }
  assert.deepEqual(tools,before);
 }finally{await server.close();}
});
