import test from 'node:test';
import assert from 'node:assert/strict';
import {nativeApp,nativeCommand,api} from '../src/api.ts';
import {installWindowsBridge} from '../src/windows-bridge.ts';

test('Windows bridge is accepted only at the private HTTPS app origin',async()=>{
  const originalWindow=globalThis.window,originalLocation=globalThis.location;
  const calls:unknown[]=[];
  try{
    const bridge={command:async(message:unknown)=>{calls.push(message);return {status:200,text:'{"ready":true}'};}};
    Object.defineProperty(globalThis,'window',{value:{solasiWindows:bridge,pywebview:{api:{command:bridge.command}}},configurable:true});
    Object.defineProperty(globalThis,'location',{value:new URL('https://solasi.invalid/'),configurable:true});
    installWindowsBridge();
    assert.equal(nativeApp(),true);
    assert.deepEqual(await api('/health'),{ready:true});
    assert.equal((calls[0] as {path:string}).path,'/api/health');
    Object.defineProperty(globalThis,'location',{value:new URL('https://example.com/'),configurable:true});
    assert.equal(nativeApp(),false);
    await assert.rejects(nativeCommand({op:'http'}),/앱 연결/);
  }finally{
    Object.defineProperty(globalThis,'window',{value:originalWindow,configurable:true});
    Object.defineProperty(globalThis,'location',{value:originalLocation,configurable:true});
  }
});

test('Windows native playback refuses arbitrary URLs and invalid arguments',async()=>{
  const originalWindow=globalThis.window,originalLocation=globalThis.location;
  try{
    Object.defineProperty(globalThis,'window',{value:{solasiWindows:{command:async()=>({})},pywebview:{api:{command:async()=>({})}}},configurable:true});
    Object.defineProperty(globalThis,'location',{value:new URL('https://solasi.invalid/'),configurable:true});
    installWindowsBridge();
    for(const path of ['https://example.com/audio','file:///C:/private.wav','/api/assets/other/original']){
      await assert.rejects(nativeCommand({op:'playback_load',id:'fixture',path}),/재생|경로/);
    }
    await assert.rejects(nativeCommand({op:'playback_seek',id:'fixture',time:NaN}),/재생|시각/);
    await assert.rejects(nativeCommand({op:'playback_volume',id:'fixture',volume:2}),/음량/);
  }finally{
    Object.defineProperty(globalThis,'window',{value:originalWindow,configurable:true});
    Object.defineProperty(globalThis,'location',{value:originalLocation,configurable:true});
  }
});
