// Actual speech playback -> production capture/worklet -> actual native ASR and local AI jobs.
import React,{useState,useEffect} from 'react';
import {createRoot} from 'react-dom/client';
import {RecordingCapture} from '../src/recording-capture';
import type {RecordingState} from '../src/recording-capture';
import {api} from '../src/api';
import '../src/styles.css';

const NativeContext=window.AudioContext;
let media:MediaStream,bufferSource:AudioBufferSourceNode,sourceContext:AudioContext,mediaContext:AudioContext,fixtureBuffer:AudioBuffer,clockStart=0,capture:RecordingCapture|null=null;
const audioSeconds=()=>Math.max(0,sourceContext.currentTime-clockStart);
Object.defineProperty(navigator.mediaDevices,'getUserMedia',{value:async()=>media});
const samples:any[]=[],runs:any[]=[];let activeRun:any;
const NativeSocket=window.WebSocket;
class MeasuredSocket extends NativeSocket{
  sent=new Map<number,number>();recording='';
  constructor(url:string|URL,protocols?:string|string[]){super(url,protocols);this.addEventListener('close',event=>activeRun?.socket_events.push({at:Date.now(),type:'close',code:event.code,clean:event.wasClean,reason_length:event.reason.length,pending:this.sent.size}));this.addEventListener('error',()=>activeRun?.socket_events.push({at:Date.now(),type:'error',state:this.readyState,pending:this.sent.size}));}
  send(data:Parameters<WebSocket['send']>[0]){
    if(typeof data==='string')this.recording=JSON.parse(data).recording_id;
    else if(data instanceof ArrayBuffer)this.sent.set(Number(new DataView(data).getBigUint64(0,true)),performance.now());
    super.send(data);
  }
  set onmessage(fn:((this:WebSocket,event:MessageEvent)=>any)|null){super.onmessage=fn?(event)=>{const message=JSON.parse(event.data);if(message.type==='ack'&&this.sent.has(message.seq)){activeRun?.acks.push({recording_id:this.recording,seq:message.seq,frames:message.frame_count,ms:performance.now()-this.sent.get(message.seq)!});this.sent.delete(message.seq);}fn.call(this,event);}:null;}
  get onmessage(){return super.onmessage;}
}
window.WebSocket=MeasuredSocket;
export function mount(sid:string,duration:number,both=true,inputType='사람 읽기 음성',model='qwen3.5:4b',mode:'realtime'|'after_stop'='realtime',direct=false){
  if(direct)window.AudioContext=class extends NativeContext{
    createMediaStreamSource(stream:MediaStream):MediaStreamAudioSourceNode{
      if(stream!==media)return super.createMediaStreamSource(stream);
      if(activeRun?.play_started)throw new Error('Direct fixture cannot resume source playback after recovery');
      sourceContext=this;bufferSource=this.createBufferSource();bufferSource.buffer=fixtureBuffer;
      return bufferSource as unknown as MediaStreamAudioSourceNode;
    }
  };
  function Fixture(){
    const [state,setState]=useState<RecordingState|null>(null),[status,setStatus]=useState('준비 전'),[elapsed,setElapsed]=useState(0),[error,setError]=useState(''),[running,setRunning]=useState(false),[ready,setReady]=useState(false),[jobs,setJobs]=useState<any[]>([]);
    const request=(path:string,body:object)=>api<any>(path,{method:'POST',body:JSON.stringify(body)});
    async function ask(kind='answer'){return request('/ai/jobs',{session_id:sid,kind,prompt:kind==='summary'?'확정된 전사 전체를 근거로 주어·가정·조건·예시를 보존하고 앞·중간·후반의 핵심을 요약하세요.':'프로세스와 스레드의 차이와 동기화가 필요한 이유를 근거로 세 문장으로 설명하세요.',scope:{session_id:sid,mode:'current'},web:false});}
    async function prepare(){try{setStatus('로컬 엔진 준비 중');await request('/local/connect',{mode:'managed'});await api('/settings',{method:'PUT',body:JSON.stringify({provider:'ollama',model,context_limit:8192})});if(mode==='realtime'){const warm=await ask();setStatus('생성 예열 중');let job=warm;while(['queued','running'].includes(job.status)){await new Promise(r=>setTimeout(r,500));job=await api('/jobs/'+job.id);}if(job.status!=='done')throw new Error(job.error||'예열 실패');}setReady(true);setStatus('준비됨');}catch(e){setError((e as Error).message);}}
    async function start(concurrent:boolean){
      try{
        setRunning(true);setError('');mediaContext=new NativeContext();sourceContext=mediaContext;const destination=mediaContext.createMediaStreamDestination();media=destination.stream;
        fixtureBuffer=await mediaContext.decodeAudioData(await (await fetch('/api/fixture/audio')).arrayBuffer());
        if(!direct){bufferSource=mediaContext.createBufferSource();bufferSource.buffer=fixtureBuffer;bufferSource.connect(destination);await mediaContext.resume();}
        // Capture owns its context so segment recovery cannot close the speech playback graph.
        const run:any={mode:mode==='after_stop'?'after_stop':concurrent?'concurrent':'asr_only',started:Date.now(),generations:[],acks:[],socket_events:[],lifecycle_events:[],capture_events:[],capture_route:direct?'AudioBufferSource in production capture AudioContext -> production worklet; getUserMedia stream substituted; no physical microphone/bridge/recovery claim':'AudioBufferSource -> MediaStreamDestination -> independent production capture AudioContext'};runs.push(run);activeRun=run;
        capture=new RecordingCapture(sid,s=>{setState(s);if(!run.last_state||s.phase!==run.last_state.phase||s.error!==run.last_state.error||s.recovered!==run.last_state.recovered)run.capture_events.push({at:Date.now(),audio_seconds:audioSeconds(),...s});run.last_state=s;if(run.play_started&&s.phase==='idle'&&s.error&&!run.stopped){run.recording_error=s.error;void finish();}},mode);await capture.start();if(direct&&sourceContext===mediaContext)throw new Error('Direct fixture did not enter the production capture context');sourceContext.addEventListener('statechange',()=>run.lifecycle_events.push({at:Date.now(),type:'audio_context',state:sourceContext.state}));
        bufferSource.onended=()=>void finish();clockStart=sourceContext.currentTime;bufferSource.start();run.play_started=Date.now();run.render_start=clockStart;setStatus(mode==='after_stop'?'원음 저장 중 · 전사는 종료 후 실행':concurrent?'전사 + 생성 진행':'전사 단독 진행');
        let lastAsk=-35;const timer=setInterval(()=>{
          setElapsed(audioSeconds());
          if(mode==='realtime'&&concurrent&&audioSeconds()>=180&&!run.summary_submitted){run.summary_submitted=Date.now();void ask('summary').then(j=>{run.summary_job_id=j.id;run.generations.push({id:j.id,kind:'summary',submitted:Date.now(),audio_seconds:audioSeconds()});}).catch(e=>{run.summary_error=e.message;});}
          if(mode==='realtime'&&concurrent&&audioSeconds()>=25&&audioSeconds()-lastAsk>=60){lastAsk=audioSeconds();void ask().then(j=>{run.generations.push({id:j.id,submitted:Date.now(),audio_seconds:audioSeconds()});}).catch(e=>{run.generation_error=e.message;});}
        },500);
        async function finish(){
          if(run.stopped)return;run.stopped=Date.now();clearInterval(timer);bufferSource.stop();await capture?.stop();capture=null;media.getTracks().forEach(t=>t.stop());if(sourceContext.state!=='closed')await sourceContext.close();if(mediaContext.state!=='closed')await mediaContext.close();setStatus('확정 전사·생성 완료 대기');
          let active=true;const deadline=Date.now()+600000;
          while(active&&Date.now()<deadline){const current=await api<any[]>('/sessions/'+sid+'/jobs');setJobs(current);active=current.some(j=>['queued','running'].includes(j.status));await new Promise(r=>setTimeout(r,1000));}
          if(!active&&mode==='after_stop'){const j=await ask();run.generations.push({id:j.id,submitted:Date.now(),audio_seconds:duration});let job=j;while(['queued','running'].includes(job.status)&&Date.now()<deadline){await new Promise(r=>setTimeout(r,500));job=await api('/jobs/'+job.id);}active=['queued','running'].includes(job.status);}
          if(!active){const final=await ask('summary');run.final_summary_job_id=final.id;run.generations.push({id:final.id,kind:'final_summary',submitted:Date.now(),audio_seconds:duration});let job=final;while(['queued','running'].includes(job.status)&&Date.now()<deadline){await new Promise(r=>setTimeout(r,500));job=await api('/jobs/'+final.id);}active=['queued','running'].includes(job.status);}
          run.done=Date.now();run.jobs=await api('/sessions/'+sid+'/jobs');run.events=await api('/sessions/'+sid+'/events');setJobs(run.jobs);const complete=!run.recording_error&&!active&&!run.summary_error&&run.last_state.seconds>=duration-.1&&run.jobs.every((j:any)=>j.status==='done'||j.kind==='asr_review'&&['cancelled','failed','interrupted'].includes(j.status));await request('/fixture/telemetry',{runs,samples,ready:complete&&runs.length===(mode==='realtime'&&both?2:1)&&runs.every(r=>!r.recording_error)});setStatus(run.recording_error?'녹음 중단 · 시험 종료':active?'완료 대기 시간 초과':complete?'시험 완료':'원음 길이·작업 검증 불완전');setRunning(false);if(mode==='realtime'&&both&&concurrent&&complete)void start(false);
        }
      }catch(e){setError((e as Error).message);setRunning(false);await capture?.stop(true);capture=null;media?.getTracks().forEach(t=>t.stop());if(mediaContext&&mediaContext.state!=='closed')await mediaContext.close();}
    }
    useEffect(()=>{const record=(event:Event)=>activeRun?.lifecycle_events.push({at:Date.now(),type:event.type,visibility:document.visibilityState});window.addEventListener('pagehide',record);document.addEventListener('visibilitychange',record);return()=>{window.removeEventListener('pagehide',record);document.removeEventListener('visibilitychange',record);};},[]);
    useEffect(()=>{let busy=false;const timer=setInterval(async()=>{if(busy)return;busy=true;try{const event=await api<any>('/sessions/'+sid+'/events');const current=await api<any[]>('/sessions/'+sid+'/jobs');setJobs(current);if(capture){samples.push({at:Date.now(),audio_seconds:audioSeconds(),recordings:event.recordings.map((r:any)=>({id:r.id,stored_frames:r.stored_frames,source_frames:r.source_frames,gaps:r.gaps,status:r.status,transcription:r.transcription})),final_end_ms:Math.max(0,...event.transcripts.filter((t:any)=>t.final).map((t:any)=>t.end_ms)),jobs:current.filter(j=>['queued','running'].includes(j.status)).map(j=>({id:j.id,status:j.status,result:j.result}))});if(samples.length%5===0)await request('/fixture/telemetry',{runs,samples});}}catch(e){setError((e as Error).message);}finally{busy=false;}},1000);return()=>clearInterval(timer);},[]);
    return <main style={{maxWidth:1000,margin:'2rem auto',padding:24}}><h1>{mode==='after_stop'?'긴 사람 음성 종료 후 처리 검증':'긴 사람 음성 동시 실행 검증'}</h1><p>{model} · {inputType} · {duration.toFixed(2)}초 · {direct?'동일 오디오 컨텍스트의 시험 음원':'브라우저 미디어 스트림'} · 실제 강의 아님 · {mode==='after_stop'?'녹음 후 ASR → 생성':'실제 ASR/로컬 동시 생성'} · 스피커 출력 없음</p>
      <section className="card"><button disabled={running||ready} onClick={()=>void prepare()}>{mode==='after_stop'?'로컬 엔진 연결':'엔진·생성 예열'}</button><button disabled={!ready||running} onClick={()=>void start(true)}>{mode==='after_stop'?'원음 녹음 → 종료 후 전사 시작':both?'동시→단독 연속 검증 시작':'전사·생성 검증 시작'}</button><p role="status">{status} · 음원 {elapsed.toFixed(1)}초</p>{error&&<p role="alert">{error}</p>}<pre>{JSON.stringify(state,null,2)}</pre></section>
      <section className="card"><h2>실제 작업</h2>{jobs.filter(j=>j.status==='done'&&j.request?.request?.kind==='summary'&&j.result?.id).map(j=><p key={j.id}><a href={'/api/artifacts/'+j.result.id+'/export'} download>실제 요약 Markdown 내보내기</a></p>)}<pre>{JSON.stringify(jobs.map(j=>({id:j.id,kind:j.kind,status:j.status,result:j.result,error:j.error})),null,2)}</pre></section></main>;
  }
  createRoot(document.getElementById('root')!).render(<Fixture/>);
}
