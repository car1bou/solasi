import React,{forwardRef,useEffect,useImperativeHandle,useMemo,useRef,useState} from 'react';
import {nativeApp,nativeCommand} from './api';
import {NativeAudioController,type NativeAudioState} from './native-audio-controller';

export type PlaybackHandle=Pick<HTMLAudioElement,'currentTime'|'duration'|'paused'|'play'|'pause'>;
type Event={currentTarget:PlaybackHandle};
type Props={src:string;controls?:boolean;preload?:'none'|'metadata'|'auto';'aria-label'?:string;onLoadedMetadata?:(event:Event)=>void;onPlay?:(event:Event)=>void;onTimeUpdate?:(event:Event)=>void;onSeeking?:(event:Event)=>void;onEnded?:(event:Event)=>void;onError?:()=>void};
const NativeAudio=forwardRef<PlaybackHandle,Props>(function NativeAudio(props,ref){
  const latest=useRef(props);latest.current=props;
  const [state,setState]=useState<NativeAudioState>({ready:false,duration:0,currentTime:0,paused:true,ended:false,seeked:false,error:''});
  const [volume,setVolume]=useState(1);
  const controller=useMemo(()=>new NativeAudioController(props.src,nativeCommand,(next,previous,event)=>{
    setState(next);if(!event)return;
    if(next.error){latest.current.onError?.();return;}
    const callback={currentTarget:handle};
    if(next.ready&&!previous.ready)latest.current.onLoadedMetadata?.(callback);
    if(!next.paused&&previous.paused)latest.current.onPlay?.(callback);
    if(next.seeked)latest.current.onSeeking?.(callback);
    latest.current.onTimeUpdate?.(callback);
    if(next.ended)latest.current.onEnded?.(callback);
  }),[props.src]);
  const fail=(error:unknown)=>controller.fail(error);
  const handle=useMemo<PlaybackHandle>(()=>({
    get currentTime(){return controller.state.currentTime;},
    set currentTime(time:number){void controller.seek(time).catch(fail);},
    get duration(){return controller.state.duration;},get paused(){return controller.state.paused;},
    play(){return controller.play();},
    pause(){void controller.pause().catch(fail);}
  }),[controller]);
  useImperativeHandle(ref,()=>handle,[handle]);
  useEffect(()=>{
    const update=(event:globalThis.Event)=>{
      const next=(event as CustomEvent<NativeAudioState&{id:string}>).detail;if(next)controller.receive(next);
    };
    window.addEventListener('solasi-playback-state',update);
    if(props.preload!=='none')void controller.preload().catch(fail);
    return()=>{window.removeEventListener('solasi-playback-state',update);void controller.dispose().catch(()=>{});};
  },[controller]);
  function seek(time:number){handle.currentTime=time;latest.current.onSeeking?.({currentTarget:handle});}
  return <div className="native-audio" role="group" aria-label={props['aria-label']||'원음 재생'}><button type="button" aria-label={state.paused?'원음 재생':'원음 일시 정지'} onClick={()=>state.paused?void handle.play().catch(fail):handle.pause()}>{state.paused?'재생':'일시 정지'}</button><input type="range" aria-label="원음 재생 위치" min={0} max={state.duration||1} step={.1} value={Math.min(state.currentTime,state.duration||1)} disabled={!state.ready} onChange={event=>seek(Number(event.target.value))}/><span>{Math.floor(state.currentTime/60)}:{String(Math.floor(state.currentTime%60)).padStart(2,'0')}</span><input type="range" aria-label="원음 음량" min={0} max={1} step={.05} value={volume} onChange={event=>{const value=Number(event.target.value);setVolume(value);void controller.setVolume(value).catch(fail);}}/>{state.error&&<p role="alert">{state.error}</p>}</div>;
});

export default forwardRef<PlaybackHandle,Props>(function PlaybackAudio(props,ref){
  if(nativeApp())return <NativeAudio key={props.src} {...props} ref={ref}/>;
  return <audio {...props} ref={ref as React.Ref<HTMLAudioElement>}/>;
});
