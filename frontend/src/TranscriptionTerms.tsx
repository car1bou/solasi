import React,{useEffect,useState} from 'react';
import {api} from './api';

export default function TranscriptionTerms({sessionId}:{sessionId:string}){
  const [text,setText]=useState(''),[effective,setEffective]=useState(''),[busy,setBusy]=useState(true),[error,setError]=useState(''),[saved,setSaved]=useState(false);
  useEffect(()=>{let active=true;setBusy(true);setText('');setEffective('');setError('');setSaved(false);void api<{terms:string[],effective_prompt:string}>('/sessions/'+sessionId+'/transcription-terms').then(data=>{if(active){setText(data.terms.join(', '));setEffective(data.effective_prompt);}}).catch(e=>{if(active)setError(e.message);}).finally(()=>{if(active)setBusy(false);});return()=>{active=false;};},[sessionId]);
  async function save(event:React.FormEvent){
    event.preventDefault();setBusy(true);setError('');setSaved(false);
    try{
      const result=await api<{terms:string[],effective_prompt:string}>('/sessions/'+sessionId+'/transcription-terms',{method:'PUT',body:JSON.stringify({terms:text.split(/[,\n]/).map(t=>t.trim()).filter(Boolean)})});
      setText(result.terms.join(', '));setEffective(result.effective_prompt);setSaved(true);
    }catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  return <details className="card"><summary>전사 용어</summary><form onSubmit={e=>void save(e)}><label htmlFor="transcription-terms">이번 녹음의 이름·지명·전문용어</label><textarea id="transcription-terms" disabled={busy} value={text} onChange={e=>{setText(e.target.value);setSaved(false);}} placeholder="이란, 자그로스산맥" maxLength={200}/><button disabled={busy} type="submit">{busy?'처리 중':'저장'}</button>{saved&&<span role="status"> 저장됨 · 다음 전사 구간부터 적용</span>}{error&&<p role="alert">{error}</p>}</form>{effective&&<p>적용 힌트: {effective}</p>}<small>등록한 과목 개념·현재 참석자 이름 포함. 입력한 명칭 우선.</small></details>;
}
