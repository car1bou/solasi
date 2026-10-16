import assert from 'node:assert/strict';
import test from 'node:test';
import {RecordingCapture} from '../src/recording-capture.ts';

const flush=async()=>{for(let i=0;i<40;i++)await Promise.resolve();};

test('bundled capture uses native commands and follows saved-frame state without browser audio',async t=>{
  const events=new EventTarget(),messages:any[]=[],states:any[]=[];
  const nativeWindow=Object.assign(events,{webkit:{messageHandlers:{solasi:{async postMessage(message:any){messages.push(message);return {accepted:true};}}}}});
  for(const [key,value] of Object.entries({window:nativeWindow,location:new URL('solasi-app://app/')})){
    const old=Object.getOwnPropertyDescriptor(globalThis,key);Object.defineProperty(globalThis,key,{value,configurable:true});
    t.after(()=>{if(old)Object.defineProperty(globalThis,key,old);else Reflect.deleteProperty(globalThis,key);});
  }
  const capture=new RecordingCapture('a'.repeat(32),state=>states.push(state));
  await capture.start();assert.equal(messages[0].op,'audio_start');assert.equal(messages[0].transcription_mode,'after_stop');
  events.dispatchEvent(new CustomEvent('solasi-recording-state',{detail:{capture_id:'other',phase:'idle',seconds:9,pending:0,error:'',recovered:false}}));
  assert.equal(states.at(-1).phase,'starting');
  events.dispatchEvent(new CustomEvent('solasi-recording-state',{detail:{capture_id:messages[0].capture_id,phase:'recording',seconds:2,pending:.25,error:'',recovered:false}}));
  assert.equal(states.at(-1).phase,'recording');assert.equal(states.at(-1).seconds,2);
  await capture.stop();assert.equal(messages[1].op,'audio_stop');assert.equal(states.at(-1).phase,'idle');
  events.dispatchEvent(new CustomEvent('solasi-recording-state',{detail:{capture_id:messages[0].capture_id,phase:'recording',seconds:3,pending:0,error:'',recovered:false}}));
  assert.equal(states.at(-1).phase,'idle');
});
function setup(t:any){
  t.mock.timers.enable({apis:['setTimeout','setInterval','Date'],now:100000});
  const calls:any[]=[],nodes:any[]=[],contexts:any[]=[],sockets:any[]=[];let count=0,acquisitions=0,ack=true,flushReply=true;
  class Track extends EventTarget{readyState='live';muted=false;stop(){this.readyState='ended';}}
  const track=new Track(),stream={getTracks:()=>[track],getAudioTracks:()=>[track]};
  class Context extends EventTarget{
    sampleRate=48000;state='suspended';onstatechange:any=null;audioWorklet={addModule:async()=>{}};destination={};
    constructor(){super();contexts.push(this);}
    dispatchEvent(event:Event){this.onstatechange?.(event);return super.dispatchEvent(event);}
    createMediaStreamSource(){return {connect(){},disconnect(){}};}
    createGain(){return {gain:{value:0},connect(){},disconnect(){}};}
    async resume(){this.state='running';this.dispatchEvent(new Event('statechange'));}
    async close(){this.state='closed';}
  }
  class Worklet extends EventTarget{
    end=0;seq=0;stopTrackState='';port:any={onmessage:null,postMessage:(m:any)=>{if(m.type==='stop')this.stopTrackState=track.readyState;if(m.type==='stop'&&flushReply)queueMicrotask(()=>this.port.onmessage?.({data:{type:'stopped',end_frame:this.end}}));}};
    constructor(){super();nodes.push(this);}
    connect(){}disconnect(){}
    frame(){const first=this.end;this.end+=12000;this.port.onmessage?.({data:{type:'frame',seq:this.seq++,first_frame:first,samples:new Int16Array(12000)}});}
  }
  class Socket{
    static OPEN=1;readyState=1;sentFrames=0;onopen:any;onmessage:any;onclose:any;onerror:any;
    constructor(){sockets.push(this);queueMicrotask(()=>this.onopen?.());}
    send(data:any){if(typeof data==='string'){queueMicrotask(()=>this.onmessage?.({data:JSON.stringify({type:'ready'})}));return;}
      this.sentFrames+=new DataView(data).getUint32(16,true);
      if(ack){const v=new DataView(data),seq=Number(v.getBigUint64(0,true)),frame_count=v.getUint32(16,true);queueMicrotask(()=>this.onmessage?.({data:JSON.stringify({type:'ack',seq,frame_count})}));}}
    close(){this.readyState=3;}
  }
  for(const [key,value] of Object.entries({AudioContext:Context,AudioWorkletNode:Worklet,WebSocket:Socket,navigator:{mediaDevices:{getUserMedia:async()=>{acquisitions++;return stream;}}},location:{host:'127.0.0.1:8765',hash:'',pathname:'/'},history:{replaceState(){}}})){const old=Object.getOwnPropertyDescriptor(globalThis,key);Object.defineProperty(globalThis,key,{value,configurable:true,writable:true});t.after(()=>{if(old)Object.defineProperty(globalThis,key,old);else Reflect.deleteProperty(globalThis,key);});}
  t.mock.method(globalThis,'fetch',async(url:any,options:any)=>{const body=options?.body?JSON.parse(options.body):null;calls.push({url,body,trackState:track.readyState});return new Response(JSON.stringify(String(url).endsWith('/client')?{csrf_token:'test'}:String(url).endsWith('/audio/start')?{recording_id:String(++count).padStart(32,'0')}:{id:'job'}),{headers:{'Content-Type':'application/json'}});});
  const states:any[]=[];const capture=new RecordingCapture('session',(s:any)=>states.push({...s}));
  t.after(async()=>{const stopped=capture.stop(true);await flush();t.mock.timers.tick(20000);await flush();await stopped;t.mock.timers.reset();});
  return {capture,states,calls,nodes,contexts,sockets,track,acquisitions:()=>acquisitions,setAck:(v:boolean)=>{ack=v;},setFlush:(v:boolean)=>{flushReply=v;},tick:async(ms:number)=>{t.mock.timers.tick(ms);await flush();}};
}

