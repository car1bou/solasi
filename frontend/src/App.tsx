import React, { useEffect, useState } from 'react';
import { api, connect } from './api';
import type { Course, Session } from './types';
import SessionView from './SessionView';
import Readiness from './Readiness';
import SettingsView from './SettingsView';

export default function App() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [ready, setReady] = useState(false);
  const [settings,setSettings]=useState(false);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [kind, setKind] = useState<'lecture' | 'meeting'>('lecture');
  const [title, setTitle] = useState('');
  const [courseId, setCourseId] = useState('');
  const [lectureNo, setLectureNo] = useState('1');
  const [courseTitle, setCourseTitle] = useState('');
  async function refresh() {
    const [c, s] = await Promise.all([api<Course[]>('/courses'), api<Session[]>('/sessions')]);
    setCourses(c); setSessions(s);
  }
  useEffect(() => {connect().then(refresh).then(() => setReady(true)).catch(e => setError(e.message));}, []);
  const session = sessions.find(s => s.id === selected);
  async function createCourse(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {const c = await api<Course>('/courses', {method: 'POST', body: JSON.stringify({title: courseTitle})}); setCourseId(c.id); setCourseTitle(''); await refresh();}
    catch (e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  async function createSession(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {const s = await api<Session>('/sessions', {method: 'POST', body: JSON.stringify({kind, title, course_id: kind === 'lecture' ? courseId || null : null, lecture_no: kind === 'lecture' ? Number(lectureNo) : null})}); await refresh(); setSelected(s.id); setCreating(false);setSettings(false); setTitle('');}
    catch (e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  return <div className="app-shell">
    <aside className="sidebar"><button className="brand" onClick={() => {setSelected(null);setSettings(false);}}><span className="brand-symbol" aria-hidden="true">◒</span><span>기록실</span></button>
      <button className="primary new-button" onClick={() => {setCreating(true); setSelected(null);setSettings(false);}} disabled={!ready}>＋ 새 기록</button>
      <div className="sidebar-label">최근 기록 <span>{sessions.length}</span></div>
      <nav aria-label="기록 목록">{sessions.map(s => <button key={s.id} className={'session-link ' + (selected === s.id ? 'active' : '')} onClick={() => {setSelected(s.id); setCreating(false);setSettings(false);}}><span className="session-type">{s.kind === 'lecture' ? '수업' : '회의'}</span><span>{s.title}<small>{new Date(s.started_at).toLocaleDateString('ko-KR')}</small></span></button>)}</nav><button className="settings-button" disabled={!ready} onClick={()=>{setSettings(true);setSelected(null);setCreating(false);}}>모델·키 설정</button>
    </aside>
    <main>
      {error && <div className="error-banner" role="alert">{error}<button aria-label="오류 메시지 닫기" onClick={() => setError('')}>×</button></div>}
      {!ready && !error && <p role="status">연결 중…</p>}
      {settings ? <SettingsView/> : session ? <SessionView key={session.id} session={session} onDeleted={async(pending)=>{setSelected(null);await refresh();if(pending)setError('일부 앱 파일 정리 대기 · 재실행 시 재시도');}}/> : <div className="home">
        <div className="section-heading"><h1>기록</h1></div>
        {creating ? <section className="card creation"><h2>새 기록</h2><form onSubmit={createSession}><div className="segmented"><button type="button" aria-pressed={kind === 'lecture'} onClick={() => setKind('lecture')}>수업</button><button type="button" aria-pressed={kind === 'meeting'} onClick={() => setKind('meeting')}>회의</button></div><label>제목<input value={title} onChange={e => setTitle(e.target.value)} required maxLength={200}/></label>
          {kind === 'lecture' && <div className="form-row"><label>과목<select value={courseId} onChange={e => setCourseId(e.target.value)}><option value="">미지정</option>{courses.map(c => <option key={c.id} value={c.id}>{c.title}</option>)}</select></label><label>회차<input type="number" min="1" value={lectureNo} onChange={e => setLectureNo(e.target.value)} required/></label></div>}<div className="actions"><button type="button" onClick={() => setCreating(false)}>취소</button><button className="primary" disabled={busy}>기록 만들기</button></div></form></section> : <section className="welcome-grid"><button className="welcome-card" onClick={() => {setKind('lecture');setCreating(true);}} disabled={!ready}><h2>수업</h2></button><button className="welcome-card" onClick={() => {setKind('meeting');setCreating(true);}} disabled={!ready}><h2>회의</h2></button></section>}
        <section className="card"><div className="subheading"><h2>과목</h2><span className="muted">{courses.length}개</span></div>{courses.length ? <div className="course-list">{courses.map(c => <div key={c.id}><span className="course-icon" aria-hidden="true">▤</span><strong>{c.title}</strong><span className="muted">{sessions.filter(s => s.course_id === c.id).length}개 기록</span></div>)}</div> : null}<form className="inline-form" onSubmit={createCourse}><label className="sr-only" htmlFor="course-title">과목 이름</label><input id="course-title" value={courseTitle} onChange={e => setCourseTitle(e.target.value)} placeholder="과목 이름" required maxLength={200}/><button disabled={!ready || busy}>과목 추가</button></form></section><Readiness/>
      </div>}
    </main>
  </div>;
}
