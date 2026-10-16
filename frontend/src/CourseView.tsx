import React,{useState} from 'react';
import type {Course,Session} from './types';
import MaterialLibrary from './MaterialLibrary';
import QuestionView from './QuestionView';
import {navigate} from './native-lifecycle';
export default function CourseView({course,sessions,onNewLecture,onSession}:{course:Course;sessions:Session[];onNewLecture:()=>void;onSession:(id:string)=>void}){
  const [tab,setTab]=useState<'materials'|'answer'|'summary'>('materials');
  return <section className="course-workspace"><div className="section-heading"><div><span className="eyebrow">과목</span><h1>{course.title}</h1>{course.description&&<p>{course.description}</p>}</div><button className="primary" onClick={onNewLecture}>＋ 이 과목 강의 기록</button></div><div className="segmented" aria-label="과목 내용">{([['materials','자료·필기'],['answer','자료·메모 질문'],['summary','자료·메모 요약']] as const).map(([value,label])=><button key={value} aria-pressed={tab===value} onClick={()=>{if(tab!==value)navigate(()=>setTab(value));}}>{label}</button>)}</div>{tab==='materials'?<MaterialLibrary course={course}/>:<QuestionView key={tab} course={course} kind={tab} scope={{course_id:course.id,mode:'course'}}/>}<section className="card course-recordings"><h2>강의 기록</h2>{sessions.length?sessions.map(session=><button key={session.id} onClick={()=>onSession(session.id)}>{session.lecture_no?session.lecture_no+'회차 · ':''}{session.title}<small>{new Date(session.started_at).toLocaleDateString('ko-KR')}</small></button>):<p>아직 강의 기록이 없습니다. 자료·필기는 강의 기록 없이도 저장됩니다.</p>}</section></section>;
}
