import test from 'node:test';
import assert from 'node:assert/strict';
import {subscribeNativeAudio} from '../src/native-playback-links.ts';
import type {NativeClip} from '../src/native-playback-links.ts';

test('cold native link is received even when delivered synchronously with UI readiness',async()=>{
  Object.defineProperty(globalThis,'location',{configurable:true,value:new URL('solasi-app://app/')});
  const windowTarget=new EventTarget(),clip={url:'/api/recordings/'+'a'.repeat(32)+'/audio',start:12,end:15};
  const received:NativeClip[]=[],errors:string[]=[];
  const host=Object.assign(windowTarget,{webkit:{messageHandlers:{solasi:{postMessage:async(message:{op:string})=>{
    assert.equal(message.op,'ui_ready');
    windowTarget.dispatchEvent(new CustomEvent('solasi-open-audio',{detail:clip}));
    return {ready:true};
  }}}}});
  Object.defineProperty(globalThis,'window',{configurable:true,value:host});
  const unsubscribe=subscribeNativeAudio(value=>received.push(value),message=>errors.push(message));
  await Promise.resolve();
  assert.deepEqual(received,[clip]);assert.deepEqual(errors,[]);
  for(const invalid of [{...clip,url:'file:///private/note'},{...clip,start:-1},{...clip,end:Infinity},{...clip,end:clip.start}])windowTarget.dispatchEvent(new CustomEvent('solasi-open-audio',{detail:invalid}));
  assert.equal(received.length,1);
  unsubscribe();windowTarget.dispatchEvent(new CustomEvent('solasi-open-audio',{detail:clip}));
  assert.equal(received.length,1);
});

test('native ready failure is reported only while the listener is mounted',async()=>{
  const errors:string[]=[];let reject!:(error:Error)=>void;
  Object.defineProperty(globalThis,'location',{configurable:true,value:new URL('solasi-app://app/')});
  const host=Object.assign(new EventTarget(),{webkit:{messageHandlers:{solasi:{postMessage:()=>new Promise((_,fail)=>{reject=fail;})}}}});
  Object.defineProperty(globalThis,'window',{configurable:true,value:host});
  const unsubscribe=subscribeNativeAudio(()=>{},message=>errors.push(message));
  unsubscribe();reject(new Error('closed'));await new Promise(resolve=>setTimeout(resolve,0));
  assert.deepEqual(errors,[]);
});
