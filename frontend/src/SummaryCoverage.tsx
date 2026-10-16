import React from 'react';
import SourceLink from './SourceLink';
import SummarySection from './SummarySection';
import type {Artifact} from './QuestionView';

export default function SummaryCoverage({saved}:{saved:Artifact}){
  const {body,evidence}=saved,excerpt=body.summary_format==='excerpts-v1';
  return <>{body.covered_source_ids&&<p>처리한 원문 {body.covered_source_ids.length}개 · 최종 인용 {body.cited_source_ids?.length??body.covered_source_ids.length}개</p>}
    {(body.merged||!!body.selection_incomplete_parts?.length)&&<p>{excerpt?'핵심 구간 선택 확인 필요':body.selection_incomplete_parts?.length?'최종 선택 불완전 · 누락한 구간 요약을 함께 표시':'구간 요약 처리 완료'}{!excerpt&&typeof body.merge_steps==='number'?' · '+body.merge_steps+'회':''}</p>}
    {!!body.unquoted_sources?.length&&<details><summary>직접 인용하지 않은 원문 {body.unquoted_sources.length}개 · 누락 여부 확인</summary>{body.unquoted_sources.map((q,i)=><blockquote key={i}><pre className="source-text">{q.text}</pre>{q.evidence_ids.map(id=><SourceLink key={id} id={id} label={evidence.find(e=>e.ref.id===id)?.label||'원문'}/>)}</blockquote>)}</details>}
    {body.part_sections&&<details><summary>원래 구간 요약</summary>{body.part_sections.map((s,i)=><SummarySection key={i} section={s} evidence={evidence} excerpt={excerpt}/>)}</details>}
  </>;
}
