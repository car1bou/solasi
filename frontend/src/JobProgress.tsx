import React,{useState} from 'react';
import {api} from './api';
import type {Job} from './types';

export default function JobProgress<T>({job,onChange}:{job:Job<T>;onChange:(job:Job<T>)=>void}){
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  const active=['queued','running'].includes(job.status);
  async function act(action:'cancel'|'retry'){
    setBusy(true);setError('');
    try{onChange(await api<Job<T>>('/jobs/'+job.id+'/'+action,{method:'POST'}));}
    catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  return <div role="status"><p>{active&&job.result?.paused_reason||({queued:'대기',running:'처리 중',done:'완료',failed:'실패',cancelled:'취소됨',interrupted:'중단됨'}[job.status])}</p>{job.error&&<p role="alert">{job.error}</p>}{error&&<p role="alert">{error}</p>}{active&&<button type="button" disabled={busy} onClick={()=>void act('cancel')}>작업 취소</button>}{['failed','cancelled','interrupted'].includes(job.status)&&<button type="button" disabled={busy} onClick={()=>void act('retry')}>같은 요청 재시도</button>}</div>;
}