test('silent PCM plus durable ACK stays healthy beyond the watchdog window',async t=>{
  const f=setup(t);await f.capture.start();
  for(let i=0;i<32;i++){f.nodes.at(-1).frame();await flush();await f.tick(250);}
  assert.equal(f.states.at(-1).phase,'recording');assert.equal(f.calls.filter(c=>c.url.endsWith('/audio/start')).length,1);
  await f.capture.stop();assert.equal(f.track.readyState,'ended');assert.equal(f.nodes[0].stopTrackState,'live');assert.equal(f.calls.find(c=>c.url.endsWith('/stop')).trackState,'ended');
});

test('missing PCM opens one new segment without acquiring another microphone',async t=>{
  const f=setup(t);await f.capture.start();f.nodes[0].frame();await flush();await f.tick(6000);
  assert.equal(f.states.at(-1).phase,'recovering');assert.equal(f.calls.filter(c=>c.url.endsWith('/audio/start')).length,2);
  f.nodes.at(-1).frame();await flush();assert.equal(f.states.at(-1).phase,'recording');assert.equal(f.states.at(-1).recovered,true);assert.equal(f.acquisitions(),1);
  assert.equal(f.calls.find(c=>c.url.endsWith('/stop')).body.interrupted,true);
  await f.tick(6000);assert.equal(f.states.at(-1).phase,'idle');assert.equal(f.track.readyState,'ended');assert.equal(f.calls.filter(c=>c.url.endsWith('/audio/start')).length,2);
});

test('no ACK with no further PCM cannot remain recording forever',async t=>{
  const f=setup(t);f.setAck(false);await f.capture.start();f.nodes[0].frame();await flush();await f.tick(6000);await f.tick(3000);await f.tick(1000);
  assert.ok(f.states.some(s=>s.phase==='recovering'));assert.equal(f.calls.filter(c=>c.url.endsWith('/audio/start')).length,2);
});

test('ended microphone is terminal and never prompts for a replacement',async t=>{
  const f=setup(t);await f.capture.start();f.nodes[0].frame();await flush();f.track.readyState='ended';f.track.dispatchEvent(new Event('ended'));await flush();
  assert.equal(f.states.at(-1).phase,'idle');assert.equal(f.acquisitions(),1);assert.equal(f.calls.filter(c=>c.url.endsWith('/audio/start')).length,1);
});

test('suspended context recovers into a new segment and stop prevents late revival',async t=>{
  const f=setup(t);await f.capture.start();f.nodes[0].frame();await flush();f.contexts[0].state='suspended';f.contexts[0].dispatchEvent(new Event('statechange'));await flush();
  f.nodes[0].frame();await flush();await f.tick(250);
  assert.equal(f.calls.filter(c=>c.url.endsWith('/audio/start')).length,2);await f.capture.stop();await f.tick(20000);
  assert.equal(f.states.at(-1).phase,'idle');assert.equal(f.track.readyState,'ended');assert.ok(f.contexts.every(c=>c.state==='closed'));
});

