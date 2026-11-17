import test from 'node:test';
import assert from 'node:assert/strict';
import {api,nativeApp,nativeCommand} from '../src/api.ts';

function androidFixture(respond=true){
  const originalWindow=globalThis.window,originalLocation=globalThis.location;
  const page=new EventTarget(),sent:{id:string;message:Record<string,unknown>}[]=[];
  const bridge={postMessage(raw:string){
    const request=JSON.parse(raw);sent.push(request);
    if(respond)queueMicrotask(()=>bridge.onmessage?.({data:JSON.stringify({id:request.id,result:{status:200,text:'{"ready":true}'}})}));
  },onmessage:null as ((event:{data:string})=>void)|null};
  Object.assign(page,{top:page,self:page,SolasiNative:bridge});
  Object.defineProperty(globalThis,'window',{value:page,configurable:true});
  Object.defineProperty(globalThis,'location',{value:new URL('https://solasi.invalid/'),configurable:true});
  return {page,bridge,sent,reply(value:unknown){bridge.onmessage?.({data:JSON.stringify(value)});},restore(){page.dispatchEvent(new Event('pagehide'));Object.defineProperty(globalThis,'window',{value:originalWindow,configurable:true});Object.defineProperty(globalThis,'location',{value:originalLocation,configurable:true});}};
}

test('Android API routes structured native replies without network bootstrap',async()=>{
  const fixture=androidFixture(),oldFetch=globalThis.fetch;
  globalThis.fetch=async()=>{throw new Error('unexpected network fetch');};
  try{
    assert.equal(nativeApp(),true);
    assert.deepEqual(await api('/health'),{ready:true});
  }finally{globalThis.fetch=oldFetch;fixture.restore();}
});

test('Android transport refuses a foreign origin, credential URL, non-UI path and embedded frame',async()=>{
  const fixture=androidFixture();
  try{
    for(const url of ['https://example.com/','https://user@solasi.invalid/','https://solasi.invalid/other']){
      Object.defineProperty(globalThis,'location',{value:new URL(url),configurable:true});
      assert.equal(nativeApp(),false);
      await assert.rejects(nativeCommand({op:'ui_ready'}),/앱 연결/);
    }
    Object.defineProperty(globalThis,'location',{value:new URL('https://solasi.invalid/'),configurable:true});
    Object.assign(fixture.page,{top:{}});
    assert.equal(nativeApp(),false);
    await assert.rejects(nativeCommand({op:'ui_ready'}),/앱 연결/);
    assert.equal(fixture.sent.length,0);
  }finally{fixture.restore();}
});

test('Android replies preserve HTTP error status and correlate out-of-order results',async()=>{
  const fixture=androidFixture(false);
  try{
    const first=nativeCommand({op:'ui_ready'}),second=api('/courses');
    assert.equal(fixture.sent.length,2);
    const failure=assert.rejects(second,error=>error instanceof Error&&error.message==='revision conflict'&&(error as {status?:number}).status===409);
    fixture.reply({id:fixture.sent[1].id,result:{status:409,text:'{"detail":"revision conflict"}'}});
    fixture.reply({id:fixture.sent[0].id,result:{ready:true}});
    assert.deepEqual(await first,{ready:true});await failure;
  }finally{fixture.restore();}
});

test('Android rejects nested JSON and malformed HTTP results instead of reporting success',async()=>{
  const fixture=androidFixture(false);
  try{
    for(const result of ['{"status":200,"text":"{}"}',{status:200,text:{}},{status:0,text:'{}'},null]){
      const pending=api('/health'),failure=assert.rejects(pending,/응답/);
      fixture.reply({id:fixture.sent.at(-1)!.id,result});await failure;
    }
  }finally{fixture.restore();}
});

