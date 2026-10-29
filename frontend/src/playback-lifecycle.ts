export type PlaybackHandle=Pick<HTMLAudioElement,'currentTime'|'duration'|'paused'|'play'|'pause'>;
export function createPlaybackLifecycle(pause:()=>void,visible:()=>boolean){
  let interrupted=false,pendingMetadata:(()=>void)|null=null;
  const stop=()=>{interrupted=true;pause();};
  const active=()=>!interrupted&&visible();
  return {
    active,
    // Retain the initial range seek until visible interaction, without reviving autoplay.
    metadata(handle:PlaybackHandle,callback?: (event:{currentTarget:PlaybackHandle})=>void){const loaded=()=>callback?.({currentTarget:{
      get currentTime(){return handle.currentTime;},set currentTime(time:number){handle.currentTime=time;},
      get duration(){return handle.duration;},get paused(){return handle.paused;},
      play:()=>active()?handle.play():Promise.resolve(),pause:()=>handle.pause(),
    }});if(active())loaded();else pendingMetadata=loaded;},
    interact:()=>{if(!visible())return;const loaded=pendingMetadata;pendingMetadata=null;interrupted=true;try{loaded?.();}finally{interrupted=false;}},
    listen(target:EventTarget){
      interrupted=false;
      target.addEventListener('solasi-navigated',stop);
      return()=>{target.removeEventListener('solasi-navigated',stop);stop();};
    },
  };
}
