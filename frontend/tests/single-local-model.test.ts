import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';

test('native local settings require no model ID choice and handwriting has no model comparison buttons',async()=>{
 Object.defineProperty(globalThis,'location',{value:{protocol:'solasi-app:'},configurable:true});
 const server=await createServer({configFile:false,server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
 try{
  const {default:Settings}=await server.ssrLoadModule('/src/SettingsView.tsx');
  const settings=renderToStaticMarkup(React.createElement(Settings));
  assert.doesNotMatch(settings,/모델 ID|local-models/);assert.match(settings,/API 키/);
  const {default:Review}=await server.ssrLoadModule('/src/HandwritingReview.tsx');
  const review=renderToStaticMarkup(React.createElement(Review,{courseId:'c',assetId:'a',page:1,digest:'a'.repeat(64),revision:1,saved:true,width:100,height:100}));
  assert.doesNotMatch(review,/Gemma|12B|Qwen|수식 대조/);assert.match(review,/손글씨 인식/);assert.match(review,/다시 읽기/);
 }finally{await server.close();Reflect.deleteProperty(globalThis,'location');}
});
