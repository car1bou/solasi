import React,{useEffect,useRef,useState} from 'react';
import {api} from './api';

type HintState={terms:string[],effective_prompt:string,excluded_terms?:{term:string,reason:string}[]};
export default function TranscriptionTerms({sessionId}:{sessionId:string}){
  const [text,setText]=useState(''),[effective,setEffective]=useState(''),[excluded,setExcluded]=useState<NonNullable<HintState['excluded_terms']>>([]),[busy,setBusy]=useState(true),[error,setError]=useState(''),[saved,setSaved]=useState(false);
  const sequence=useRef(0);
  async function request(write:boolean,initial=false){
    const current=++sequence.current;setBusy(true);setError('');
    try{
      const result=await api<HintState>('/sessions/'+sessionId+'/transcription-terms',write?{method:'PUT',body:JSON.stringify({terms:text.split(/[,\n]/).map(t=>t.trim()).filter(Boolean)})}:undefined);
      if(current!==sequence.current)return;
      if(write||initial)setText(result.terms.join(', '));
      setEffective(result.effective_prompt);setExcluded(result.excluded_terms??[]);
      if(write)setSaved(true);
    }catch(e){if(current===sequence.current)setError((e as Error).message);}
    finally{if(current===sequence.current)setBusy(false);}
  }
  useEffect(()=>{setText('');setEffective('');setExcluded([]);setSaved(false);void request(false,true);return()=>{++sequence.current;};},[sessionId]);
  return <details className="card"><summary>전사 용어</summary>
    <form onSubmit={e=>{e.preventDefault();void request(true);}}>
      <label htmlFor="transcription-terms">이번 녹음의 이름·지명·전문용어</label>
      <textarea id="transcription-terms" disabled={busy} value={text} onChange={e=>{setText(e.target.value);setSaved(false);}} placeholder="이란, 자그로스산맥" maxLength={200}/>
      <button disabled={busy} type="submit">{busy?'처리 중':'저장'}</button>
      <button disabled={busy} type="button" onClick={()=>void request(false)}>힌트 다시 확인</button>
      {saved&&<span role="status"> 저장됨 · 다음 전사 구간부터 적용</span>}
      {error&&<p role="alert">{error}</p>}
    </form>
    {effective&&<p>Whisper 적용 힌트: {effective}</p>}
    {!!excluded.length&&<div><p>이번 힌트에서 제외된 용어</p><ul>{excluded.map((item,index)=><li key={index}>{item.term} · {item.reason}</li>)}</ul><small>근거가 바뀐 용어는 과목 개념의 원문·근거를 검토한 뒤 다시 등록하세요. 기존 용어와 대본은 보존됩니다.</small></div>}
    <small>등록한 과목 개념·현재 참석자 이름 포함. 입력한 명칭 우선. 힌트 다시 확인은 입력 중인 내용을 바꾸지 않습니다.</small>
  </details>;
}