test('Android ignores replies after origin changes and cleans up a failed send',async()=>{
  const fixture=androidFixture(false);
  try{
    let settled=false;
    const pending=nativeCommand({op:'ui_ready'}).then(value=>{settled=true;return value;});
    Object.defineProperty(globalThis,'location',{value:new URL('https://example.com/'),configurable:true});
    fixture.reply({id:fixture.sent[0].id,result:{ready:true}});
    await Promise.resolve();assert.equal(settled,false);
    Object.defineProperty(globalThis,'location',{value:new URL('https://solasi.invalid/'),configurable:true});
    fixture.reply({id:fixture.sent[0].id,result:{ready:true}});await pending;
    const original=fixture.bridge.postMessage;
    fixture.bridge.postMessage=()=>{throw new Error('send failed');};
    await assert.rejects(nativeCommand({op:'ui_ready'}),/send failed/);
    fixture.bridge.postMessage=original;
    const next=nativeCommand({op:'ui_ready'});
    fixture.reply({id:fixture.sent.at(-1)!.id,result:{ready:true}});assert.deepEqual(await next,{ready:true});
  }finally{fixture.restore();}
});

test('Android AbortSignal cancellation targets the API ID, not the envelope ID',async()=>{
  const fixture=androidFixture(false),controller=new AbortController();
  try{
    const pending=api('/courses',{signal:controller.signal}),failure=assert.rejects(pending,error=>error instanceof DOMException&&error.name==='AbortError');
    const request=fixture.sent[0];controller.abort();
    assert.equal(fixture.sent[1].message.op,'cancel');
    assert.equal(fixture.sent[1].message.target,request.message.id);
    assert.notEqual(request.id,request.message.id);
    fixture.reply({id:fixture.sent[1].id,result:{cancelled:true}});
    fixture.reply({id:request.id,error:'Request cancelled'});await failure;
  }finally{fixture.restore();}
});

test('uncorrelated and malformed replies never settle another Android request',async()=>{
  const fixture=androidFixture(false);
  try{
    let settled=false;
    const pending=nativeCommand({op:'ui_ready'}).then(result=>{settled=true;return result;});
    fixture.reply({id:crypto.randomUUID(),error:'wrong request'});
    fixture.bridge.onmessage?.({data:'invalid json'});
    fixture.reply({error:'missing identity'});
    await Promise.resolve();assert.equal(settled,false);
    fixture.reply({id:fixture.sent[0].id,result:{ready:true}});
    assert.deepEqual(await pending,{ready:true});
    const invalid=nativeCommand({op:'ui_ready'}),failure=assert.rejects(invalid,/응답/);
    fixture.reply({id:fixture.sent[1].id,result:{ready:true},error:'ambiguous'});await failure;
  }finally{fixture.restore();}
});

test('Android rejects invalid commands and propagates a correlated native error',async()=>{
  const fixture=androidFixture(false);
  try{
    for(const message of [null,[],{op:'resource',path:'/private'},{op:'http',native_selected_files:['/private']},{op:'ui_ready',value:NaN}]){
      await assert.rejects(nativeCommand(message),/요청/);
    }
    assert.equal(fixture.sent.length,0);
    const pending=nativeCommand({op:'ui_ready'}),failure=assert.rejects(pending,/native unavailable/);
    fixture.reply({id:fixture.sent[0].id,error:'native unavailable'});await failure;
  }finally{fixture.restore();}
});

test('Android bounds pending requests, releases capacity and cleans up on pagehide',async()=>{
  const fixture=androidFixture(false);
  try{
    const pending=Array.from({length:32},()=>nativeCommand({op:'ui_ready'}));
    const results=Promise.allSettled(pending);
    await assert.rejects(nativeCommand({op:'ui_ready'}),/요청|대기/);
    assert.equal(fixture.sent.length,32);
    fixture.reply({id:fixture.sent[0].id,result:{ready:true}});
    assert.deepEqual(await pending[0],{ready:true});
    const replacement=nativeCommand({op:'ui_ready'}),closed=assert.rejects(replacement,/닫|종료/);
    assert.equal(fixture.sent.length,33);
    fixture.page.dispatchEvent(new Event('pagehide'));
    await closed;assert.equal((await results).filter(result=>result.status==='rejected').length,31);
    assert.equal(fixture.bridge.onmessage,null);
  }finally{fixture.restore();}
});

