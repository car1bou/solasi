import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';

test('job status shows ASR waiting only while active and keeps cancel/retry controls',async()=>{
  const server=await createServer({configFile:false,server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
  try{
    const {default:JobProgress}=await server.ssrLoadModule('/src/JobProgress.tsx');
    const draw=(status:string)=>renderToStaticMarkup(React.createElement(JobProgress,{job:{id:'fixture',kind:'search',status,error:null,result:{paused_reason:'전사 처리 후 실행'}},onChange:()=>{}}));
    const waiting=draw('running');assert.match(waiting,/전사 처리 후 실행/);assert.match(waiting,/작업 취소/);assert.doesNotMatch(waiting,/같은 요청 재시도/);
    const done=draw('done');assert.match(done,/완료/);assert.doesNotMatch(done,/전사 처리 후 실행|작업 취소/);
    const cancelled=draw('cancelled');assert.match(cancelled,/취소됨/);assert.match(cancelled,/같은 요청 재시도/);assert.doesNotMatch(cancelled,/전사 처리 후 실행/);
  }finally{await server.close();}
});
