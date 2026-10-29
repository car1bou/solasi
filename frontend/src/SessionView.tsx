import React,{useId,useRef,useState} from 'react';
import MaterialView from './MaterialView';
import TranscriptView from './TranscriptView';
import Recorder from './Recorder';
import QuestionCards from './QuestionCards';
import TranscriptionTerms from './TranscriptionTerms';
import ConceptView from './ConceptView';
import MeetingView from './MeetingView';
import StudyView from './StudyView';
import QuestionView from './QuestionView';
import {navigate} from './native-lifecycle';
import {api} from './api';
import Icon from './Icon';
import PopupMenu from './PopupMenu';
import type {Session,Course} from './types';
export default function SessionView({session,course,onDeleted,onRecordingChange,onCourse}:{session:Session;course?:Course;onCourse?:(id:string)=>void;onRecordingChange?:(active:boolean)=>void;onDeleted:(pending?:number)=>Promise<void>}) {
  const [tab,setTab]=useState<'transcript'|'material'|'note'|'concept'|'question'|'study'|'minutes'>(course?'material':'transcript');
  const [question,setQuestion]=useState(''),[quiz,setQuiz]=useState<string|null>(null);
  const [confirm,setConfirm]=useState<'session'|'audio'|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const tablist=useRef<HTMLDivElement>(null),tabId=useId();
  const tabs=[['material','노트'],['transcript','대본'],['question','질문'],...(session.kind==='lecture'?([['study','요약·학습']]as const):([['minutes','회의록']]as const)),['concept','검색·개념']]as const;
  const currentTab=tab==='note'?'material':tab;
  function moveTab(event:React.KeyboardEvent){const index=tabs.findIndex(([value])=>value===currentTab),next=event.key==='Home'?0:event.key==='End'?tabs.length-1:event.key==='ArrowRight'?(index+1)%tabs.length:event.key==='ArrowLeft'?(index+tabs.length-1)%tabs.length:-1;if(next<0)return;event.preventDefault();navigate(()=>{setTab(tabs[next][0]);tablist.current?.querySelectorAll<HTMLButtonElement>('[role=tab]')[next]?.focus();});}
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
    <div className="workspace-location">{course&&onCourse?<button onClick={()=>onCourse(course.id)}>{course.title}</button>:course?.title||(session.kind==='lecture'?'미지정 강의':'회의')}{session.lecture_no?' / '+session.lecture_no+'회차':''}</div>
    <div className="section-heading"><div><h1>{session.title}</h1><p>{new Date(session.started_at).toLocaleDateString('ko-KR')}</p></div><PopupMenu className="session-management"><summary aria-label="기록 메뉴" title="기록 메뉴"><Icon name="more-vertical"/></summary><div><button data-menu-action onClick={()=>setConfirm('audio')}>이 회차 원음 정리…</button><button data-menu-action onClick={()=>setConfirm('session')}>기록 삭제</button></div></PopupMenu></div>
    {confirm&&<section className="card" role="alertdialog" aria-label="삭제 확인"><h2>{confirm==='session'?'기록 삭제':'이 회차 원음 정리'}</h2><p>{confirm==='session'?'앱의 녹음·전사·노트·결과물을 삭제합니다.':'이 회차에서 앱으로 녹음한 원음은 삭제하고, 외부 음성 파일은 연결만 해제합니다. 전사·노트·필기·AI 결과는 보관하지만 이후 원음 재생과 재전사는 할 수 없습니다.'} 연결한 외부 원본 파일은 유지됩니다.</p><button disabled={busy} onClick={()=>setConfirm(null)}>취소</button><button disabled={busy} onClick={()=>void remove()}>확인하고 삭제</button></section>}
    {error&&<p role="alert">{error}</p>}
    <Recorder sessionId={session.id} onActiveChange={onRecordingChange}/>
    <div ref={tablist} className="segmented session-tabs" role="tablist" aria-label="기록 내용" onKeyDown={moveTab}>{tabs.map(([value,label])=><button key={value} id={tabId+'-'+value} role="tab" aria-selected={currentTab===value} aria-controls={tabId+'-panel'} tabIndex={currentTab===value?0:-1} onClick={()=>{if(currentTab!==value)navigate(()=>setTab(value));}}>{label}</button>)}</div>
    <div id={tabId+'-panel'} role="tabpanel" aria-labelledby={tabId+'-'+currentTab}>
    <div className="session-utilities" hidden={tab!=='transcript'}><TranscriptionTerms sessionId={session.id}/><QuestionCards session={session}/></div>
    <div hidden={tab!=='transcript'}><TranscriptView sessionId={session.id}/></div>
    <div hidden={tab!=='material'&&tab!=='note'}><MaterialView session={session} course={course} mode="all"/></div>
    <div hidden={tab!=='concept'}><ConceptView session={session} onQuestion={prompt=>navigate(()=>{setQuestion(prompt);setTab('question');})} onQuiz={id=>navigate(()=>{setQuiz(id);setTab('study');})}/></div>
    <div hidden={tab!=='question'}><QuestionView session={session} initialPrompt={question}/></div>
    {session.kind==='lecture'&&<div hidden={tab!=='study'}><StudyView session={session} artifactId={quiz}/></div>}
    {session.kind==='meeting'&&<div hidden={tab!=='minutes'}><MeetingView session={session}/></div>}
    </div>
  </section>;
}
