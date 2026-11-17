import type {NativeAudioState} from './native-audio-controller.ts';

type Fields=Record<string,unknown>;

export function createWebPlayback(){
  const players=new Map<string,HTMLAudioElement>();
  function state(audio:HTMLAudioElement,seeked=false):NativeAudioState{
    return {ready:audio.readyState>=1,duration:Number.isFinite(audio.duration)?audio.duration:0,
      currentTime:audio.currentTime,paused:audio.paused,ended:audio.ended,seeked,error:audio.error?'원음을 재생할 수 없습니다.':''};
  }
  function release(id:string){
    const audio=players.get(id);if(!audio)return {};
    const result=state(audio);players.delete(id);audio.pause();audio.removeAttribute('src');audio.load();return result;
  }
  async function playback(message:Fields){
    const {op,id}=message;
    if(typeof id!=='string'||!/^[A-Za-z0-9_-]{1,64}$/.test(id))throw new Error('재생 ID를 확인하세요.');
    if(op==='playback_seek'&&(typeof message.time!=='number'||!Number.isFinite(message.time)||message.time<0))throw new Error('재생 시각을 확인하세요.');
    if(op==='playback_volume'&&(typeof message.volume!=='number'||!Number.isFinite(message.volume)||message.volume<0||message.volume>1))throw new Error('음량을 확인하세요.');
    if(op==='playback_load'){
      if(typeof message.path!=='string'||!/^\/api\/recordings\/[a-f0-9]{32}\/audio(?:\?[^#]*)?$/.test(message.path))throw new Error('재생 경로를 확인하세요.');
      release(id);
      const audio=new Audio(message.path);players.set(id,audio);audio.preload='metadata';
      for(const event of ['loadedmetadata','timeupdate','play','pause','ended','error','seeked'])audio.addEventListener(event,()=>{
        if(players.get(id)===audio)window.dispatchEvent(new CustomEvent('solasi-playback-state',{detail:{id,...state(audio,event==='seeked')}}));
      });
      audio.load();return {};
    }
    if(op==='playback_close'||op==='playback_release')return release(id);
    const audio=players.get(id);if(!audio)throw new Error('원음 재생 연결이 종료되었습니다.');
    if(op==='playback_play')await audio.play();
    else if(op==='playback_pause')audio.pause();
    else if(op==='playback_volume')audio.volume=message.volume as number;
    else if(op==='playback_seek'){
      if(audio.readyState<1)await new Promise<void>((resolve,reject)=>{
        const done=()=>{clearTimeout(timer);audio.removeEventListener('loadedmetadata',loaded);audio.removeEventListener('error',failed);};
        const loaded=()=>{done();resolve();},failed=()=>{done();reject(new Error('원음 재생 정보를 읽을 수 없습니다.'));};
        const timer=setTimeout(()=>{done();reject(new Error('원음 재생 정보 시간 초과'));},15000);
        audio.addEventListener('loadedmetadata',loaded,{once:true});audio.addEventListener('error',failed,{once:true});
      });
      audio.currentTime=Math.min(message.time as number,Number.isFinite(audio.duration)?audio.duration:message.time as number);
    }else throw new Error('지원하지 않는 재생 명령입니다.');
    return state(audio);
  }
  return {command:playback,close(){for(const id of [...players.keys()])release(id);}};
}
