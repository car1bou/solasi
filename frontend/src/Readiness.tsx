import React, {useEffect, useState} from 'react';
import {api} from './api';
type Component = {label: string; ready: boolean};
export default function Readiness() {
  const [items, setItems] = useState<Component[]>([]);
  const [error, setError] = useState('');
  useEffect(() => {api<Component[]>('/runtime/status').then(setItems).catch(e=>setError(e.message));}, []);
  return <section className="card"><h2>준비 상태</h2>{error && <p role="alert">{error}</p>}<div className="readiness-list">{items.map(item=><div key={item.label}><span>{item.label}</span><span className={'badge ' + (item.ready ? '' : 'pending')}>{item.ready ? '준비됨' : '설치·연결 필요'}</span></div>)}</div></section>;
}
