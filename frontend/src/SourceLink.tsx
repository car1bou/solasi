import {inkPath} from './ink';
import type {InkStroke} from './types';
import React,{useState,useRef,useEffect} from 'react';
import {api} from './api';
import PlaybackAudio from './PlaybackAudio';
import Icon from './Icon';

type Source={ink_snapshot?:InkStroke[];status:string;ref:{kind:string;page:number|null;version:number;start_ms:number|null;end_ms:number|null;bbox?:number[]|null;source_width?:number|null;source_height?:number|null};text_snapshot:string;open_url:string|null;image_url?:string;seek_seconds:number|null;end_seconds:number|null;original_status?:string;retrieved_at?:string;title?:string};
export function SourceImage({source}:{source:Source}){return <>{source.image_url&&<div className="ink-region-preview"><img alt={'원본 '+source.ref.page+'쪽'} src={source.image_url}/>{source.ref.kind==='ink_note'&&<svg viewBox={'0 0 '+(source.ref.source_width||1)+' '+(source.ref.source_height||1)} preserveAspectRatio="none" aria-hidden="true">{source.ink_snapshot?.map(stroke=><path key={stroke.id} d={inkPath(stroke,source.ref.source_width||1,source.ref.source_height||1)} fill={stroke.color} opacity={stroke.opacity}/>)}{source.ref.bbox&&<rect x={source.ref.bbox[0]*(source.ref.source_width||1)} y={source.ref.bbox[1]*(source.ref.source_height||1)} width={source.ref.bbox[2]*(source.ref.source_width||1)} height={source.ref.bbox[3]*(source.ref.source_height||1)}/>}</svg>}</div>}</>;}
export default function SourceLink({id,label}:{id:string;label:string}) {
  const [source,setSource]=useState<Source|null>(null),[error,setError]=useState('');
  const dialog=useRef<HTMLDialogElement>(null);
  useEffect(()=>{if(source&&!dialog.current?.open)dialog.current?.showModal();},[source]);
  async function open(){setError('');try{setSource(await api<Source>('/sources/'+encodeURIComponent(id)));}catch(e){setError((e as Error).message);}}
  return <span className="source-link"><button type="button" className="text-button" onClick={()=>void open()}>{label}</button>
    {source&&<dialog ref={dialog} aria-label="출처" className="source-dialog" onCancel={()=>setSource(null)}><div className="subheading"><strong>출처 · v{source.ref.version} {source.status==='changed'?'· 변경됨':source.status==='deleted'?'· 삭제됨':''}</strong><button className="icon-button" aria-label="출처 닫기" title="출처 닫기" onClick={()=>setSource(null)}><Icon name="close"/></button></div>
      {source.ref.kind==='transcript'&&source.open_url?<PlaybackAudio controls src={source.open_url} onLoadedMetadata={e=>{e.currentTarget.currentTime=source.seek_seconds||0;}} onTimeUpdate={e=>{if(source.end_seconds!==null&&e.currentTarget.currentTime>=source.end_seconds)e.currentTarget.pause();}} onPlay={e=>{if(source.end_seconds!==null&&e.currentTarget.currentTime>=source.end_seconds)e.currentTarget.currentTime=source.seek_seconds||0;}} onError={()=>setError('원음을 재생할 수 없습니다')}/>:null}
      <SourceImage source={source}/>
      {source.ref.kind==='web'&&<p>{source.title||'웹 참고'}{source.retrieved_at?' · 조회 '+new Date(source.retrieved_at).toLocaleString('ko-KR'):''}</p>}
      <pre className="source-text">{source.text_snapshot}</pre>
      {source.open_url&&source.ref.kind!=='transcript'&&<a href={source.open_url} target="_blank" rel="noopener noreferrer">원본 열기</a>}
      {source.original_status==='missing'&&<p>원음·원본 없음</p>}
    </dialog>}
    {error&&<span role="alert">{error}</span>}
  </span>;
}
