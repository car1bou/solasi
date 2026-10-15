import json,unittest
from unittest.mock import AsyncMock,patch
from tests import test_answers
from lecture_study.models import Evidence,SourceRef,ProviderResult
from lecture_study.outputs import summary_parts,output_messages,check_budget,SUMMARY_SCHEMA,SUMMARY_INSTRUCTION,summarize_session
from lecture_study.answers import evidence_schema,freeze_request
from lecture_study.materials import save_note
from lecture_study.jobs import submit_job

class ContextSummaryTests(unittest.IsolatedAsyncioTestCase):
    setUp=test_answers.AnswerTests.setUp

    def test_adjacent_transcripts_share_one_context_part(self):
        request=self.request.model_copy(update={'kind':'summary'})
        evidence=[Evidence(ref=SourceRef(id='r'+str(n),kind='transcript',session_id=self.sid,start_ms=n*3000,end_ms=(n+1)*3000),text='금요일 네 대는 제안이고 월요일 세 대로 정정했지만 미확정입니다.',label='전사') for n in range(8)]
        parts=summary_parts(request,evidence)
        self.assertEqual(len(parts),1)
        self.assertEqual([e.ref.id for e in parts[0]],[e.ref.id for e in evidence])

    def test_escaped_large_source_is_split_without_budget_overflow(self):
        request=self.request.model_copy(update={'kind':'summary'})
        original=Evidence(ref=self.ref,text='"\n한국어"'*2000,label='원문')
        parts=summary_parts(request,[original])
        self.assertEqual(''.join(e.text for part in parts for e in part),original.text)
        for part in parts:check_budget(request.provider,output_messages(request,part,SUMMARY_INSTRUCTION),evidence_schema(SUMMARY_SCHEMA,part))

    async def test_processing_coverage_is_distinct_from_selected_citations(self):
        other=save_note(self.db,self.sid,'아 네 알겠습니다.')
        request=self.request.model_copy(update={'kind':'summary','prompt':'핵심 정의 요약'})
        evidence=[Evidence(ref=self.ref,text='프로세스는 실행 중인 프로그램입니다.',label='정의'),Evidence(ref=other,text='아 네 알겠습니다.',label='맞장구')]
        frozen={'request':request.model_dump(),'evidence':[e.model_dump()for e in evidence],'summary_parts':[[e.model_dump()for e in evidence]],'summary_policy':'context-v1','cutoff_ms':None,'warning':'','web_status':{'status':'off'}};job=submit_job(self.db,self.sid,'ai',frozen)
        response=ProviderResult(text=json.dumps({'sections':[{'title':'정의','text':'프로세스는 실행 중인 프로그램이다.','evidence_ids':['s1']}]}),model='test',usage={},elapsed_ms=1)
        with patch('lecture_study.outputs.generate',new=AsyncMock(return_value=response))as generated:
            result=await summarize_session(self.db,frozen,job['id'])
        self.assertEqual(generated.await_count,1)
        self.assertEqual(set(result.body['covered_source_ids']),{self.ref.id,other.id})
        self.assertEqual(result.body['cited_source_ids'],[self.ref.id])
        self.assertEqual(len(result.body['part_coverage']),1)

    async def test_selective_merge_rejects_an_unprovided_source(self):
        from lecture_study.merging import merge_generated
        other=save_note(self.db,self.sid,'별도 원문')
        request=self.request.model_copy(update={'kind':'summary'})
        evidence=[Evidence(ref=self.ref,text='프로세스는 실행 중인 프로그램입니다.',label='정의'),Evidence(ref=other,text='별도 원문',label='별도')]
        frozen={'request':request.model_dump(),'evidence':[e.model_dump()for e in evidence],'summary_policy':'context-v1'};job=submit_job(self.db,self.sid,'ai',frozen)
        piece={'sections':[{'title':'정의','text':'프로그램','evidence_ids':[self.ref.id]}]}
        bad=ProviderResult(text=json.dumps({'sections':[{'title':'가짜','text':'가짜','evidence_ids':['s2']}]}),model='test',usage={},elapsed_ms=1)
        with patch('lecture_study.outputs.generate',new=AsyncMock(return_value=bad)):
            with self.assertRaisesRegex(ValueError,'근거'):await merge_generated(self.db,frozen,job['id'],[piece,piece],'summary')
        self.assertEqual(self.db.execute('SELECT count(*) FROM artifact_parts').fetchone()[0],0)

    async def test_new_request_freezes_the_summary_policy(self):
        frozen=await freeze_request(self.db,self.request.model_copy(update={'kind':'summary'}))
        self.assertEqual(frozen.get('summary_policy'),'context-v1')

    async def test_instruction_only_part_can_be_empty_without_inventing_summary(self):
        from lecture_study.materials import save_note
        from lecture_study.models import Evidence
        note=save_note(self.db,self.sid,'원문과 대조하며 도입부를 정리한다.')
        request=self.request.model_copy(update={'kind':'summary'})
        items=[Evidence(ref=self.ref,text='프로세스는 실행 중인 프로그램입니다.',label='사실'),Evidence(ref=note,text='원문과 대조하며 도입부를 정리한다.',label='메모')]
        frozen={'request':request.model_dump(),'evidence':[e.model_dump()for e in items],'summary_parts':[[e.model_dump()]for e in items],'summary_policy':'context-v1','allow_empty_summary_parts':True,'cutoff_ms':None,'warning':''};job=submit_job(self.db,self.sid,'ai',frozen)
        generated=AsyncMock(side_effect=[ProviderResult(text=json.dumps({'sections':[{'title':'정의','text':'실행 중인 프로그램','evidence_ids':['s1']}]}),model='test',usage={},elapsed_ms=1),ProviderResult(text='{"sections":[]}',model='test',usage={},elapsed_ms=1)])
        with patch('lecture_study.outputs.generate',new=generated):saved=await summarize_session(self.db,frozen,job['id'])
        self.assertEqual(generated.await_count,2);self.assertEqual(saved.body['cited_source_ids'],[self.ref.id]);self.assertEqual(len(saved.body['covered_source_ids']),2)
        from lecture_study.outputs import cached_summary_parts
        self.assertEqual(cached_summary_parts(self.db,job['id'])['parts'][1]['sections'],[])

    def test_known_side_and_quantity_target_mismatch_warns_without_rewriting(self):
        from lecture_study.outputs import summary_warnings
        evidence=[Evidence(ref=self.ref,text='왼손 엄지손가락 손톱 밑을 찔렀습니다. 혼인한 지 7에서 8년입니다.',label='원문')]
        body={'sections':[{'title':'오류','text':'오른손을 찔렀고 체온이 7~8년 낮아졌습니다.','evidence_ids':[self.ref.id]}]}
        warnings=summary_warnings(body,evidence);self.assertEqual(len(warnings),2);self.assertEqual(body['sections'][0]['text'],'오른손을 찔렀고 체온이 7~8년 낮아졌습니다.')
        self.assertEqual(summary_warnings({'sections':[{'title':'근거','text':'왼손을 찔렀다. 혼인 기간은 7~8년이다.','evidence_ids':[self.ref.id]}]},evidence),[])

    async def test_transcript_part_cannot_silently_be_empty(self):
        ref=self.ref.model_copy(update={'kind':'transcript','start_ms':0,'end_ms':1000})
        with self.db:self.db.execute('UPDATE sources SET ref=? WHERE id=?',(ref.model_dump_json(),ref.id))
        request=self.request.model_copy(update={'kind':'summary'})
        evidence=Evidence(ref=ref,text='프로세스는 실행 중인 프로그램입니다.',label='전사')
        frozen={'request':request.model_dump(),'evidence':[evidence.model_dump()],'summary_parts':[[evidence.model_dump()]],'summary_policy':'context-v1','allow_empty_summary_parts':True,'cutoff_ms':1000,'warning':''}
        job=submit_job(self.db,self.sid,'ai',frozen)
        with patch('lecture_study.outputs.generate',new=AsyncMock(return_value=ProviderResult(text='{"sections":[]}',model='test',usage={},elapsed_ms=1))):
            with self.assertRaisesRegex(ValueError,'형식'):await summarize_session(self.db,frozen,job['id'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM artifact_parts WHERE job_id=?',(job['id'],)).fetchone()[0],0)

    def test_smaller_output_reservation_leaves_room_for_merge_input(self):
        request=self.request.model_copy(update={'kind':'summary'})
        messages=[{'role':'user','content':'x'*5000}]
        with self.assertRaisesRegex(ValueError,'예산'):check_budget(request.provider,messages,{})
        check_budget(request.provider,messages,{},output_limit=2048)

    def test_generated_inline_citation_cleanup_preserves_source_text_and_model_body(self):
        from lecture_study.outputs import clean_summary_citations
        body={'sections':[{'title':'내용','text':'배열 [s1, s2]를 쓴다. 다른 생성 설명 [s52, l113, s54].','evidence_ids':[self.ref.id]}]}
        original=json.dumps(body,ensure_ascii=False)
        evidence=[Evidence(ref=self.ref,text='변수 S1과 s2를 배열로 쓴다.',label='원문')]
        cleaned=clean_summary_citations(body,evidence)
        self.assertEqual(cleaned['sections'][0]['text'],'배열 [s1, s2]를 쓴다. 다른 생성 설명 .')
        self.assertEqual(json.dumps(body,ensure_ascii=False),original)
        self.assertEqual(cleaned['sections'][0]['evidence_ids'],[self.ref.id])

    def test_inline_citations_only_cannot_be_saved_as_summary_text(self):
        from lecture_study.outputs import clean_summary_citations
        body={'sections':[{'title':'빈 내용','text':'[s99]','evidence_ids':[self.ref.id]}]}
        with self.assertRaisesRegex(ValueError,'비어'):clean_summary_citations(body,[Evidence(ref=self.ref,text='원문',label='원문')])
