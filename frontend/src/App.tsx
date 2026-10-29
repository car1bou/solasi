import React,{useEffect,useRef,useState} from 'react';
import {api,connect} from './api';
import type {Course,Session} from './types';
import SessionView from './SessionView';
import CourseView from './CourseView';
import Readiness from './Readiness';
import SettingsView from './SettingsView';
import SessionList from './SessionList';
import Icon from './Icon';
import NativePlayback from './NativePlayback';
import {navigate} from './native-lifecycle';
import {useCloseGuard} from './use-close-guard';

export function CourseNavigation({courses,active,onCourse}:{courses:Course[];active:string|null;onCourse:(id:string)=>void}){
  return <nav aria-label="과목 목록" className="course-navigation">{courses.map(course=><button key={course.id} className={'course-nav-link '+(active===course.id?'active':'')} aria-current={active===course.id?'page':undefined} title={course.title} onClick={()=>onCourse(course.id)}><Icon name="book" size={18}/><span>{course.title}</span></button>)}</nav>;
}

export default function App(){
  const [courses,setCourses]=useState<Course[]>([]),[sessions,setSessions]=useState<Session[]>([]),[selected,setSelected]=useState<string|null>(null),[selectedCourse,setSelectedCourse]=useState<string|null>(null),[recording,setRecording]=useState<string[]>([]);
  const [error,setError]=useState(''),[ready,setReady]=useState(false),[settings,setSettings]=useState(false),[creating,setCreating]=useState(false),[addingCourse,setAddingCourse]=useState(false),[busy,setBusy]=useState(false),[kind,setKind]=useState<'lecture'|'meeting'>('lecture'),[title,setTitle]=useState(''),[courseId,setCourseId]=useState(''),[lectureNo,setLectureNo]=useState('1'),[courseTitle,setCourseTitle]=useState('');
  const [connectionError,setConnectionError]=useState(''),[connecting,setConnecting]=useState(true),[navigationError,setNavigationError]=useState(''),[meetingsOnly,setMeetingsOnly]=useState(false);
  const connectionPending=useRef(false),dialog=useRef<HTMLDialogElement>(null);
  useCloseGuard('새 기록 제목',busy&&!addingCourse||!!title);
  useCloseGuard('새 과목 이름',!!courseTitle||busy&&addingCourse);
  async function initialize(){if(connectionPending.current)return;connectionPending.current=true;setConnecting(true);setConnectionError('');try{await connect();await refresh();setReady(true);}catch(e){setConnectionError((e as Error).message);}finally{connectionPending.current=false;setConnecting(false);}}
  async function refresh(){const [c,s]=await Promise.all([api<Course[]>('/courses'),api<Session[]>('/sessions')]);setCourses(c);setSessions(s);}
  useEffect(()=>{void initialize();const blocked=(event:Event)=>setNavigationError((event as CustomEvent<string>).detail);const moved=()=>setNavigationError('');window.addEventListener('solasi-navigation-blocked',blocked);window.addEventListener('solasi-navigated',moved);return()=>{window.removeEventListener('solasi-navigation-blocked',blocked);window.removeEventListener('solasi-navigated',moved);};},[]);
  useEffect(()=>{window.scrollTo(0,0);},[selected,selectedCourse,settings]);
  useEffect(()=>{if(addingCourse)document.getElementById('course-title')?.focus();},[addingCourse]);
  useEffect(()=>{
    if(!creating)return;
    const element=dialog.current!,trigger=document.activeElement as HTMLElement|null;
    element.showModal();
    element.querySelector<HTMLInputElement>('.record-title input')?.focus();
    return()=>{element.close();if(trigger?.isConnected)trigger.focus();};
  },[creating]);
  function showHome(){setNavigationError('');setSelected(null);setSelectedCourse(null);setSettings(false);setCreating(false);setMeetingsOnly(false);}
  function home(){if(selected||selectedCourse||settings||creating||meetingsOnly)navigate(showHome);}
  function showSession(id:string){setNavigationError('');setSelected(id);setSelectedCourse(null);setCreating(false);setSettings(false);}
  function openSession(id:string){if(selected!==id||settings||creating)navigate(()=>showSession(id));}
  function showCourse(id:string){setNavigationError('');setSelectedCourse(id);setSelected(null);setSettings(false);setCreating(false);}
  function openCourse(id:string){if(selectedCourse!==id||settings||creating)navigate(()=>showCourse(id));}
  function chooseCourse(cid:string){setCourseId(cid);setLectureNo(String(Math.max(0,...sessions.filter(s=>s.course_id===cid).map(s=>s.lecture_no||0))+1));}
  function newSession(nextKind:'lecture'|'meeting',cid=''){navigate(()=>{setNavigationError('');setError('');setKind(nextKind);chooseCourse(cid);setTitle('');setCreating(true);});}
  function cancelCreation(){navigate(()=>{setCreating(false);setTitle('');setError('');},['새 기록 제목']);}
  async function createCourse(event:React.FormEvent){event.preventDefault();if(!navigate(()=>{},['새 과목 이름']))return;setBusy(true);setError('');try{const course=await api<Course>('/courses',{method:'POST',body:JSON.stringify({title:courseTitle})});setCourseTitle('');setAddingCourse(false);await refresh();showCourse(course.id);}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  async function createSession(event:React.FormEvent){event.preventDefault();if(!navigate(()=>{},['새 기록 제목']))return;setBusy(true);setError('');try{const session=await api<Session>('/sessions',{method:'POST',body:JSON.stringify({kind,title,course_id:kind==='lecture'?courseId||null:null,lecture_no:kind==='lecture'?Number(lectureNo):null})});setTitle('');await refresh();showSession(session.id);}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  const course=courses.find(c=>c.id===selectedCourse),currentSession=sessions.find(s=>s.id===selected),visibleSession=!!selected&&!settings;
  const activeCourse=selectedCourse||(!settings?currentSession?.course_id:null)||null;
  function recordForm(modal=false){return <form onSubmit={createSession} className="record-form"><fieldset disabled={!ready||busy}>
    {!modal&&<div className="segmented record-kind" aria-label="기록 종류">{([['lecture','강의','book'],['meeting','회의','mic']] as const).map(([value,label,icon])=><button key={value} type="button" aria-pressed={kind===value} onClick={()=>setKind(value)}><Icon name={icon} size={20}/>{label}</button>)}</div>}
    <div className={'record-fields '+(kind==='meeting'?'meeting-fields':'')}>
      {kind==='lecture'&&<label>과목<select value={courseId} onChange={e=>chooseCourse(e.target.value)}><option value="">미지정</option>{courses.map(c=><option key={c.id} value={c.id}>{c.title}</option>)}</select></label>}
      <label className="record-title">제목<input autoFocus={modal} value={title} onChange={e=>setTitle(e.target.value)} placeholder={kind==='lecture'?'강의 제목':'회의 제목'} required maxLength={200}/></label>
      {kind==='lecture'&&<label className="record-number">회차<input type="number" min="1" value={lectureNo} onChange={e=>setLectureNo(e.target.value)} required/></label>}
    </div>
    <div className="actions">{modal&&<button type="button" onClick={cancelCreation}>취소</button>}<button className="primary" disabled={busy||!ready}>{busy?'만드는 중…':'기록 만들기'}</button>{!modal&&title&&<button type="button" onClick={()=>setTitle('')}>제목 지우기</button>}</div>
    {modal&&<p className="creation-hint">녹음은 다음 화면에서 시작합니다.</p>}
  </fieldset></form>;}
  return <div className="app-shell"><a className="skip-link" href="#workspace">작업 화면으로 이동</a>
    <aside className="sidebar">
      <button className="brand" onClick={home} aria-label="Solasi 홈"><img className="brand-image" src="/solasi-icon.png" alt="" width={40} height={40}/><span>Solasi</span></button>
      <button className={'sidebar-home course-nav-link '+(!selected&&!selectedCourse&&!settings&&!meetingsOnly?'active':'')} onClick={home}><Icon name="book" size={18}/>홈</button>
      <div className="sidebar-label">과목 <button className="sidebar-add" aria-label="과목 추가" disabled={!ready} onClick={()=>navigate(()=>{showHome();setAddingCourse(true);})}><Icon name="plus" size={17}/></button></div>
      <CourseNavigation courses={courses} active={activeCourse} onCourse={openCourse}/>
      <button className={'course-nav-link sidebar-meetings '+(meetingsOnly||currentSession?.kind==='meeting'&&!settings?'active':'')} onClick={()=>navigate(()=>{showHome();setMeetingsOnly(true);setKind('meeting');})}><Icon name="mic" size={18}/>회의 기록</button>
      <div className="sidebar-footer"><button className={'settings-button '+(settings?'active':'')} disabled={!ready} onClick={()=>{if(!settings)navigate(()=>{setNavigationError('');setSelected(null);setSelectedCourse(null);setSettings(true);});}}><Icon name="settings" size={18}/>모델·키 설정</button><span><Icon name="shield" size={13}/> 로컬 워크스페이스</span></div>
    </aside>
    <main id="workspace" tabIndex={-1}>
      {!creating&&error&&<div className="error-banner" role="alert">{error}<button aria-label="오류 메시지 닫기" onClick={()=>setError('')}>×</button></div>}
      {!creating&&navigationError&&<div className="error-banner navigation-warning" role="alert">{navigationError}<button aria-label="미저장 입력 안내 닫기" onClick={()=>setNavigationError('')}>×</button></div>}
      {!ready&&<section className="card" aria-label="앱 연결">{connecting?<p role="status">연결 중…</p>:<><p role="alert">앱에 연결하지 못했습니다. {connectionError}</p><button onClick={()=>void initialize()}>다시 연결</button></>}</section>}
      {recording.filter(id=>id!==selected).length>0&&<div className="recording-navigation" role="status">녹음이 계속되고 있습니다.{recording.filter(id=>id!==selected).map(id=><button key={id} onClick={()=>openSession(id)}>{sessions.find(s=>s.id===id)?.title} 녹음으로 이동</button>)}</div>}
      {sessions.filter(session=>session.id===selected||recording.includes(session.id)).map(session=><div key={session.id} hidden={!visibleSession||selected!==session.id}><SessionView session={session} course={courses.find(c=>c.id===session.course_id)} onCourse={openCourse} onRecordingChange={active=>setRecording(current=>active?(current.includes(session.id)?current:[...current,session.id]):current.filter(id=>id!==session.id))} onDeleted={async pending=>{setRecording(current=>current.filter(id=>id!==session.id));showHome();await refresh();if(pending)setError('일부 앱 파일 정리 대기 · 재실행 시 재시도');}}/></div>)}
      {settings?<SettingsView/>:course?<CourseView key={course.id} course={course} sessions={sessions.filter(s=>s.kind==='lecture'&&s.course_id===course.id)} recording={recording} onNewLecture={()=>newSession('lecture',course.id)} onSession={openSession}/>:!visibleSession&&<div className="home">
        <span className="workspace-location">{meetingsOnly?'회의 기록':'홈'}</span>
        <section className="home-create"><h1>새 기록</h1>{recordForm()}</section>
        <section className="recent-records"><div className="subheading"><h2>{meetingsOnly?'회의 기록':'최근 기록'}</h2></div><SessionList sessions={meetingsOnly?sessions.filter(s=>s.kind==='meeting'):sessions} courses={courses} recording={recording} onSession={openSession}/>{ready&&!(meetingsOnly?sessions.some(s=>s.kind==='meeting'):sessions.length)&&<p className="empty-records">{meetingsOnly?'아직 회의 기록이 없습니다.':'아직 기록이 없습니다.'}</p>}</section>
        <details className="course-create" open={addingCourse} onToggle={e=>setAddingCourse(e.currentTarget.open)}><summary>과목 추가</summary><label htmlFor="course-title">새 과목</label><form className="inline-form" onSubmit={createCourse}><input disabled={busy||!ready} id="course-title" value={courseTitle} onChange={e=>setCourseTitle(e.target.value)} placeholder="과목 이름" required maxLength={200}/><button disabled={!ready||busy}>과목 추가</button>{courseTitle&&<button type="button" disabled={busy} onClick={()=>setCourseTitle('')}>입력 지우기</button>}</form></details>
        <Readiness/>
      </div>}
    </main>
    {creating&&<dialog ref={dialog} className="creation-dialog" aria-labelledby="creation-heading" onCancel={event=>{event.preventDefault();if(!busy)cancelCreation();}}><div className="subheading"><h2 id="creation-heading">{kind==='lecture'?'새 강의 기록':'새 회의 기록'}</h2><button className="icon-button" aria-label="새 기록 닫기" disabled={busy} onClick={cancelCreation}><Icon name="close" size={18}/></button></div>{error&&<p role="alert" className="notebook-error">{error}</p>}{navigationError&&<p role="alert" className="notebook-error">{navigationError}</p>}{recordForm(true)}</dialog>}
    <NativePlayback/>
  </div>;
}
