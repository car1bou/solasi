import test from 'node:test';
import assert from 'node:assert/strict';
import {NativeAudioController,type NativeAudioState} from '../src/native-audio-controller.ts';

const turn=()=>new Promise<void>(resolve=>setImmediate(resolve));
function fixture(){
  const players=new Map<string,{time:number;playing:boolean;volume:number}>(),calls:Record<string,unknown>[]=[],events:{state:NativeAudioState;previous:NativeAudioState;event:boolean}[]=[];
  let failLoad=false,releaseGate:Promise<void>|null=null;
  const controller=new NativeAudioController('/api/recordings/'+ 'a'.repeat(32)+'/audio',async fields=>{
    calls.push(fields);const id=fields.id as string;
    if(fields.op==='playback_load'){
      if(failLoad){failLoad=false;throw new Error('load failed');}
      assert(players.size<16);players.set(id,{time:0,playing:false,volume:1});
    }else if(fields.op==='playback_close'){players.delete(id);}
    else{
      const player=players.get(id);assert(player,'command used a released player');
      if(fields.op==='playback_seek')player.time=fields.time as number;
      if(fields.op==='playback_volume')player.volume=fields.volume as number;
      if(fields.op==='playback_play')player.playing=true;
      if(fields.op==='playback_release'){
        if(releaseGate)await releaseGate;
        player.playing=false;players.delete(id);return {currentTime:player.time,paused:true};
      }
    }
    return {accepted:true};
  },(state,previous,event)=>events.push({state,previous,event}));
  const id=()=>[...players.keys()].at(-1)!;
  const send=(overrides:Partial<NativeAudioState>&{id?:string}={})=>controller.receive({id:id(),ready:true,duration:100,currentTime:0,paused:false,ended:false,seeked:false,error:'',...overrides});
  return {controller,players,calls,events,id,send,failNextLoad:()=>{failLoad=true;},blockRelease:(gate:Promise<void>)=>{releaseGate=gate;}};
}

test('more than 16 paused/ended recordings release players and resume cursor/volume without metadata reset',async()=>{
  const f=fixture();let first='';
  for(let n=0;n<20;n++){
    await f.controller.play();const id=f.id();if(!first)first=id;
    f.players.get(id)!.time=n+0.25;f.send({currentTime:n+0.25});
    if(n%2){f.send({currentTime:n+0.25,ended:true});await turn();}
    else await f.controller.pause();
    assert.equal(f.players.size,0);assert.equal(f.controller.state.currentTime,n+0.25);
  }
  await f.controller.setVolume(.35);await f.controller.play();
  assert.notEqual(f.id(),first);assert.equal(f.players.get(f.id())!.time,19.25);assert.equal(f.players.get(f.id())!.volume,.35);
  f.send({currentTime:19.25});
  assert.equal(f.events.filter(e=>e.event&&e.state.ready&&!e.previous.ready).length,1);
  f.send({id:first,currentTime:0,error:'stale'});assert.equal(f.controller.state.error,'');assert.equal(f.controller.state.currentTime,19.25);
  await f.controller.dispose();assert.equal(f.players.size,0);
});

test('a seek queued while pause is completing keeps its new position and starts after restore',async()=>{
  const f=fixture();await f.controller.play();f.players.get(f.id())!.time=12;f.send({currentTime:12});
  let release!:()=>void;f.blockRelease(new Promise<void>(resolve=>{release=resolve;}));
  const pause=f.controller.pause();await turn();
  const seek=f.controller.seek(45),play=f.controller.play();release();
  await Promise.all([pause,seek,play]);assert.equal(f.controller.state.currentTime,45);
  const id=f.id();assert.equal(f.players.get(id)!.time,45);assert.equal(f.players.get(id)!.playing,true);
  assert(f.calls.findIndex(call=>call.op==='playback_seek'&&call.id===id)<f.calls.findIndex(call=>call.op==='playback_play'&&call.id===id));
  await f.controller.dispose();
});

test('paused preload releases its native player and a failed load can be retried',async()=>{
  const f=fixture();f.failNextLoad();await assert.rejects(f.controller.preload(),/load failed/);
  await f.controller.preload();f.send({paused:true});await turn();assert.equal(f.players.size,0);
  await f.controller.seek(23);f.send({paused:true,currentTime:23,seeked:true});await turn();assert.equal(f.players.size,0);
  await f.controller.play();assert.equal(f.players.get(f.id())!.time,23);await f.controller.dispose();
});

test('dispose during load prevents queued play and closes the acquired resource',async()=>{
  let release!:()=>void;const gate=new Promise<void>(resolve=>{release=resolve;}),calls:string[]=[];
  const controller=new NativeAudioController('/audio',async fields=>{calls.push(fields.op as string);if(fields.op==='playback_load')await gate;return {};},()=>{});
  const play=controller.play();await turn();const dispose=controller.dispose();release();await Promise.all([play,dispose]);
  assert(!calls.includes('playback_play'));assert.equal(calls.at(-1),'playback_close');
});
