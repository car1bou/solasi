import {createWebPlayback} from './native-web-playback.ts';

type Fields=Record<string,unknown>;
type Command=(message:Fields)=>Promise<unknown>;
declare global {interface Window {
  solasiWindows?:{command:Command};
  pywebview?:{api?:{command?:Command}};
}}

export function installWindowsBridge(){
  if(typeof window==='undefined'||typeof location==='undefined'||location.origin!=='https://solasi.invalid'||!window.solasiWindows)return;
  const bridge=window.solasiWindows,original=bridge.command;
  const playback=createWebPlayback();
  let ready:Promise<void>|undefined;
  bridge.command=async(message:Fields)=>{
    if(typeof message?.op==='string'&&message.op.startsWith('playback_'))return playback.command(message);
    if(!window.pywebview?.api?.command){
      ready??=new Promise<void>((resolve,reject)=>{
        const listener=()=>{clearTimeout(timer);resolve();};
        const timer=setTimeout(()=>{window.removeEventListener('pywebviewready',listener);ready=undefined;reject(new Error('Windows 앱 연결 시간 초과'));},15000);
        window.addEventListener('pywebviewready',listener,{once:true});
      });
      await ready;
    }
    return original(message);
  };
}
