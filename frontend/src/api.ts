export class ApiError extends Error {
  status:number;
  constructor(message:string,status:number){super(message);this.name='ApiError';this.status=status;}
}
let csrf = '';
let connection: Promise<void> | null = null;
type NativeReply={status:number;text:string};
type NativeHandler={postMessage(message:unknown):Promise<unknown>};
declare global {interface Window {webkit?:{messageHandlers?:{solasi?:NativeHandler}};}}
export function nativeApp():boolean{return typeof location!=='undefined'&&location.protocol==='solasi-app:';}
export async function nativeCommand<T>(message:unknown):Promise<T>{
  const bridge=typeof window!=='undefined'?window.webkit?.messageHandlers?.solasi:undefined;
  if(!nativeApp()||!bridge)throw new Error('앱 연결을 준비하지 못했습니다. Solasi를 다시 실행하세요.');
  return await bridge.postMessage(message) as T;
}
export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  if(nativeApp()){
    if(options.body!==undefined&&typeof options.body!=='string')throw new Error('지원하지 않는 앱 요청입니다.');
    options.signal?.throwIfAborted();
    const id=crypto.randomUUID();
    const abort=()=>{void nativeCommand({op:'cancel',target:id}).catch(()=>{});};
    options.signal?.addEventListener('abort',abort,{once:true});
    try{
      const response=await nativeCommand<NativeReply>({op:'http',id,path:'/api'+path,method:options.method||'GET',...(options.body?{body:options.body}:{})});
      options.signal?.throwIfAborted();
      const result=response.text?JSON.parse(response.text):undefined;
      if(response.status<200||response.status>=300)throw new ApiError(typeof result?.detail==='string'?result.detail:'입력 정보를 확인하세요.',response.status);
      return result as T;
    }finally{options.signal?.removeEventListener('abort',abort);}
  }
  if (path !== '/bootstrap' && path !== '/client') await connect();
  const headers = new Headers(options.headers);
  if (options.body && typeof options.body === 'string') headers.set('Content-Type', 'application/json');
  if (csrf) headers.set('X-Session-Token', csrf);
  const response = await fetch('/api' + path, {...options, headers, credentials: 'same-origin'});
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new ApiError(typeof error.detail === 'string' ? error.detail : '입력 정보를 확인하세요.', response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}
export function connect(): Promise<void> {
  if(nativeApp())return nativeCommand({op:'http',id:crypto.randomUUID(),path:'/api/health',method:'GET'}).then(()=>{});
  if (!connection) connection = (async () => {
    const token = new URLSearchParams(location.hash.slice(1)).get('bootstrap');
    history.replaceState(null, '', location.pathname);
    const result = token
      ? await api<{csrf_token: string}>('/bootstrap', {method: 'POST', body: JSON.stringify({token})})
      : await api<{csrf_token: string}>('/client');
    csrf = result.csrf_token;
  })();
  return connection;
}
export function sessionToken(): string {return csrf;}
export async function downloadJSON(filename:string,value:unknown):Promise<void>{
  const text=JSON.stringify(value,null,2);
  if(nativeApp()){await nativeCommand({op:'export_text',filename,text});return;}
  const url=URL.createObjectURL(new Blob([text],{type:'application/json'})),anchor=document.createElement('a');
  anchor.href=url;anchor.download=filename;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
