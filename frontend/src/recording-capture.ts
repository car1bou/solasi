import {api,sessionToken} from './api.ts';
import {encodeFrame,withinBuffer} from './audio-wire.ts';

export type TranscriptionMode='after_stop'|'realtime';
export type RecordingState={phase:'idle'|'starting'|'recording'|'recovering'|'stopping';seconds:number;pending:number;error:string;recovered:boolean};
type Segment={id:string;rate:number;end:number;lastPCM:number;lastTick:number;mutedAt:number|null;ending:boolean;acceptFrames:boolean;confirmed:boolean;deferred:boolean;packets:Map<number,{frames:number;sent:number}>;context?:AudioContext;node?:AudioWorkletNode;microphone?:MediaStreamAudioSourceNode;mute?:GainNode;socket?:WebSocket;flush?:()=>void;closing?:Promise<void>};

async function limited<T>(operation:Promise<T>,ms:number,message:string):Promise<T>{
  let timer:ReturnType<typeof setTimeout>;
  try{return await Promise.race([operation,new Promise<never>((_,reject)=>{timer=setTimeout(()=>reject(new Error(message)),ms);})]);}
  finally{clearTimeout(timer!);}
}

export class RecordingCapture{
  private sessionId:string;
  private transcriptionMode:TranscriptionMode;
  private onState:(state:RecordingState)=>void;
  private state:RecordingState={phase:'idle',seconds:0,pending:0,error:'',recovered:false};
  private stream:MediaStream|null=null;
  private segment:Segment|null=null;
  private finished=false;
  private recovering=false;
  private recovered=false;
  private recordedSeconds=0;
  private stopTask:Promise<void>|null=null;
  private timer:ReturnType<typeof setInterval>|null=null;
  private trackEnded=()=>{void this.fail('마이크 입력이 종료됐습니다',false);};
  private trackChanged=()=>{this.checkHealth();};
  constructor(sessionId:string,onState:(state:RecordingState)=>void,transcriptionMode:TranscriptionMode='after_stop'){this.sessionId=sessionId;this.onState=onState;this.transcriptionMode=transcriptionMode;}
  private update(change:Partial<RecordingState>){this.state={...this.state,...change};this.onState({...this.state});}
  private current(s:Segment){return this.segment===s&&!this.finished&&!s.ending;}
  private async request<T>(path:string,body:object):Promise<T>{
    const controller=new AbortController();
    try{return await limited(api<T>(path,{method:'POST',body:JSON.stringify(body),signal:controller.signal}),5000,'녹음 저장·연결 시간 초과');}
    finally{controller.abort();}
  }
  async start(){
    this.update({phase:'starting'});
    try{
      // WebKit can defer a hidden page's request until a later, unrelated click.
      if(typeof document!=='undefined'&&document.visibilityState==='hidden')throw new Error('앱 창을 앞으로 연 뒤 녹음을 다시 시작하세요.');
      const acquisition=navigator.mediaDevices.getUserMedia({audio:{channelCount:1},video:false}).then(stream=>{
        if(this.finished)stream.getTracks().forEach(t=>t.stop());
        return stream;
      });
      const stream=await limited(acquisition,30000,'마이크 준비 시간 초과 · 다시 시작');
      if(this.finished){stream.getTracks().forEach(t=>t.stop());return;}
      this.stream=stream;
      stream.getAudioTracks().forEach(track=>{track.addEventListener('ended',this.trackEnded);track.addEventListener('mute',this.trackChanged);track.addEventListener('unmute',this.trackChanged);});
      await this.openSegment();
      if(!this.finished)this.timer=setInterval(()=>this.checkHealth(),1000);
    }catch(e){if(!this.finished)await this.terminate((e as Error).name==='NotAllowedError'?'마이크 연결이 허용되지 않았습니다. 앱 창을 앞으로 연 뒤 다시 시도하고, 계속되면 macOS 마이크 접근 권한을 확인하세요.':(e as Error).message);}
  }
  private async openSegment(){
    if(this.finished)return;
    const previous=this.segment?.id,context=new AudioContext(),s:Segment={id:'',rate:context.sampleRate,end:0,lastPCM:Date.now(),lastTick:Date.now(),mutedAt:null,ending:false,acceptFrames:true,confirmed:false,deferred:false,packets:new Map(),context};
    this.segment=s;
    try{
      s.id=(await this.request<{recording_id:string}>('/sessions/'+this.sessionId+'/audio/start',{sample_rate:s.rate,transcription_mode:this.transcriptionMode,resume_from:previous||undefined})).recording_id;
      if(!this.current(s)){await this.request('/recordings/'+s.id+'/stop',{interrupted:true,reason:'연결 중 녹음 취소'});return;}
      const socket=s.socket=new WebSocket('ws://'+location.host+'/api/sessions/'+this.sessionId+'/audio');socket.binaryType='arraybuffer';
      await limited(new Promise<void>((resolve,reject)=>{
        socket.onopen=()=>{if(this.current(s))socket.send(JSON.stringify({recording_id:s.id,sample_rate:s.rate,channels:1,format:'pcm_s16le',csrf_token:sessionToken()}));};
        socket.onmessage=event=>{try{const data=JSON.parse(event.data);if(data.type==='ready')resolve();else reject(new Error(data.error||'녹음 연결 실패'));}catch{reject(new Error('녹음 연결 응답 오류'));}};
        socket.onclose=()=>reject(new Error('녹음 연결 끊김'));socket.onerror=()=>reject(new Error('녹음 연결 실패'));
      }),5000,'녹음 연결 시간 초과');
      if(!this.current(s))return;
      await limited(context.audioWorklet.addModule(new URL('./pcm-worklet.js',import.meta.url).href),5000,'오디오 처리기 준비 시간 초과');
      if(!this.current(s))return;
      const node=s.node=new AudioWorkletNode(context,'pcm-capture'),microphone=s.microphone=context.createMediaStreamSource(this.stream!),mute=s.mute=context.createGain();mute.gain.value=0;
      microphone.connect(node);node.connect(mute);mute.connect(context.destination);
      socket.onmessage=event=>{
        try{
          const data=JSON.parse(event.data);
          if(data.type==='error'){if(this.current(s))void this.fail(data.error||'원음 저장 실패',data.recoverable===true);return;}
          const pending=s.packets.get(data.seq);
          if(data.type==='ack'&&pending&&data.frame_count===pending.frames){
            s.packets.delete(data.seq);node.port.postMessage({type:'ack',frames:pending.frames});
            if(this.current(s)&&context.state==='running'&&this.stream?.getAudioTracks().every(t=>t.readyState==='live'&&!t.muted)){s.confirmed=true;this.update({phase:'recording',pending:this.pending(s)/s.rate,recovered:this.recovered,error:''});}
          }
        }catch{if(this.current(s))void this.fail('녹음 응답 오류',false);}
      };
      socket.onclose=event=>{if(this.current(s))void this.fail('녹음 연결이 끊겼습니다',event.code!==1008);};
      socket.onerror=()=>{if(this.current(s))void this.fail('녹음 전송 실패',true);};
      node.port.onmessage=event=>{
        const data=event.data;
        if(data.type==='stopped'){s.acceptFrames=false;if(Number.isSafeInteger(data.end_frame)&&data.end_frame>=s.end)s.end=data.end_frame;s.flush?.();return;}
        if(data.type==='overflow'){if(this.current(s))void this.fail('녹음 전송 지연',true);return;}
        if(data.type!=='frame'||!s.acceptFrames||this.segment!==s)return;
        if(!s.ending)this.checkHealth();
        s.end=data.first_frame+data.samples.length;s.lastPCM=Date.now();
        if(!withinBuffer(this.pending(s),data.samples.length,s.rate)||socket.readyState!==WebSocket.OPEN){if(this.current(s))void this.fail('녹음 전송 지연',true);return;}
        s.packets.set(data.seq,{frames:data.samples.length,sent:Date.now()});
        try{socket.send(encodeFrame(data.seq,data.first_frame,data.samples));}
        catch{if(this.current(s))void this.fail('녹음 전송 실패',true);}
        if(!s.ending&&!this.finished)this.update({seconds:this.recordedSeconds+s.end/s.rate,pending:this.pending(s)/s.rate});
      };
      node.onprocessorerror=()=>{if(this.current(s))void this.fail('오디오 처리기가 중단됐습니다',true);};
      await limited(context.resume(),5000,'오디오 시작 시간 초과');
      if(!this.current(s))return;
      context.onstatechange=()=>{if(this.current(s)&&context.state!=='running')void this.fail('오디오 처리가 일시 중단됐습니다',true);};
      s.lastPCM=s.lastTick=Date.now();
    }catch(e){await this.closeSegment(s,true,(e as Error).message);throw e;}
  }
  private pending(s:Segment){let count=0;for(const p of s.packets.values())count+=p.frames;return count;}
  private checkHealth():boolean{
    const s=this.segment;if(!s||!this.current(s)||!s.node)return false;
    const now=Date.now(),tracks=this.stream?.getAudioTracks()||[];
    let reason='';
    if(!tracks.length||tracks.some(t=>t.readyState==='ended')){void this.fail('마이크 입력이 종료됐습니다',false);return true;}
    if(tracks.some(t=>t.muted))s.mutedAt??=now;else s.mutedAt=null;
    if(now-s.lastTick>10000||now<s.lastTick)reason='절전 또는 오디오 수집 중단 감지';
    else if(s.mutedAt!==null&&now-s.mutedAt>=5000)reason='마이크 입력이 일시 중단됐습니다';
    else if(now-s.lastPCM>=5000)reason='오디오 입력이 도착하지 않습니다';
    else if([...s.packets.values()].some(p=>now-p.sent>=5000))reason='원음 저장 확인이 지연됩니다';
    s.lastTick=now;
    if(reason){void this.fail(reason,true);return true;}
    return false;
  }
  private async fail(reason:string,recoverable:boolean){
    if(this.finished||this.recovering)return;
    this.recovering=true;
    const canRecover=recoverable&&!this.recovered&&this.stream?.getAudioTracks().some(t=>t.readyState==='live');
    if(!canRecover){this.recovering=false;await this.terminate(reason);return;}
    this.recovered=true;this.update({phase:'recovering',error:reason+' · 새 녹음 구간으로 복구 중'});
    try{
      const s=this.segment;if(s){await this.closeSegment(s,true,reason);this.recordedSeconds+=s.end/s.rate;}
      if(this.finished)return;
      if(!this.stream?.getAudioTracks().some(t=>t.readyState==='live'))throw new Error('마이크 입력이 종료됐습니다');
      await this.openSegment();
    }catch(e){if(!this.finished)await this.terminate('자동 복구 실패 · '+(e as Error).message);}
    finally{this.recovering=false;}
  }
  private closeSegment(s:Segment,interrupted:boolean,reason=''):Promise<void>{
    if(s.closing)return s.closing;
    s.ending=true;s.deferred=this.transcriptionMode==='after_stop'&&this.recovering&&!this.finished;
    s.closing=(async()=>{
      try{
        if(s.node){
          const flushed=new Promise<void>(resolve=>{s.flush=resolve;});s.node.port.postMessage({type:'stop'});
          try{await limited(flushed,1000,'마지막 오디오 확인 시간 초과');}catch(e){interrupted=true;reason||=(e as Error).message;this.update({error:reason});}
        }
        if(this.segment===s)this.update({seconds:this.recordedSeconds+s.end/s.rate});
        if(this.finished)this.stream?.getTracks().forEach(t=>t.stop());
        const deadline=Date.now()+3000;
        while(s.packets.size&&s.socket?.readyState===WebSocket.OPEN&&Date.now()<deadline)await new Promise(resolve=>setTimeout(resolve,25));
        interrupted||=s.packets.size>0;
        if(s.id)await this.request('/recordings/'+s.id+'/stop',{end_frame:s.end,interrupted,defer_transcription:s.deferred,reason:interrupted?(reason||'원음 저장 확인 중단').slice(0,300):undefined});
      }catch(e){this.update({error:(e as Error).message+' · 수신된 원음의 저장 상태를 확인하세요'});}
      finally{
        if(s.context)s.context.onstatechange=null;
        if(s.node){s.node.onprocessorerror=null;s.node.port.onmessage=null;}
        if(s.socket){s.socket.onopen=s.socket.onmessage=s.socket.onclose=s.socket.onerror=null;s.socket.close();}
        s.microphone?.disconnect();s.node?.disconnect();s.mute?.disconnect();
        if(s.context)await limited(s.context.close(),1000,'오디오 종료 시간 초과').catch(()=>{});
      }
    })();
    return s.closing;
  }
  private async terminate(reason:string){this.update({error:reason+' · 녹음 중단'});await this.stop(true);}
  stop(interrupted=false):Promise<void>{
    if(this.stopTask)return this.stopTask;
    this.finished=true;if(this.timer)clearInterval(this.timer);
    this.update({phase:'stopping'});
    this.stream?.getTracks().forEach(t=>{t.removeEventListener('ended',this.trackEnded);t.removeEventListener('mute',this.trackChanged);t.removeEventListener('unmute',this.trackChanged);});
    this.stopTask=(async()=>{if(this.segment){await this.closeSegment(this.segment,interrupted,this.state.error);if(this.segment.id&&this.segment.deferred){try{await this.request('/recordings/'+this.segment.id+'/stop',{end_frame:this.segment.end,interrupted:true,defer_transcription:false,reason:this.state.error||undefined});this.segment.deferred=false;}catch(e){this.update({error:(e as Error).message+' · 저장한 원음의 전사를 재시도하세요'});}}}this.stream?.getTracks().forEach(t=>t.stop());this.update({phase:'idle',pending:0});})();
    return this.stopTask;
  }
}
