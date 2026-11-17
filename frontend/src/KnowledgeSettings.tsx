import React,{useEffect,useState} from 'react';
import {api} from './api';
type Status={enabled:boolean;idle:boolean;counts:Record<string,number>;errors:{key:string;error:string|null}[];index:{ready:boolean;unindexed_chunks?:number};building:{model:string;completed_chunks:number;total_chunks:number}|null};
export function KnowledgeErrors({errors}:{errors:Status['errors']}){
 const groups=new Map<string,number>();for(const item of errors){const message=item.error??'';groups.set(message,(groups.get(message)||0)+1);}
 if(!errors.length)return null;
 return <details className="knowledge-errors"><summary>최근 오류 {errors.length}건 · {groups.size}종류</summary><p className="muted">전체 실패 건수와 별개로 최근 오류만 묶어 표시합니다.</p><ul>{[...groups].map(([message,count])=><li key={message}><span className="badge">{count}건</span><p>{message||'오류 설명 없음'}</p></li>)}</ul></details>;
}
export default function KnowledgeSettings(){
 const [status,setStatus]=useState<Status|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 useEffect(()=>{let live=true;async function read(){try{const s=await api<Status>('/knowledge/status');if(live)setStatus(s);}catch(e){if(live)setError((e as Error).message);}}void read();const timer=setInterval(()=>void read(),5000);return()=>{live=false;clearInterval(timer);};},[]);
 async function act(path:string,body?:unknown){setBusy(true);setError('');try{setStatus(await api<Status>(path,{method:body?'PUT':'POST',...(body?{body:JSON.stringify(body)}:{})}));}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 return <section className="card"><h2>세컨드 브레인</h2><label className="checkbox-line"><input type="checkbox" checked={status?.enabled??false} disabled={!status||busy} onChange={e=>void act('/knowledge/options',{enabled:e.target.checked})}/>로컬 유휴 시간에 손글씨 인식·의미 색인·연결 후보 갱신</label><p className="muted">녹음·전사·사용자 요청을 우선합니다. 손글씨는 확인한 인식문만 지식에 추가하며 외부 API를 자동 호출하지 않습니다.</p>{status&&<p role="status">{!status.enabled?'일시 정지':!status.idle?'사용자 작업 후 처리':'유휴 시간 처리'} · 대기 {status.counts.pending||0} · 실패 {status.counts.failed||0}{status.index.ready?' · 의미 색인 미반영 '+(status.index.unindexed_chunks||0)+'개':' · 의미 색인 준비 전'}</p>}{status?.building&&<p role="status">의미 색인 준비 {status.building.completed_chunks}/{status.building.total_chunks}개</p>}{status&&<KnowledgeErrors errors={status.errors}/>}{!!status?.counts.failed&&<button disabled={busy} title={'실패한 자동 작업 '+status?.counts.failed+'건 전체를 다시 대기열에 넣습니다'} onClick={()=>void act('/knowledge/retry')}>실패한 자동 작업 재시도</button>}{error&&<p role="alert">{error}</p>}</section>;
}

export function StudyMemoryOptions(){
 const [enabled,setEnabled]=useState<boolean|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
 useEffect(()=>{let live=true;void api<{enabled:boolean}>('/study/options').then(s=>{if(live)setEnabled(s.enabled);}).catch(e=>{if(live)setError(e.message);});return()=>{live=false;};},[]);
 return <section className="card"><h2>대화·학습 기억</h2><label className="checkbox-line"><input type="checkbox" checked={enabled??false} disabled={enabled===null||busy} onChange={e=>{const value=e.target.checked;setBusy(true);setError('');void api<{enabled:boolean}>('/study/options',{method:'PUT',body:JSON.stringify({enabled:value})}).then(s=>setEnabled(s.enabled)).catch(e=>setError(e.message)).finally(()=>setBusy(false));}}/>이전 맥락 사용·자동 정리</label><p className="muted">대화를 이어가고 같은 과목의 공부한 지점·어려움을 기억합니다. 자동 정리는 로컬 AI만 사용합니다. 끄면 이전 대화·학습 기억을 답변에 사용하거나 새로 정리하지 않지만, 대화 원문은 계속 저장합니다. 다시 켜면 정지 중 쌓인 대화도 정리할 수 있습니다.</p><p className="muted">기억 확인·수정·삭제는 과목의 질문 화면에서 할 수 있습니다. 외부 API에 이전 맥락을 보내려면 각 요청에서 직접 선택해야 합니다.</p>{error&&<p role="alert">{error}</p>}</section>;
}
