import React,{useEffect,useState} from 'react';
import {nativeApp,nativeCommand} from './api';

export function UninstallForm({busy,error,onBegin,reset=false}:{busy:boolean;error:string;onBegin:()=>void;reset?:boolean}){
  return <section className="card"><h2>{reset?'앱 초기화':'설치 삭제'}</h2>
    <p>{reset?'앱은 유지하고 원래 보관함·수정 이력, 전용 AI 모델·추가 엔진, 앱 설정·저장된 API 키·캐시·로그를 초기화합니다.':'솔라시와 전용 AI 모델·추가 엔진, 앱 설정·저장된 API 키·캐시·로그를 함께 삭제합니다.'}</p>
    <p>앱 안의 선택창에서 필기·문서, 녹음, 전사·AI 결과를 각각 보존하거나 삭제할 수 있습니다. 처음에는 모두 보존으로 선택됩니다.</p>
    <p>보존 파일 검증과 마지막 확인을 마친 뒤에만 {reset?'초기화합니다. AI 기능은 모델·추가 엔진을 다시 준비한 뒤 사용할 수 있습니다.':'원래 보관함과 앱을 삭제합니다.'} 마지막 확인창에서도 선택을 바꾸면 다시 검증합니다.</p>
    <fieldset disabled={busy}><button type="button" onClick={onBegin}>{reset?'앱 초기화…':'설치 삭제…'}</button></fieldset>
    {busy&&<p role="status">항목 선택·보존 파일 검증 또는 마지막 확인을 진행하고 있습니다. 앱의 안내창을 확인하세요.</p>}
    {error&&<p className="error-banner" role="alert">{error}</p>}
  </section>;
}

export default function UninstallSettings(){
  const [available,setAvailable]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[status,setStatus]=useState('');
  useEffect(()=>{let active=true;if(nativeApp())void nativeCommand<{available:boolean}>({op:'uninstall_info'}).then(value=>{if(active)setAvailable(value.available);}).catch(()=>{});return()=>{active=false;};},[]);
  async function begin(reset=false){
    setBusy(true);setError('');setStatus('');
    try{const result=await nativeCommand<{cancelled?:boolean}>({op:reset?'reset_begin':'uninstall_begin',selection:{documents:true,audio:true,results:true}});if(result.cancelled)setStatus((reset?'초기화':'설치 삭제')+'를 취소했습니다. 앱과 원래 기록을 유지했습니다.');}
    catch(failure){setError((failure as Error).message);}
    finally{setBusy(false);}
  }
  return available?<><UninstallForm reset busy={busy} error={error} onBegin={()=>void begin(true)}/><UninstallForm busy={busy} error={error} onBegin={()=>void begin()}/>{status&&<p role="status">{status}</p>}</>:null;
}
