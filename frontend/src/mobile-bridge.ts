import {createWebPlayback} from './native-web-playback.ts';

type Fields=Record<string,unknown>;
type AndroidNative={postMessage(message:string):void;onmessage:((event:{data:string})=>void)|null};
declare global {interface Window {SolasiNative?:AndroidNative;}}

export function androidApp():boolean{
  if(typeof window==='undefined'||typeof location==='undefined'||window.top!==window)return false;
  const url=new URL(location.href);
  return url.origin==='https://solasi.invalid'&&!url.username&&!url.password&&['/','/index.html'].includes(url.pathname)&&typeof window.SolasiNative?.postMessage==='function';
}

const sessions=new WeakMap<AndroidNative,{command:(message:unknown)=>Promise<unknown>}>();
const operations=new Set(['http','cancel','ui_ready','export_text','audio_start','audio_stop','playback_load','playback_play','playback_pause','playback_seek','playback_volume','playback_close','playback_release']);
function fields(value:unknown):value is Fields{return value!==null&&typeof value==='object'&&!Array.isArray(value);}

function session(){
  if(!androidApp())throw new Error('앱 연결을 준비하지 못했습니다. Solasi를 다시 실행하세요.');
  const page=window,bridge=page.SolasiNative!;
  const installed=sessions.get(bridge);if(installed)return installed;
  const playback=createWebPlayback();
  const pending=new Map<string,{op:string;clientID:unknown;resolve:(value:unknown)=>void;reject:(error:Error)=>void;timer:ReturnType<typeof setTimeout>}>();
  const receive=(event:{data:string})=>{
    if(!androidApp()||window!==page||window.SolasiNative!==bridge||typeof event.data!=='string')return;
    let reply:unknown;try{reply=JSON.parse(event.data);}catch{return;}
    if(!fields(reply)||typeof reply.id!=='string')return;
    const request=pending.get(reply.id);if(!request)return;
    pending.delete(reply.id);clearTimeout(request.timer);
    const result=Object.hasOwn(reply,'result'),error=Object.hasOwn(reply,'error');
    const validResult=fields(reply.result)&&(request.op!=='http'||Number.isInteger(reply.result.status)&&Number(reply.result.status)>=100&&Number(reply.result.status)<=599&&typeof reply.result.text==='string');
    if(result===error||error&&typeof reply.error!=='string'||result&&!validResult)request.reject(new Error('앱 응답 형식을 확인할 수 없습니다.'));
    else if(error)request.reject(new Error(reply.error as string));
    else request.resolve(reply.result);
  };
  bridge.onmessage=receive;
  page.addEventListener('pagehide',()=>{
    for(const request of pending.values()){clearTimeout(request.timer);request.reject(new Error('앱 화면이 닫혀 요청이 종료되었습니다.'));}
    pending.clear();playback.close();
    if(bridge.onmessage===receive)bridge.onmessage=null;
    sessions.delete(bridge);
  },{once:true});
  const installedSession={async command(message:unknown){
    if(!androidApp()||window!==page||window.SolasiNative!==bridge)throw new Error('앱 연결을 준비하지 못했습니다.');
    if(!fields(message)||typeof message.op!=='string'||!operations.has(message.op)||Object.hasOwn(message,'native_selected_files'))throw new Error('허용하지 않은 앱 요청입니다.');
    let encoded:string;
    try{encoded=JSON.stringify(message,(_key,value)=>{
      if(typeof value==='number'&&!Number.isFinite(value)||['function','symbol','bigint'].includes(typeof value))throw new Error();
      return value;
    });}catch{throw new Error('앱 요청 형식을 확인하세요.');}
    if(message.op.startsWith('playback_'))return playback.command(message);
    if(message.op==='cancel'){
      if(typeof message.target!=='string')throw new Error('취소 요청 식별자를 확인하세요.');
      for(const [id,request] of pending)if(request.op==='http'&&request.clientID===message.target){
        clearTimeout(request.timer);pending.delete(id);request.reject(new Error('앱 요청이 취소되었습니다.'));
      }
    }
    if(pending.size>=32)throw new Error('처리 중인 앱 요청이 많습니다. 잠시 뒤 다시 시도하세요.');
    const id=crypto.randomUUID();
    return new Promise<unknown>((resolve,reject)=>{
      const timer=setTimeout(()=>{pending.delete(id);reject(new Error('앱 응답 대기 시간이 초과되었습니다.'));},120000);
      pending.set(id,{op:message.op as string,clientID:message.id,resolve,reject,timer});
      try{bridge.postMessage('{"id":'+JSON.stringify(id)+',"message":'+encoded+'}');}
      catch(error){clearTimeout(timer);pending.delete(id);reject(error instanceof Error?error:new Error('앱 요청을 보내지 못했습니다.'));}
    });
  }};
  sessions.set(bridge,installedSession);return installedSession;
}

export function installMobileBridge(){if(androidApp())session();}
export async function mobileCommand(message:unknown):Promise<unknown>{return session().command(message);}