test('WebKit interruption waits for fresh unmuted input before spending the one recovery',async t=>{
  const f=setup(t);await f.capture.start();f.nodes[0].frame();await flush();
  t.mock.method(f.contexts[0],'resume',async()=>{});
  f.contexts[0].state='interrupted';f.contexts[0].dispatchEvent(new Event('statechange'));await flush();
  await f.tick(60000);
  assert.equal(f.calls.filter(c=>c.url.endsWith('/audio/start')).length,1);
  assert.equal(f.states.at(-1).phase,'recovering');
  f.contexts[0].state='running';f.contexts[0].dispatchEvent(new Event('statechange'));await f.tick(250);
  assert.equal(f.calls.filter(c=>c.url.endsWith('/audio/start')).length,1);
  f.track.muted=true;f.nodes[0].frame();await flush();f.track.muted=false;await f.tick(250);
  assert.equal(f.calls.filter(c=>c.url.endsWith('/audio/start')).length,1);
  f.nodes[0].frame();await flush();await f.tick(250);
  assert.equal(f.calls.filter(c=>c.url.endsWith('/audio/start')).length,2);
  f.nodes.at(-1).frame();await flush();assert.equal(f.states.at(-1).phase,'recording');assert.equal(f.acquisitions(),1);
});

test('stop during WebKit interruption cannot revive recording',async t=>{
  const f=setup(t);await f.capture.start();f.nodes[0].frame();await flush();
  t.mock.method(f.contexts[0],'resume',async()=>{});
  f.contexts[0].state='interrupted';f.contexts[0].dispatchEvent(new Event('statechange'));await flush();
  await f.capture.stop();f.contexts[0].state='running';await f.tick(250);
  assert.equal(f.calls.filter(c=>c.url.endsWith('/audio/start')).length,1);
  assert.equal(f.states.at(-1).phase,'idle');assert.equal(f.track.readyState,'ended');
});

test('ended microphone during WebKit interruption closes without acquiring again',async t=>{
  const f=setup(t);await f.capture.start();f.nodes[0].frame();await flush();
  t.mock.method(f.contexts[0],'resume',async()=>{});
  f.contexts[0].state='interrupted';f.contexts[0].dispatchEvent(new Event('statechange'));await flush();
  f.track.readyState='ended';f.track.dispatchEvent(new Event('ended'));await f.tick(250);
  assert.equal(f.states.at(-1).phase,'idle');assert.equal(f.calls.filter(c=>c.url.endsWith('/audio/start')).length,1);assert.equal(f.acquisitions(),1);
});

test('rejected WebKit resume is reported instead of waiting forever',async t=>{
  const f=setup(t);await f.capture.start();f.nodes[0].frame();await flush();
  t.mock.method(f.contexts[0],'resume',async()=>{throw new Error('resume refused');});
  f.contexts[0].state='interrupted';f.contexts[0].dispatchEvent(new Event('statechange'));await flush();await f.tick(250);
  assert.equal(f.states.at(-1).phase,'idle');assert.match(f.states.at(-1).error,/resume refused/);assert.equal(f.calls.filter(c=>c.url.endsWith('/audio/start')).length,1);
});

test('missing worklet flush response is persisted as interrupted',async t=>{
  const f=setup(t);await f.capture.start();f.nodes[0].frame();await flush();f.setFlush(false);const stopped=f.capture.stop();await flush();await f.tick(1000);await stopped;
  assert.equal(f.calls.find(c=>c.url.endsWith('/stop')).body.interrupted,true);assert.equal(f.states.at(-1).phase,'idle');assert.match(f.states.at(-1).error,/마지막 오디오/);
});


test('continuous PCM without ACK triggers recovery on ACK age',async t=>{
  const f=setup(t);f.setAck(false);await f.capture.start();
  for(let i=0;i<24;i++){f.nodes[0].frame();await flush();await f.tick(250);}
  assert.ok(f.states.some(s=>s.phase==='recovering'&&/저장 확인/.test(s.error)));
});

