import {nativeApp,nativeCommand} from './api.ts';

export type NativeClip={url:string;start:number;end:number};

export function subscribeNativeAudio(open:(clip:NativeClip)=>void,failed:(message:string)=>void){
  let active=true;
  const receive=(event:Event)=>{
    const clip=(event as CustomEvent<NativeClip>).detail;
    if(!clip||!/^\/api\/recordings\/[a-f0-9]{32}\/audio$/.test(clip.url)||!Number.isFinite(clip.start)||!Number.isFinite(clip.end)||clip.start<0||clip.end<=clip.start)return;
    open(clip);
  };
  window.addEventListener('solasi-open-audio',receive);
  if(nativeApp())void nativeCommand({op:'ui_ready'}).catch(error=>{if(active)failed((error as Error).message);});
  return()=>{active=false;window.removeEventListener('solasi-open-audio',receive);};
}
