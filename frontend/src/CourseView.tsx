import React,{useId,useRef,useState} from 'react';
import type {Course,Session} from './types';
import MaterialLibrary from './MaterialLibrary';
import QuestionView from './QuestionView';
import SessionList from './SessionList';
import Icon from './Icon';
import {navigate} from './native-lifecycle';

const tabs=[['materials','자료·필기'],['recordings','강의 기록'],['answer','질문'],['summary','요약']] as const;
export default function CourseView({course,sessions,recording=[],onNewLecture,onSession,sidebarToggle}:{course:Course;sessions:Session[];recording?:string[];onNewLecture:()=>void;onSession:(id:string)=>void;sidebarToggle?:React.ReactNode}){
  const [tab,setTab]=useState<typeof tabs[number][0]>('materials');
  const id=useId(),tablist=useRef<HTMLDivElement>(null);
  function moveTab(event:React.KeyboardEvent){
    const index=tabs.findIndex(([value])=>value===tab);
    const next=event.key==='Home'?0:event.key==='End'?tabs.length-1:event.key==='ArrowRight'?(index+1)%tabs.length:event.key==='ArrowLeft'?(index+tabs.length-1)%tabs.length:-1;
    if(next<0)return;event.preventDefault();navigate(()=>{setTab(tabs[next][0]);tablist.current?.querySelectorAll<HTMLButtonElement>('[role=tab]')[next]?.focus();});
  }
  return <section className="course-workspace">
    <span className="workspace-location">과목 / {course.title}</span>
    <div className="section-heading">{tab==='materials'&&sidebarToggle}<div><h1 title={course.title}>{course.title}</h1>{course.description&&<p>{course.description}</p>}</div><button className="primary" aria-label="새 강의 기록" title="새 강의 기록" onClick={onNewLecture}><Icon name="plus" size={17}/>새 강의 기록</button></div>
    <div ref={tablist} className="segmented workspace-tabs" role="tablist" aria-label="과목 내용" onKeyDown={moveTab}>{tabs.map(([value,label])=><button key={value} id={id+'-'+value} role="tab" aria-selected={tab===value} aria-controls={id+'-panel'} tabIndex={tab===value?0:-1} onClick={()=>{if(tab!==value)navigate(()=>setTab(value));}}>{label}</button>)}</div>
    <div id={id+'-panel'} role="tabpanel" aria-labelledby={id+'-'+tab}>
      <div hidden={tab!=='materials'}><MaterialLibrary course={course}/></div>
      {tab==='recordings'&&<section className="course-recordings"><div className="subheading"><h2>강의 기록</h2><span className="muted">{sessions.length}개</span></div><SessionList sessions={sessions} courses={[course]} recording={recording} onSession={onSession}/>{!sessions.length&&<div className="empty-state"><h3>아직 강의 기록이 없습니다</h3><button className="primary" aria-label="새 강의 기록" title="새 강의 기록" onClick={onNewLecture}><Icon name="plus" size={17}/>새 강의 기록</button></div>}</section>}
      {(tab==='answer'||tab==='summary')&&<QuestionView key={tab} course={course} kind={tab} scope={{course_id:course.id,mode:'course'}}/>}
    </div>
  </section>;
}