test('muted microphone does not confirm recovery just because zero samples are ACKed',async t=>{
  const f=setup(t);await f.capture.start();f.nodes[0].frame();await flush();f.track.muted=true;f.track.dispatchEvent(new Event('mute'));
  for(let i=0;i<24;i++){f.nodes.at(-1).frame();await flush();await f.tick(250);}
  assert.equal(f.calls.filter(c=>c.url.endsWith('/audio/start')).length,2);
  f.nodes.at(-1).frame();await flush();assert.equal(f.states.at(-1).phase,'recovering');
  f.track.muted=false;f.track.dispatchEvent(new Event('unmute'));f.nodes.at(-1).frame();await flush();
  assert.equal(f.states.at(-1).phase,'recording');assert.equal(f.states.at(-1).recovered,true);
});

test('pending microphone acquisition cannot revive a stopped capture',async t=>{
  const f=setup(t);let grant:any;
  t.mock.method(navigator.mediaDevices,'getUserMedia',()=>new Promise(resolve=>{grant=resolve;}));
  const started=f.capture.start();await f.capture.stop();grant({getTracks:()=>[f.track],getAudioTracks:()=>[f.track]});await started;
  assert.equal(f.track.readyState,'ended');assert.equal(f.calls.filter(c=>c.url.endsWith('/audio/start')).length,0);assert.equal(f.states.at(-1).phase,'idle');
});

test('hidden page does not queue a microphone request for a later click',async t=>{
  const f=setup(t),old=Object.getOwnPropertyDescriptor(globalThis,'document');
  Object.defineProperty(globalThis,'document',{value:{visibilityState:'hidden'},configurable:true});
  t.after(()=>{if(old)Object.defineProperty(globalThis,'document',old);else Reflect.deleteProperty(globalThis,'document');});
  await f.capture.start();
  assert.equal(f.acquisitions(),0);assert.equal(f.states.at(-1).phase,'idle');
  assert.match(f.states.at(-1).error,/앱 창을 앞으로/);assert.equal(f.calls.length,0);
});

test('microphone acquisition expires at 30 seconds and late grant cannot start recording',async t=>{
  const f=setup(t);let grant:any;
  t.mock.method(navigator.mediaDevices,'getUserMedia',()=>new Promise(resolve=>{grant=resolve;}));
  const started=f.capture.start();await flush();await f.tick(29999);
  assert.equal(f.states.at(-1).phase,'starting');await f.tick(1);await started;
  assert.equal(f.states.at(-1).phase,'idle');assert.match(f.states.at(-1).error,/마이크 준비 시간 초과 · 다시 시작/);
  grant({getTracks:()=>[f.track],getAudioTracks:()=>[f.track]});await flush();
  assert.equal(f.track.readyState,'ended');assert.equal(f.calls.length,0);assert.equal(f.contexts.length,0);
});

test('denial explains a refused connection without claiming macOS permission is absent',async t=>{
  const f=setup(t);t.mock.method(navigator.mediaDevices,'getUserMedia',async()=>{throw new DOMException('Permission denied','NotAllowedError');});
  await f.capture.start();assert.equal(f.states.at(-1).phase,'idle');
  assert.match(f.states.at(-1).error,/마이크 연결이 허용되지/);assert.match(f.states.at(-1).error,/계속되면.*macOS/);
  assert.equal(f.calls.length,0);
});

test('unsettled resume and stop API release resources within deadlines',async t=>{
  const f=setup(t);t.mock.method((globalThis as any).AudioContext.prototype,'resume',()=>new Promise(()=>{}));
  const started=f.capture.start();await flush();await f.tick(5000);await flush();await f.tick(1000);await started;
  assert.equal(f.states.at(-1).phase,'idle');assert.equal(f.track.readyState,'ended');assert.ok(f.contexts.every(c=>c.state==='closed'));
});


test('stop API that never replies still releases microphone socket and context',async t=>{
  const f=setup(t);await f.capture.start();f.nodes[0].frame();await flush();const fetch=globalThis.fetch;
  t.mock.method(globalThis,'fetch',(url:any,options:any)=>String(url).endsWith('/stop')?new Promise(()=>{}):fetch(url,options));
  const stopped=f.capture.stop();await flush();await f.tick(5000);await stopped;
  assert.equal(f.states.at(-1).phase,'idle');assert.equal(f.track.readyState,'ended');assert.ok(f.contexts.every(c=>c.state==='closed'));assert.match(f.states.at(-1).error,/시간 초과/);
});

