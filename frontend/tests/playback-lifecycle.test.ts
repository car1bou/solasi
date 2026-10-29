import test from 'node:test';
import assert from 'node:assert/strict';
import * as lifecycleModule from '../src/native-lifecycle.ts';
import {NativeAudioController} from '../src/native-audio-controller.ts';

const turn=()=>new Promise<void>(resolve=>setImmediate(resolve));

test('successful navigation pauses every player; a blocked move keeps playback and callbacks active',async()=>{
  const {createPlaybackLifecycle}=await import('../src/playback-lifecycle.ts');
  const events=new EventTarget();
  Object.defineProperty(globalThis,'window',{configurable:true,value:events});
  const audio=[{paused:false,time:23,volume:.35},{paused:false,time:8,volume:.7}];
  const players=audio.map(item=>createPlaybackLifecycle(()=>{item.paused=true;},()=>true));
  const cleanup=players.map(player=>player.listen(events));
  let dirty=true,moves=0;
  const release=lifecycleModule.registerCloseGuard('전사 수정',()=>dirty);
  try{
    assert.equal(lifecycleModule.navigate(()=>moves++),false);
    assert(audio.every(item=>!item.paused));assert(players.every(player=>player.active()));
    dirty=false;assert.equal(lifecycleModule.navigate(()=>moves++),true);
    assert(audio.every(item=>item.paused));assert(players.every(player=>!player.active()));assert.equal(moves,1);
    players[0].interact();assert.equal(players[0].active(),true);assert.equal(players[1].active(),false);
    assert.deepEqual(audio.map(({time,volume})=>({time,volume})),[{time:23,volume:.35},{time:8,volume:.7}]);
  }finally{release();cleanup.forEach(stop=>stop());}
});

test('a hidden async result cannot autoplay or advance its playlist; returning requires an explicit interaction',async()=>{
  const {createPlaybackLifecycle}=await import('../src/playback-lifecycle.ts');
  let visible=false,plays=0,advances=0;
  const player=createPlaybackLifecycle(()=>{},()=>visible);
  player.interact();assert.equal(player.active(),false);
  const metadata=Promise.resolve().then(()=>{if(player.active())plays++;});
  const ended=Promise.resolve().then(()=>{if(player.active())advances++;});
  await Promise.all([metadata,ended]);assert.equal(plays,0);assert.equal(advances,0);
  const events=new EventTarget(),cleanup=player.listen(events);
  events.dispatchEvent(new Event('solasi-navigated'));
  visible=true;assert.equal(player.active(),false);
  player.interact();assert.equal(player.active(),true);
  if(player.active())plays++;assert.equal(plays,1);
  cleanup();assert.equal(player.active(),false);
});

test('navigation during native load prevents late metadata autoplay and playlist advance, then resumes cursor and volume',async()=>{
  const {createPlaybackLifecycle}=await import('../src/playback-lifecycle.ts');
  let finishLoad!:()=>void;
  const loading=new Promise<void>(resolve=>{finishLoad=resolve;}),events=new EventTarget();
  const players=new Map<string,{time:number;volume:number;playing:boolean}>();
  let advances=0,metadata=0;
  const controller=new NativeAudioController('/synthetic-audio',async fields=>{
    const id=fields.id as string;
    if(fields.op==='playback_load'){players.set(id,{time:0,volume:1,playing:false});await loading;}
    else if(fields.op==='playback_seek')players.get(id)!.time=fields.time as number;
    else if(fields.op==='playback_volume')players.get(id)!.volume=fields.volume as number;
    else if(fields.op==='playback_play')players.get(id)!.playing=true;
    else if(fields.op==='playback_release'){const time=players.get(id)!.time;players.delete(id);return {currentTime:time};}
    else if(fields.op==='playback_close')players.delete(id);
    return {};
  },(next,previous,event)=>{
    if(!event)return;
    if(next.ready&&!previous.ready)player.metadata(handle,event=>{metadata++;event.currentTarget.currentTime=23;void event.currentTarget.play();});
    if(player.active()&&next.ended)advances++;
  });
  const handle={get currentTime(){return controller.state.currentTime;},set currentTime(time:number){void controller.seek(time);},get duration(){return controller.state.duration;},get paused(){return controller.state.paused;},play:()=>controller.play(),pause:()=>{void controller.pause();}};
  const player=createPlaybackLifecycle(()=>{void controller.pause();},()=>true),cleanup=player.listen(events);
  await controller.setVolume(.35);
  const pending=controller.play();await turn();
  const first=[...players.keys()][0];events.dispatchEvent(new Event('solasi-navigated'));
  controller.receive({id:first,ready:true,duration:100,currentTime:0,paused:true,ended:false,seeked:false,error:''});
  finishLoad();await pending;await turn();
  assert.equal(metadata,0);assert.equal(advances,0);assert.equal(players.size,0);assert.equal(controller.state.currentTime,0);
  controller.receive({id:first,ready:true,duration:100,currentTime:100,paused:true,ended:true,seeked:false,error:''});
  assert.equal(advances,0);
  player.interact();await controller.play();assert.equal(metadata,1);
  const resumed=[...players.values()][0];assert.deepEqual(resumed,{time:23,volume:.35,playing:true});
  cleanup();await controller.dispose();assert.equal(players.size,0);
});


test('metadata arriving after navigation retains its initial seek without autoplay, then manual replay keeps that cursor',async()=>{
  const {createPlaybackLifecycle}=await import('../src/playback-lifecycle.ts');
  const events=new EventTarget();
  let time=0,paused=true,plays=0;
  const audio={get currentTime(){return time;},set currentTime(value:number){time=value;},duration:30,get paused(){return paused;},play:async()=>{plays++;paused=false;},pause:()=>{paused=true;}};
  const player=createPlaybackLifecycle(()=>audio.pause(),()=>true),cleanup=player.listen(events);
  events.dispatchEvent(new Event('solasi-navigated'));
  player.metadata(audio,event=>{event.currentTarget.currentTime=12;void event.currentTarget.play();});
  await Promise.resolve();assert.equal(time,0);assert.equal(plays,0);assert.equal(paused,true);
  player.interact();assert.equal(time,12);assert.equal(plays,0);await audio.play();assert.equal(time,12);assert.equal(plays,1);assert.equal(paused,false);
  cleanup();
});
