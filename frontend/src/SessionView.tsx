import React,{useState} from 'react';
import MaterialView from './MaterialView';
import TranscriptView from './TranscriptView';
import Recorder from './Recorder';
import QuestionCards from './QuestionCards';
import TranscriptionTerms from './TranscriptionTerms';
import ConceptView from './ConceptView';
import MeetingView from './MeetingView';
import StudyView from './StudyView';
import QuestionView from './QuestionView';
import {api} from './api';
import type {Session,Course} from './types';
export default function SessionView({session,course,onDeleted,onRecordingChange}:{session:Session;course?:Course;onRecordingChange?:(active:boolean)=>void;onDeleted:(pending?:number)=>Promise<void>}) {
  const [tab,setTab]=useState<'transcript'|'material'|'note'|'concept'|'question'|'study'|'minutes'>('transcript');
  const [question,setQuestion]=useState(''),[quiz,setQuiz]=useState<string|null>(null);
  const [confirm,setConfirm]=useState<'session'|'audio'|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
  async function remove(){
    setBusy(true);setError('');
    try{
      const result=await api<{cleanup_pending:number}>('/sessions/'+session.id+(confirm==='audio'?'/audio':''),{method:'DELETE',body:JSON.stringify({confirmed:true})});
      if(confirm==='session'){await onDeleted(result.cleanup_pending);return;}
      setConfirm(null);
      if(result.cleanup_pending)setError('일부 앱 파일 정리 대기 · 재실행 시 재시도');
    }catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  return <section className="session-workspace">
    <div className="section-heading"><div><span className="eyebrow">{session.kind==='lecture'?'수업':'회의'}</span><h1>{session.title}</h1><p>{new Date(session.started_at).toLocaleString('ko-KR')}{session.lecture_no?' · '+session.lecture_no+'회차':''}</p></div><div><button onClick={()=>setConfirm('audio')}>원음 삭제·연결 해제</button><button onClick={()=>setConfirm('session')}>기록 삭제</button></div></div>
    {confirm&&<section className="card" role="alertdialog" aria-label="삭제 확인"><h2>{confirm==='session'?'기록 삭제':'원음 삭제·연결 해제'}</h2><p>{confirm==='session'?'앱의 녹음·전사·노트·결과물을 삭제합니다.':'앱 녹음을 삭제하고 외부 오디오 연결을 해제합니다. 전사·노트는 보관합니다.'} 연결한 외부 원본 파일은 유지됩니다.</p><button disabled={busy} onClick={()=>setConfirm(null)}>취소</button><button disabled={busy} onClick={()=>void remove()}>확인하고 삭제</button></section>}
    {error&&<p role="alert">{error}</p>}
    <TranscriptionTerms sessionId={session.id}/>
    <Recorder sessionId={session.id} onActiveChange={onRecordingChange}/>
    <QuestionCards session={session}/>
    <div className="segmented" role="tablist" aria-label="기록 내용">{([['transcript','전사'],['material','자료'],['note','노트'],['concept','검색·개념'],['question','질문'],...(session.kind==='lecture'?([['study','학습']] as const):([['minutes','회의록']] as const))] as const).map(([value,label])=><button key={value} role="tab" aria-selected={tab===value} onClick={()=>setTab(value)}>{label}</button>)}</div>
    <div hidden={tab!=='transcript'}><TranscriptView sessionId={session.id}/></div>
    <div hidden={tab!=='material'&&tab!=='note'}><MaterialView session={session} course={course} mode={tab==='material'?'material':'note'}/></div>
    <div hidden={tab!=='concept'}><ConceptView session={session} onQuestion={prompt=>{setQuestion(prompt);setTab('question');}} onQuiz={id=>{setQuiz(id);setTab('study');}}/></div>
    <div hidden={tab!=='question'}><QuestionView session={session} initialPrompt={question}/></div>
    {session.kind==='lecture'&&<div hidden={tab!=='study'}><StudyView session={session} artifactId={quiz}/></div>}
    {session.kind==='meeting'&&<div hidden={tab!=='minutes'}><MeetingView session={session}/></div>}
  </section>;
}