test('Android can cancel an HTTP request even when all 32 reply slots are occupied',async()=>{
  const fixture=androidFixture(false),controller=new AbortController();
  try{
    const target=api('/courses',{signal:controller.signal}),cancelled=assert.rejects(target,error=>error instanceof DOMException&&error.name==='AbortError');
    const pending=Array.from({length:31},()=>nativeCommand({op:'ui_ready'})),finished=Promise.allSettled(pending);
    controller.abort();
    assert.equal(fixture.sent.length,33);
    assert.equal(fixture.sent[32].message.op,'cancel');
    fixture.reply({id:fixture.sent[32].id,result:{cancelled:true}});await cancelled;
    fixture.page.dispatchEvent(new Event('pagehide'));await finished;
  }finally{fixture.restore();}
});

test('Android reply timeout rejects and frees the pending slot',async(t)=>{
  const fixture=androidFixture(false);
  t.mock.timers.enable({apis:['setTimeout']});
  try{
    const pending=nativeCommand({op:'ui_ready'}),failure=assert.rejects(pending,/시간/);
    t.mock.timers.tick(120001);await failure;
    const next=nativeCommand({op:'ui_ready'});
    fixture.reply({id:fixture.sent[1].id,result:{ready:true}});
    assert.deepEqual(await next,{ready:true});
  }finally{fixture.restore();t.mock.timers.reset();}
});

test('Android playback rejects private and foreign paths before contacting native',async()=>{
  const fixture=androidFixture();
  try{
    for(const path of ['https://example.com/audio','file:///private.wav','/api/assets/other/original','/api/recordings/'+'a'.repeat(32)+'/audio#foreign']){
      await assert.rejects(nativeCommand({op:'playback_load',id:'fixture',path}),/재생|경로/);
    }
    await assert.rejects(nativeCommand({op:'playback_seek',id:'fixture',time:-1}),/재생|시각/);
    await assert.rejects(nativeCommand({op:'playback_volume',id:'fixture',volume:2}),/음량/);
    assert.equal(fixture.sent.length,0);
  }finally{fixture.restore();}
});

test('Android HTML audio playback restores cursor and releases its source',async()=>{
  const fixture=androidFixture(),originalAudio=globalThis.Audio;
  class AudioFixture extends EventTarget{
    static instances:AudioFixture[]=[];
    readyState=1;duration=60;currentTime=0;paused=true;ended=false;error=null;volume=1;preload='';src:string;
    constructor(path:string){super();this.src=path;AudioFixture.instances.push(this);}
    load(){} async play(){this.paused=false;}pause(){this.paused=true;}removeAttribute(name:string){if(name==='src')this.src='';}
  }
  Object.defineProperty(globalThis,'Audio',{value:AudioFixture,configurable:true});
  try{
    const states:unknown[]=[];fixture.page.addEventListener('solasi-playback-state',event=>states.push((event as CustomEvent).detail));
    const path='/api/recordings/'+'a'.repeat(32)+'/audio';
    await nativeCommand({op:'playback_load',id:'fixture',path});
    await nativeCommand({op:'playback_seek',id:'fixture',time:12.5});
    await nativeCommand({op:'playback_play',id:'fixture'});
    const audio=AudioFixture.instances[0];audio.dispatchEvent(new Event('timeupdate'));
    assert.deepEqual(states.at(-1),{id:'fixture',ready:true,duration:60,currentTime:12.5,paused:false,ended:false,seeked:false,error:''});
    const snapshot=await nativeCommand<{currentTime:number;paused:boolean}>({op:'playback_release',id:'fixture'});
    assert.equal(snapshot.currentTime,12.5);assert.equal(audio.src,'');assert.equal(audio.paused,true);
    await nativeCommand({op:'playback_load',id:'fixture',path});
    await nativeCommand({op:'playback_seek',id:'fixture',time:snapshot.currentTime});
    assert.equal(AudioFixture.instances[1].currentTime,12.5);
    fixture.page.dispatchEvent(new Event('pagehide'));assert.equal(AudioFixture.instances[1].src,'');
    assert.equal(fixture.sent.length,0);
  }finally{fixture.restore();Object.defineProperty(globalThis,'Audio',{value:originalAudio,configurable:true});}
});
