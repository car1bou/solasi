// Manual browser fixture: production Recorder/worklet/server with synthetic media and no ASR inference.
import React,{useEffect,useState} from 'react';
import {createRoot} from 'react-dom/client';
import Recorder from '../src/Recorder';
import {api} from '../src/api';
import '../src/styles.css';

const NativeContext=window.AudioContext,NativeSocket=window.WebSocket;
const contexts:AudioContext[]=[],sources:MediaStreamAudioSourceNode[]=[];
let stream:MediaStream,acquisitions=0,dropACK=false;
const log:string[]=[];
const note=(text:string)=>log.push(new Date().toISOString()+' '+text);
class ControlledContext extends NativeContext{
  constructor(){super();contexts.push(this);}
  createMediaStreamSource(media:MediaStream){const source=super.createMediaStreamSource(media);sources.push(source);return source;}
}
class ControlledSocket extends NativeSocket{
  constructor(url:string|URL,protocols?:string|string[]){super(url,protocols);dropACK=false;}
  set onmessage(fn:((this:WebSocket,event:MessageEvent)=>any)|null){super.onmessage=fn?function(event){if(dropACK&&JSON.parse(event.data).type==='ack')return;fn.call(this,event);}:null;}
  get onmessage(){return super.onmessage;}
}
window.AudioContext=ControlledContext;window.WebSocket=ControlledSocket;
Object.defineProperty(navigator.mediaDevices,'getUserMedia',{value:async()=>{
  acquisitions++;const context=new NativeContext(),osc=context.createOscillator(),gain=context.createGain(),output=context.createMediaStreamDestination();
  gain.gain.value=0;osc.connect(gain);gain.connect(output);osc.start();await context.resume();stream=output.stream;
  const track=stream.getAudioTracks()[0],stop=track.stop.bind(track);track.stop=()=>{stop();void context.close();};note('synthetic acquisition '+acquisitions);return stream;
}});
export function mount(sessionId:string){
  function Fixture(){
    const [records,setRecords]=useState<any[]>([]),[events,setEvents]=useState<string[]>([]),[count,setCount]=useState(0),[dropping,setDropping]=useState(false);
    useEffect(()=>{const timer=setInterval(()=>{void api<any[]>('/sessions/'+sessionId+'/recordings').then(setRecords);setEvents([...log]);setCount(acquisitions);setDropping(dropACK);},500);return()=>clearInterval(timer);},[]);
    return <main style={{maxWidth:1000,margin:'2rem auto',padding:24}}><h1>녹음 복구 검증</h1><p>합성 무음 · 실제 AudioWorklet/서버 WAV 저장 · ASR 대역 · 외부 전송 없음</p>
      <Recorder sessionId={sessionId}/>
      <section className="card"><h2>결함 주입</h2><div className="actions">
        <button onClick={()=>{sources.at(-1)?.disconnect();note('PCM disconnected');}}>PCM 입력 끊기</button>
        <button onClick={()=>{void contexts.at(-1)?.suspend();note('AudioContext suspended');}}>오디오 처리 중단</button>
        <button onClick={()=>{dropACK=!dropACK;note('drop ACK '+dropACK);setDropping(dropACK);}}>{dropping?'ACK 복원':'ACK 차단'}</button>
        <button onClick={()=>{stream?.getAudioTracks().forEach(t=>{t.stop();t.dispatchEvent(new Event('ended'));});note('track ended');}}>마이크 종료</button>
      </div><p>입력 획득 횟수: {count} · ACK 차단: {String(dropping)}</p></section>
      <section className="card"><h2>실제 서버 기록</h2><pre>{JSON.stringify(records.map(r=>({id:r.id,status:r.status,sample_rate:r.sample_rate,stored_frames:r.stored_frames,source_frames:r.source_frames,offset_ms:r.offset_ms,gaps:r.gaps,error:r.error})),null,2)}</pre></section>
      <section className="card"><h2>결함 주입 이력</h2><pre>{events.join('\n')}</pre></section></main>;
  }
  createRoot(document.getElementById('root')!).render(<Fixture/>);
}
