import React,{useEffect,useRef,useState} from 'react';
import {RecordingCapture} from './recording-capture';
import type {RecordingState,TranscriptionMode} from './recording-capture';

export default function Recorder({sessionId,onActiveChange}:{sessionId:string;onActiveChange?:(active:boolean)=>void}){
  const [state,setState]=useState<RecordingState>({phase:'idle',seconds:0,pending:0,error:'',recovered:false});
  const [mode,setMode]=useState<TranscriptionMode>('after_stop');
  const active=useRef<RecordingCapture|null>(null),mounted=useRef(true);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;void active.current?.stop(true);active.current=null;};},[sessionId]);
  function start(){
    const capture=new RecordingCapture(sessionId,next=>{if(mounted.current&&active.current===capture){setState(next);if(next.phase==='idle'){active.current=null;onActiveChange?.(false);}}},mode);
    active.current=capture;onActiveChange?.(true);void capture.start();
  }
  const {phase,seconds,pending,error,recovered}=state;
  return <section className="card recorder">
    <div><h2>녹음</h2><span role="status">{{idle:error?'중단됨':'대기',starting:'연결 중',recording:recovered?'자동 복구됨 · 녹음 중':'녹음 중',recovering:'자동 복구 중',stopping:'저장 중'}[phase]}</span>
      <span className="muted"> {Math.floor(seconds/60)}:{String(Math.floor(seconds%60)).padStart(2,'0')}{pending>1?' · 전송 대기 '+pending.toFixed(1)+'초':''}</span>
    </div>
    <label>전사 방식<select value={mode} disabled={phase!=='idle'} onChange={e=>setMode(e.target.value as TranscriptionMode)}><option value="after_stop">녹음 종료 후 전사</option><option value="realtime">실시간 전사</option></select></label>
    {phase==='idle'?<button className="primary" onClick={start}>{error?'녹음 다시 시작':'녹음 시작'}</button>:<button disabled={phase==='stopping'} onClick={()=>void active.current?.stop()}>종료</button>}
    {error&&<p role="alert">{error}</p>}
  </section>;
}
