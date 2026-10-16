import test from 'node:test';
import assert from 'node:assert/strict';
import * as lifecycle from '../src/native-lifecycle.ts';
const {createCloseLifecycle,registerCloseGuard}=lifecycle;

test('internal navigation keeps unsaved inputs mounted and names every blocking editor',()=>{
  const events=new EventTarget();
  Object.defineProperty(globalThis,'window',{configurable:true,value:events});
  let dirty=true,moves=0,finished=0,message='';
  events.addEventListener('solasi-navigation-blocked',event=>{message=(event as CustomEvent<string>).detail;});
  events.addEventListener('solasi-finish-ink',()=>{finished++;});
  const release=registerCloseGuard('회차 노트',()=>dirty),other=registerCloseGuard('전사 수정',()=>dirty);
  try{
    assert.equal(typeof lifecycle.navigate,'function');
    assert.equal(lifecycle.navigate(()=>moves++),false);
    assert.equal(moves,0);assert.match(message,/회차 노트.*전사 수정.*저장/);assert.equal(finished,0);
    dirty=false;assert.equal(lifecycle.navigate(()=>moves++),true);
    assert.equal(moves,1);assert.equal(finished,1);
  }finally{release();other();}
  assert.equal(lifecycle.navigate(()=>moves++),true);assert.equal(moves,2);
});

test('replacing a result preserves its request form but still blocks a nested dirty editor',()=>{
  Object.defineProperty(globalThis,'window',{configurable:true,value:new EventTarget()});
  let edited=false,moves=0;
  const request=registerCloseGuard('질문 입력',()=>true),editor=registerCloseGuard('회의록 수정',()=>edited);
  try{
    assert.equal(lifecycle.navigate(()=>moves++,['질문 입력']),true);
    edited=true;assert.equal(lifecycle.navigate(()=>moves++,['질문 입력']),false);
    assert.equal(moves,1);
  }finally{request();editor();}
});

test('native close blocks unsaved scoped editors, flushes before close and thaws on failure',async()=>{
  const root={inert:false},events=new EventTarget();
  Object.defineProperty(globalThis,'document',{configurable:true,value:{getElementById:()=>root}});
  Object.defineProperty(globalThis,'window',{configurable:true,value:events});
  let dirty=true,flushes=0,resumed=0,failed=false,finishedInk=0;
  events.addEventListener('solasi-finish-ink',()=>{assert.equal(root.inert,false);finishedInk++;});
  const unregister=registerCloseGuard('회차 노트',()=>dirty);
  const close=createCloseLifecycle(async()=>{flushes++;assert.equal(root.inert,true);if(failed)throw new Error('disk full');},()=>{resumed++;});
  try{
    await assert.rejects(close.prepareClose(),/회차 노트.*저장하지 않은 수정/);
    assert.equal(flushes,0);assert.equal(root.inert,false);
    dirty=false;await close.prepareClose();assert.equal(root.inert,true);assert.equal(flushes,1);
    close.resume();assert.equal(root.inert,false);
    failed=true;await assert.rejects(close.prepareClose(),/disk full/);assert.equal(root.inert,false);
    failed=false;await close.prepareClose();assert.equal(root.inert,true);
    assert.equal(resumed,2);assert.equal(finishedInk,3);
  }finally{unregister();close.resume();}
});

test('a timed out close cannot freeze or approve after the user resumes editing',async()=>{
  const root={inert:false};
  Object.defineProperty(globalThis,'document',{configurable:true,value:{getElementById:()=>root}});
  Object.defineProperty(globalThis,'window',{configurable:true,value:new EventTarget()});
  let release!:()=>void,resumed=0;
  const close=createCloseLifecycle(()=>new Promise<void>(resolve=>{release=resolve;}),()=>{resumed++;});
  const pending=close.prepareClose();assert.equal(root.inert,true);
  close.resume();assert.equal(root.inert,false);release();
  await assert.rejects(pending,/취소/);
  assert.equal(root.inert,false);assert.equal(resumed,1);
});
