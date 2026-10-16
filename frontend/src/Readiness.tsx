import React, {useEffect, useState} from 'react';
import {api} from './api';
type Component = {label: string; ready: boolean};
export default function Readiness() {
  const [items, setItems] = useState<Component[]>([]);
  const [error, setError] = useState('');
  useEffect(() => {api<Component[]>('/runtime/status').then(setItems).catch(e=>setError(e.message));}, []);
  return <section className="readiness-card">{error && <p role="alert">{error}</p>}<details><summary><span>준비 상태</span><span className="muted">{error?'확인 실패':items.length?items.filter(item=>item.ready).length+' / '+items.length+' 준비됨':'확인 중…'}</span></summary><div className="readiness-list">{items.map(item=><div key={item.label}><span>{item.label}</span><span className={'badge ' + (item.ready ? '' : 'pending')}>{item.ready ? '준비됨' : '설치·연결 필요'}</span></div>)}</div></details></section>;
}
