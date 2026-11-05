import React from 'react';
import type {Asset} from './types';

export default function MaterialRecovery({asset,busy,onCheck,onReconnect,onExtract}:{asset:Asset;busy:boolean;onCheck:()=>void;onReconnect:()=>void;onExtract:()=>void}){
 const unavailable=['missing','denied'].includes(asset.source_status),changed=asset.source_status==='changed',stale=asset.status==='stale';
 if(!unavailable&&!changed&&!stale)return null;
 return <div className="material-recovery" role="status"><strong>{asset.source_status==='missing'?'원본 파일 없음':asset.source_status==='denied'?'원본 접근 권한 필요':changed?'원본 변경':'검색용 원문 갱신 필요'} · {asset.filename}</strong><p>{unavailable?'저장된 메모·필기와 과거 출처는 보존됩니다. 같은 내용의 원본 파일 하나를 다시 선택하세요.':changed?'원본을 확인하세요. 내용이 달라지면 이전 메모·필기는 보존되며 새 원본 위에는 표시하지 않습니다.':'페이지 보기와 필기는 사용할 수 있습니다. 검색·질문에 새 내용을 사용하려면 재추출하세요.'}</p><div className="actions">{unavailable&&<button disabled={busy} onClick={onReconnect}>원본 다시 찾기</button>}<button disabled={busy} onClick={onCheck}>{changed?'원본 확인':'다시 확인'}</button>{!unavailable&&!asset.handwritten&&<button disabled={busy} onClick={onExtract}>재추출</button>}</div></div>;
}

export function MaterialError({message}:{message:string}){
 if(message.startsWith('원본 파일 접근·내용을 확인하세요:'))return <details className="material-error-details"><summary>원본 파일을 열 수 없습니다 · 자세히</summary><p>{message}</p></details>;
 return <p role="alert" className="notebook-error">{message}</p>;
}
