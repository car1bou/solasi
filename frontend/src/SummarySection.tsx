import React from 'react';
import SourceLink from './SourceLink';
import type {Evidence} from './types';

export type SummarySectionData={title:string;text:string;evidence_ids:string[];subject?:string;event_type?:string;review_required?:boolean;quotes?:{text:string;evidence_ids:string[]}[]};
const labels:Record<string,string>={fact:'원문상 진술',hypothesis:'가정',condition:'조건',example:'예시',expectation:'기대',proposal:'제안',decision:'결정',unresolved:'미결',unclear:'불명확'};
export default function SummarySection({section,evidence}:{section:SummarySectionData;evidence:Evidence[]}){
  const source=(id:string)=><SourceLink key={id} id={id} label={evidence.find(e=>e.ref.id===id)?.label||'원문'}/>;
  return <section><h4>{section.review_required?'원문 발췌':section.title}</h4>{section.review_required?<p>원문 발췌 · 생성 해석 확인 필요</p>:section.event_type&&<p>{section.subject+' · '+(labels[section.event_type]||section.event_type)}</p>}<pre className="source-text">{section.text}</pre>{section.quotes?<details><summary>원문 근거</summary>{section.quotes.map((q,i)=><blockquote key={i}><pre className="source-text">{q.text}</pre>{q.evidence_ids.map(source)}</blockquote>)}</details>:section.evidence_ids.map(source)}</section>;
}
