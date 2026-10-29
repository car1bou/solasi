import React from 'react';
import type {Course,Session} from './types';
import Icon from './Icon';

export default function SessionList({sessions,courses,onSession,recording=[]}:{sessions:Session[];courses:Course[];onSession:(id:string)=>void;recording?:string[]}){
  return <div className="record-list">{[...sessions].sort((a,b)=>Date.parse(b.started_at)-Date.parse(a.started_at)).map(session=><button key={session.id} className="record-row" onClick={()=>onSession(session.id)}>
    <Icon name={session.kind==='lecture'?'book':'mic'} size={21}/>
    <span className="record-copy"><strong>{session.lecture_no?session.lecture_no+'회차 · ':''}{session.title}</strong><small>{session.kind==='meeting'?'회의':courses.find(course=>course.id===session.course_id)?.title||'미지정 강의'}{recording.includes(session.id)&&<span className="record-live"> · 녹음 중</span>}</small></span>
    <time dateTime={session.started_at}>{new Date(session.started_at).toLocaleDateString('ko-KR')}</time><Icon name="arrow" size={17}/>
  </button>)}</div>;
}