test('late start response after user stop is explicitly finalized',async t=>{
  const f=setup(t);let respond:any;const fetch=globalThis.fetch;
  t.mock.method(globalThis,'fetch',(url:any,options:any)=>String(url).endsWith('/audio/start')?new Promise(resolve=>{respond=resolve;}):fetch(url,options));
  const started=f.capture.start();await flush();await f.capture.stop();respond(new Response(JSON.stringify({recording_id:'a'.repeat(32)})));await started;
  assert.ok(f.calls.some(c=>c.url==='/api/recordings/'+('a'.repeat(32))+'/stop'&&c.body.interrupted));assert.equal(f.nodes.length,0);assert.equal(f.track.readyState,'ended');
});


test('server idle timeout permits one recovery and requires fresh ACK',async t=>{
  const f=setup(t);await f.capture.start();f.nodes[0].frame();await flush();
  f.sockets[0].onmessage({data:JSON.stringify({type:'error',error:'오디오 입력 시간 초과',recoverable:true})});await flush();
  assert.equal(f.calls.filter(c=>c.url.endsWith('/audio/start')).length,2);
  assert.equal(f.states.at(-1).phase,'recovering');
  f.nodes.at(-1).frame();await flush();assert.equal(f.states.at(-1).phase,'recording');assert.equal(f.states.at(-1).recovered,true);
});


test('interruption still saves the final worklet buffer when the socket works',async t=>{
  const f=setup(t);await f.capture.start();f.nodes[0].frame();await flush();
  f.nodes[0].port.postMessage=(message:any)=>{if(message.type==='stop'){f.nodes[0].frame();queueMicrotask(()=>f.nodes[0].port.onmessage?.({data:{type:'stopped',end_frame:24000}}));}};
  await f.capture.stop(true);
  assert.equal(f.calls.find(c=>c.url.endsWith('/stop')).body.end_frame,24000);
  assert.equal(f.sockets[0].sentFrames,24000);assert.equal(f.states.at(-1).seconds,.5);
  // ACK handling emits another recording state only for a live, non-closing segment.
  assert.equal(f.states.filter(s=>s.phase==='recording').length,1);
});


test('the PCM packet that detects a stall is still saved before recovery',async t=>{
  const f=setup(t);await f.capture.start();f.nodes[0].frame();await flush();
  t.mock.method(Date,'now',()=>106000);f.nodes[0].frame();await flush();
  assert.equal(f.sockets[0].sentFrames,24000);
  assert.equal(f.calls.filter(c=>c.url.endsWith('/audio/start')).length,2);
});

test('default is post-recording and recovery inherits mode and capture ancestry',async t=>{
  const f=setup(t);await f.capture.start();f.nodes[0].frame();await flush();
  assert.equal(f.calls.find(c=>c.url.endsWith('/audio/start')).body.transcription_mode,'after_stop');
  await f.tick(6000);f.nodes.at(-1).frame();await flush();
  const starts=f.calls.filter(c=>c.url.endsWith('/audio/start'));
  assert.equal(starts[1].body.transcription_mode,'after_stop');assert.equal(starts[1].body.resume_from,'1'.padStart(32,'0'));
  assert.equal(f.calls.find(c=>c.url.endsWith('/stop')).body.defer_transcription,true);
  await f.capture.stop();assert.equal(f.calls.filter(c=>c.url.endsWith('/stop')).at(-1).body.defer_transcription,false);
});

test('explicit live mode is stored at start',async t=>{
  const f=setup(t);const capture=new RecordingCapture('session',()=>{},'realtime');await capture.start();f.nodes[0].frame();await flush();await capture.stop();
  assert.equal(f.calls.find(c=>c.url.endsWith('/audio/start')).body.transcription_mode,'realtime');
});


test('user stop releases a recovery segment whose deferred close is already in flight',async t=>{
  const f=setup(t);await f.capture.start();f.nodes[0].frame();await flush();let respond:any;const fetch=globalThis.fetch;
  t.mock.method(globalThis,'fetch',(url:any,options:any)=>String(url).endsWith('/stop')&&JSON.parse(options.body).defer_transcription?new Promise(resolve=>{respond=resolve;}):fetch(url,options));
  await f.tick(6000);assert.ok(respond);const stopped=f.capture.stop();respond(new Response(JSON.stringify({id:'job'})));await stopped;await flush();
  assert.equal(f.calls.filter(c=>c.url.endsWith('/audio/start')).length,1);
  assert.equal(f.calls.filter(c=>c.url.endsWith('/stop')).at(-1).body.defer_transcription,false);assert.equal(f.states.at(-1).phase,'idle');
});
