import React,{forwardRef,useEffect,useImperativeHandle,useMemo,useRef,useState} from 'react';
import {nativeApp,nativeCommand} from './api';
import {NativeAudioController,type NativeAudioState} from './native-audio-controller';
import Icon from './Icon';
import {createPlaybackLifecycle,type PlaybackHandle} from './playback-lifecycle';

export type {PlaybackHandle} from './playback-lifecycle';
type Event={currentTarget:PlaybackHandle};
type Props={src:string;controls?:boolean;preload?:'none'|'metadata'|'auto';'aria-label'?:string;onLoadedMetadata?:(event:Event)=>void;onPlay?:(event:Event)=>void;onTimeUpdate?:(event:Event)=>void;onSeeking?:(event:Event)=>void;onEnded?:(event:Event)=>void;onError?:()=>void};
const NativeAudio=forwardRef<PlaybackHandle,Props&{elementRef:(element:HTMLDivElement|null)=>void;onInteraction:()=>void}>(function NativeAudio(props,ref){
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
  return <div ref={props.elementRef} onPointerDownCapture={props.onInteraction} onKeyDownCapture={props.onInteraction} onClickCapture={props.onInteraction} className="native-audio" role="group" aria-label={props['aria-label']||'원음 재생'}><button type="button" className="icon-button" aria-label={state.paused?'원음 재생':'원음 일시 정지'} title={state.paused?'원음 재생':'원음 일시 정지'} onClick={()=>state.paused?void handle.play().catch(fail):handle.pause()}><Icon name={state.paused?'play':'pause'}/></button><input type="range" aria-label="원음 재생 위치" min={0} max={state.duration||1} step={.1} value={Math.min(state.currentTime,state.duration||1)} disabled={!state.ready} onChange={event=>seek(Number(event.target.value))}/><span>{Math.floor(state.currentTime/60)}:{String(Math.floor(state.currentTime%60)).padStart(2,'0')}</span><input type="range" aria-label="원음 음량" min={0} max={1} step={.05} value={volume} onChange={event=>{const value=Number(event.target.value);setVolume(value);void controller.setVolume(value).catch(fail);}}/>{state.error&&<p role="alert">{state.error}</p>}</div>;
});

export default forwardRef<PlaybackHandle,Props>(function PlaybackAudio(props,ref){
  const audio=useRef<PlaybackHandle|null>(null),element=useRef<HTMLElement|null>(null);
  const lifecycle=useMemo(()=>createPlaybackLifecycle(()=>audio.current?.pause(),()=>!!element.current&&!element.current.closest('[hidden],[inert]')),[]);
  useImperativeHandle(ref,()=>audio.current!,[props.src]);
  useEffect(()=>lifecycle.listen(window),[lifecycle]);
  const guard=(callback?:Props['onLoadedMetadata'])=>(event:Event)=>{if(lifecycle.active())callback?.(event);};
  const guarded:Props={...props,
    onLoadedMetadata:event=>lifecycle.metadata(event.currentTarget,props.onLoadedMetadata),onTimeUpdate:guard(props.onTimeUpdate),
    onSeeking:guard(props.onSeeking),onEnded:guard(props.onEnded),
    onPlay:event=>{if(lifecycle.active())props.onPlay?.(event);else event.currentTarget.pause();},
    onError:()=>{if(lifecycle.active())props.onError?.();},
  };
  if(nativeApp())return <NativeAudio key={props.src} {...guarded} ref={audio} elementRef={node=>{element.current=node;}} onInteraction={lifecycle.interact}/>;
  return <audio {...guarded} ref={node=>{audio.current=node;element.current=node;}} onPointerDownCapture={lifecycle.interact} onKeyDownCapture={lifecycle.interact} onClickCapture={lifecycle.interact}/>;
});
