import json,unittest
from unittest.mock import AsyncMock,patch
from lecture_study.models import Evidence,SourceRef,ProviderResult
from tests import test_answers
from lecture_study.jobs import submit_job

class GroundingTests(unittest.TestCase):
    def source(self,i,text):return Evidence(ref=SourceRef(id='s'+str(i),kind='transcript',session_id='session',start_ms=i*1000,end_ms=(i+1)*1000),text=text,label='전사')
    def test_hypothesis_and_adjacent_health_context_are_preserved_as_quotes(self):
        from lecture_study.summary_grounding import ground_sections
        evidence=[self.source(i,t)for i,t in enumerate(['절대 일어나서는 안 되지만','부모님이 이렇게','돌아가셨을 때','혼자 남는다 생각하니까','예 건강하시죠'])]
        body={'sections':[{'title':'부모 상실','text':'부모님이 돌아가셔서 혼자 남았다.','subject':'부모님','event_type':'fact','evidence_ids':['s2']}]}
        result=ground_sections(body,evidence)
        section=result['sections'][0]
        self.assertTrue(section['review_required']);self.assertEqual(section['event_type'],'hypothesis')
        self.assertNotIn('혼자 남았다',section['text']);self.assertIn('절대 일어나서는 안 되지만',section['text']);self.assertIn('예 건강하시죠',section['text'])
        self.assertEqual(evidence[2].text,'돌아가셨을 때')
    def test_unsupported_subject_and_fragment_do_not_create_a_complete_event(self):
        from lecture_study.summary_grounding import ground_sections
        evidence=[self.source(0,'어느 날 새벽.')]
        section=ground_sections({'sections':[{'title':'화해','text':'아내와 남편은 화해했다.','subject':'아내와 남편','event_type':'fact','evidence_ids':['s0']}]},evidence)['sections'][0]
        self.assertTrue(section['review_required']);self.assertEqual(section['text'],'어느 날 새벽.');self.assertEqual(section['subject'],'불명확')
    def test_server_quotes_exact_source_instead_of_accepting_generated_quote_text(self):
        from lecture_study.summary_grounding import ground_sections
        evidence=[self.source(0,'아버지는 영등포 물레동 출신입니다.')]
        result=ground_sections({'sections':[{'title':'출생지','text':'아버지는 영등포 물레동 출신이다.','subject':'아버지','event_type':'fact','evidence_ids':['s0']}]},evidence)
        self.assertEqual(result['sections'][0]['quotes'][0]['text'],evidence[0].text);self.assertFalse(result['sections'][0]['review_required'])
        with self.assertRaisesRegex(ValueError,'근거'):ground_sections({'sections':[{'title':'가짜','text':'설명','subject':'아버지','event_type':'fact','evidence_ids':['unknown']}]},evidence)

class GroundedMergeTests(unittest.IsolatedAsyncioTestCase):
    setUp=test_answers.AnswerTests.setUp
    async def test_merge_retries_once_then_keeps_missing_tail_and_never_rewrites_items(self):
        from lecture_study.summary_grounding import merge_grounded
        from lecture_study.materials import save_note
        other=save_note(self.db,self.sid,'후반 할멈은 문을 나가 버린다.')
        evidence=[Evidence(ref=self.ref,text='프로세스는 실행 중인 프로그램입니다.',label='앞'),Evidence(ref=other,text='후반 할멈은 문을 나가 버린다.',label='뒤')]
        request=self.request.model_copy(update={'kind':'summary'})
        frozen={'request':request.model_dump(),'evidence':[e.model_dump()for e in evidence],'summary_grounding':'quotes-v1','summary_selection_limit':1}
        job=submit_job(self.db,self.sid,'ai',frozen)
        pieces=[{'sections':[{'title':str(i),'text':e.text,'subject':'원문','event_type':'fact','review_required':False,'quotes':[{'text':e.text,'evidence_ids':[e.ref.id]}],'evidence_ids':[e.ref.id]}]}for i,e in enumerate(evidence)]
        generated=AsyncMock(return_value=ProviderResult(text=json.dumps({'selected_ids':['p0:0']}),model='test',usage={},elapsed_ms=1))
        with patch('lecture_study.outputs.generate',new=generated):body,infos=await merge_grounded(self.db,frozen,job['id'],pieces)
        self.assertEqual(generated.await_count,2);self.assertEqual(body['sections'],[p['sections'][0]for p in pieces]);self.assertEqual(body['selection_incomplete_parts'],[1])
        self.assertIn('원문',generated.call_args.args[1][0]['content'])
        sent=json.loads(generated.call_args.args[1][1]['content'])
        self.assertTrue(all('section'not in item and 'quotes'not in item and 'evidence_ids'not in item for item in sent['candidates'].values()))
        with patch('lecture_study.outputs.generate',new=AsyncMock(side_effect=AssertionError('cached selection must not run'))):again,_=await merge_grounded(self.db,frozen,job['id'],pieces)
        self.assertEqual(again,body)
    async def test_short_summary_keeps_all_grounded_items_without_an_extra_model_call(self):
        from lecture_study.summary_grounding import merge_grounded
        frozen={'request':self.request.model_copy(update={'kind':'summary'}).model_dump(),'evidence':[Evidence(ref=self.ref,text='프로세스는 실행 중인 프로그램입니다.',label='원문').model_dump()],'summary_grounding':'quotes-v1'};job=submit_job(self.db,self.sid,'ai',frozen)
        piece={'sections':[{'title':'정의','text':'정의','subject':'불명확','event_type':'unclear','review_required':True,'quotes':[{'text':'정의','evidence_ids':[self.ref.id]}],'evidence_ids':[self.ref.id]}]}
        with patch('lecture_study.outputs.generate',new=AsyncMock(side_effect=AssertionError('unnecessary generation'))):body,infos=await merge_grounded(self.db,frozen,job['id'],[piece])
        self.assertEqual(body['sections'],piece['sections']);self.assertEqual(infos,[])

class LectureAndMeetingTests(unittest.TestCase):
    source=GroundingTests.source
    def test_clear_lecture_assumption_and_example_are_not_uncertain(self):
        from lecture_study.summary_grounding import ground_sections
        for state,text in [('condition','마찰이 없다고 가정하면 모형의 결론을 적용한다.'),('example','행렬 A는 설명을 위한 예시이다.')]:
            subject='마찰' if state=='condition' else '행렬 A'
            section=ground_sections({'sections':[{'title':'설명','text':text,'subject':subject,'event_type':state,'evidence_ids':['s0']}]},[self.source(0,text)])['sections'][0]
            self.assertFalse(section['review_required']);self.assertEqual(section['text'],text)
    def test_meeting_proposal_cannot_become_an_assigned_decision(self):
        from lecture_study.summary_grounding import ground_sections
        source=self.source(0,'김민수는 담당자 후보이며 확정하지 않았습니다.')
        section=ground_sections({'sections':[{'title':'담당 결정','text':'김민수가 담당자로 확정됐다.','subject':'김민수','event_type':'decision','evidence_ids':['s0']}]},[source],mode='meeting')['sections'][0]
        self.assertTrue(section['review_required']);self.assertEqual(section['text'],source.text)


class GroundedDispatchTests(unittest.IsolatedAsyncioTestCase):
    setUp=test_answers.AnswerTests.setUp
    async def test_export_hides_unverified_labels_but_keeps_source_and_original_model_metadata(self):
        from lecture_study.answers import freeze_request
        from lecture_study.outputs import summarize_session,export_markdown
        frozen=await freeze_request(self.db,self.request.model_copy(update={'kind':'summary'}));job=submit_job(self.db,self.sid,'ai',frozen)
        item={'title':'해석','text':'프로세스가 실행된다.','subject_quote':'프로세스는 실행 중인 프로그램입니다.','subject_source_id':'s1','event_type':'hypothesis','evidence_ids':['s1']}
        result=ProviderResult(text=json.dumps({'sections':[item]}),model='test',usage={},elapsed_ms=1)
        with patch('lecture_study.outputs.generate',new=AsyncMock(return_value=result)):saved=await summarize_session(self.db,frozen,job['id'])
        markdown=export_markdown(self.db,saved.id)
        self.assertIn('원문 발췌 · 생성 해석 확인 필요',markdown);self.assertIn('프로세스는 실행 중인 프로그램입니다.',markdown)
        self.assertNotIn('주어:',markdown);self.assertNotIn('가정·조건',markdown)
        from lecture_study.answers import get_artifact
        self.assertEqual(get_artifact(self.db,saved.id)['metadata']['part_metadata'][0]['unreviewed_body']['sections'][0],item)
    async def test_new_request_schema_source_quotes_cache_and_export(self):
        from lecture_study.answers import freeze_request
        from lecture_study.outputs import summarize_session,cached_summary_parts,export_markdown
        frozen=await freeze_request(self.db,self.request.model_copy(update={'kind':'summary'}))
        self.assertEqual(frozen['summary_grounding'],'quotes-v1');self.assertEqual(frozen['summary_mode'],'lecture')
        job=submit_job(self.db,self.sid,'ai',frozen)
        async def generated(config,messages,images,schema,**kwargs):
            self.assertIn('subject_quote',schema['properties']['sections']['items']['required'])
            return ProviderResult(text=json.dumps({'sections':[{'title':'정의','text':'프로세스는 실행 중인 프로그램이다.','subject_quote':'프로세스','subject_source_id':'s1','event_type':'fact','evidence_ids':['s1']}]}),model='test',usage={},elapsed_ms=1)
        with patch('lecture_study.outputs.generate',new=AsyncMock(side_effect=generated))as generate:
            saved=await summarize_session(self.db,frozen,job['id']);again=await summarize_session(self.db,frozen,job['id'])
        self.assertEqual(generate.await_count,1);self.assertEqual(again.body,saved.body)
        section=saved.body['sections'][0];self.assertFalse(section['review_required']);self.assertEqual(section['quotes'][0]['text'],'프로세스는 실행 중인 프로그램입니다.')
        self.assertEqual(cached_summary_parts(self.db,job['id'])['parts'][0]['sections'][0],section)
        self.assertIn('주어: 프로세스',export_markdown(self.db,saved.id));self.assertIn('> 프로세스는 실행 중인 프로그램입니다.',export_markdown(self.db,saved.id))
        body=saved.body|{'selection_incomplete_parts':[0]}
        with self.db:self.db.execute('UPDATE artifacts SET body=? WHERE id=?',(json.dumps(body),saved.id))
        self.assertIn('최종 선택에서 누락한 구간',export_markdown(self.db,saved.id))


class ContextGuardTests(unittest.TestCase):
    source=GroundingTests.source
    def test_clear_condition_stays_clear_even_when_model_labels_it_fact(self):
        from lecture_study.summary_grounding import ground_sections
        text='마찰이 없다고 가정하면 모형의 결론을 적용한다.'
        section=ground_sections({'sections':[{'title':'조건','text':text,'subject':'마찰','event_type':'fact','evidence_ids':['s0']}]},[self.source(0,text)])['sections'][0]
        self.assertFalse(section['review_required']);self.assertEqual(section['event_type'],'condition')
    def test_nearby_proposal_does_not_overrule_a_separate_explicit_decision(self):
        from lecture_study.summary_grounding import ground_sections
        evidence=[self.source(0,'김민수는 담당자 후보이며 확정하지 않았습니다.'),self.source(1,'이서연이 담당하기로 확정했습니다.')]
        section=ground_sections({'sections':[{'title':'담당','text':'이서연이 담당하기로 확정했다.','subject':'이서연','event_type':'decision','evidence_ids':['s1']}]},evidence,mode='meeting')['sections'][0]
        self.assertFalse(section['review_required']);self.assertEqual(section['event_type'],'decision')

class ReviewBoundaryTests(unittest.TestCase):
    source=GroundingTests.source
    def test_clear_condition_and_demonstration_do_not_need_a_magic_word(self):
        from lecture_study.summary_grounding import ground_sections
        for state,text,subject in [('condition','입력이 0일 때만 실행한다.','입력'),('example','행렬 A에 2를 대입해 계산해 보자.','행렬 A')]:
            section=ground_sections({'sections':[{'title':'설명','text':text,'subject':subject,'event_type':state,'evidence_ids':['s0']}]},[self.source(0,text)])['sections'][0]
            self.assertFalse(section['review_required']);self.assertEqual(section['text'],text)
    def test_nearby_person_does_not_support_another_persons_action(self):
        from lecture_study.summary_grounding import ground_sections
        evidence=[self.source(0,'김민수는 예산을 보고했다.'),self.source(1,'박영희가 배포를 맡았다.')]
        section=ground_sections({'sections':[{'title':'담당','text':'김민수가 배포를 맡았다.','subject':'김민수','event_type':'fact','evidence_ids':['s1']}]},evidence)['sections'][0]
        self.assertTrue(section['review_required']);self.assertNotIn('김민수가 배포',section['text'])
    def test_single_source_units_keep_middle_and_tail_even_if_map_only_summarizes_start(self):
        from lecture_study.summary_grounding import grounded_units,ground_sections
        original=self.source(0,'처음에는 장비 예산을 설명했다. 중간에는 배치 계획을 변경했다. 마지막에는 계약을 취소했다.')
        units,restore=grounded_units([original],{'s0':'s1'})
        self.assertEqual(len(units),3)
        body=ground_sections({'sections':[{'title':'처음','text':'장비 예산을 설명했다.','subject':'장비 예산','event_type':'fact','evidence_ids':[units[0].ref.id]}]},units)
        self.assertTrue(any('계약을 취소' in s['text']for s in body['sections']));self.assertTrue(any('계획을 변경' in s['text']for s in body['sections']))
        self.assertEqual(set(g for s in body['sections']for g in s['coverage_groups']),{0,1,2});self.assertEqual(set(restore.values()),{'s0'})

class SelectionCoverageTests(unittest.IsolatedAsyncioTestCase):
    setUp=test_answers.AnswerTests.setUp
    async def test_single_part_still_checks_middle_and_tail_selection(self):
        from lecture_study.summary_grounding import merge_grounded
        frozen={'request':self.request.model_copy(update={'kind':'summary'}).model_dump(),'evidence':[Evidence(ref=self.ref,text='프로세스는 실행 중인 프로그램입니다.',label='원문').model_dump()],'summary_grounding':'quotes-v1','summary_selection_limit':1};job=submit_job(self.db,self.sid,'ai',frozen)
        pieces=[{'sections':[{'title':str(i),'text':'구간 '+str(i),'evidence_ids':[self.ref.id],'coverage_groups':[i]}for i in range(3)]}]
        generate=AsyncMock(return_value=ProviderResult(text='{"selected_ids":["p0:0"]}',model='test',usage={},elapsed_ms=1))
        with patch('lecture_study.outputs.generate',new=generate):body,_=await merge_grounded(self.db,frozen,job['id'],pieces)
        self.assertEqual(generate.await_count,2);self.assertEqual(len(body['sections']),3);self.assertEqual(body['selection_incomplete_parts'],[0])
        with self.db:self.db.execute('UPDATE artifact_parts SET body=? WHERE job_id=? AND part_no=-1',(json.dumps({'selected_ids':['p0:0'],'incomplete_parts':[]}),job['id']))
        with self.assertRaises(ValueError):await merge_grounded(self.db,frozen,job['id'],pieces)
    async def test_tokenizer_validation_error_is_not_hidden_as_a_size_fallback(self):
        from lecture_study.summary_grounding import merge_grounded
        frozen={'request':self.request.model_copy(update={'kind':'summary'}).model_dump(),'evidence':[Evidence(ref=self.ref,text='프로세스는 실행 중인 프로그램입니다.',label='원문').model_dump()],'summary_selection_limit':1};job=submit_job(self.db,self.sid,'ai',frozen)
        pieces=[{'sections':[{'title':'제목','text':'내용','evidence_ids':[self.ref.id]}for _ in range(2)]}]
        with patch('lecture_study.outputs.check_budget',side_effect=ValueError('토크나이저가 변경되었습니다')):
            with self.assertRaisesRegex(ValueError,'토크나이저'):await merge_grounded(self.db,frozen,job['id'],pieces)

class EmptyAndDecisionTests(unittest.TestCase):
    source=GroundingTests.source
    def test_empty_map_keeps_substantive_notes(self):
        from lecture_study.summary_grounding import grounded_units,ground_sections
        original=self.source(0,'처음에는 장비 예산을 설명했다. 중간에는 배치 계획을 변경했다. 마지막에는 계약을 취소했다.')
        original=original.model_copy(update={'ref':original.ref.model_copy(update={'kind':'note'})})
        units,_=grounded_units([original],{'s0':'s1'})
        result=ground_sections({'sections':[]},units)
        self.assertEqual({g for s in result['sections']for g in s['coverage_groups']},{0,1,2})
        self.assertIn('계약을 취소',' '.join(s['text']for s in result['sections']))
    def test_clear_writing_request_may_remain_empty(self):
        from lecture_study.summary_grounding import ground_sections
        for text in ('원문과 대조하며 도입부를 정리한다.','인터뷰 답변의 핵심 설명과 정정 내용을 정리하고 원문과 대조한다.'):
            source=self.source(0,text);source=source.model_copy(update={'ref':source.ref.model_copy(update={'kind':'note'})})
            self.assertEqual(ground_sections({'sections':[]},[source])['sections'],[])
    def test_explicit_confirmation_after_review_remains_a_decision(self):
        from lecture_study.summary_grounding import ground_sections
        text='제안을 검토한 뒤 김민수를 담당자로 확정했습니다.'
        result=ground_sections({'sections':[{'title':'담당 확정','text':text,'subject':'김민수','event_type':'decision','evidence_ids':['s0']}]},[self.source(0,text)],mode='meeting')['sections'][0]
        self.assertEqual(result['event_type'],'decision');self.assertFalse(result['review_required'])

    def test_proposal_without_confirmation_cannot_become_decision(self):
        from lecture_study.summary_grounding import ground_sections
        text='김민수가 배포를 맡는 방안을 제안합니다.'
        result=ground_sections({'sections':[{'title':'담당 확정','text':'김민수가 배포를 맡기로 확정했다.','subject':'김민수','event_type':'decision','evidence_ids':['s0']}]},[self.source(0,text)],mode='meeting')['sections'][0]
        self.assertEqual(result['event_type'],'unresolved');self.assertTrue(result['review_required'])
    def test_definition_using_summary_vocabulary_is_not_a_writing_request(self):
        from lecture_study.summary_grounding import ground_sections
        source=self.source(0,'요약은 자료의 원문을 대조하여 내용을 정리하는 기법이다.');source=source.model_copy(update={'ref':source.ref.model_copy(update={'kind':'note'})})
        self.assertTrue(ground_sections({'sections':[]},[source])['sections'])
    def test_explicit_negative_assignment_is_not_a_decision(self):
        from lecture_study.summary_grounding import ground_sections
        for text in ('김민수로 결정하지 않았습니다.','김민수는 담당자가 아닙니다.','김민수와 합의하지 않았습니다.'):
            result=ground_sections({'sections':[{'title':'담당 확정','text':'김민수로 확정했다.','subject':'김민수','event_type':'decision','evidence_ids':['s0']}]},[self.source(0,text)],mode='meeting')['sections'][0]
            self.assertTrue(result['review_required']);self.assertEqual(result['text'],text)

    def test_household_word_is_not_a_hypothetical_cue(self):
        from lecture_study.summary_grounding import ground_sections
        source=self.source(0,'가정에서는 어머니가 요리를 했고 제가 한식 자격증을 땄습니다.')
        result=ground_sections({'sections':[{'title':'가족 요리','text':source.text,'subject':'어머니','event_type':'fact','evidence_ids':['s0']}]},[source])['sections'][0]
        self.assertFalse(result['review_required']);self.assertEqual(result['event_type'],'fact')
    def test_named_subjects_work_statement_is_not_an_empty_writing_request(self):
        from lecture_study.summary_grounding import ground_sections
        source=self.source(0,'자료팀은 원문과 대조하여 회의록을 정리한다.');source=source.model_copy(update={'ref':source.ref.model_copy(update={'kind':'note'})})
        self.assertTrue(ground_sections({'sections':[]},[source])['sections'])

class ProtectedItemTests(unittest.IsolatedAsyncioTestCase):
    setUp=test_answers.AnswerTests.setUp
    async def test_hypotheses_and_review_excerpts_survive_even_with_the_same_coverage_group(self):
        from lecture_study.summary_grounding import merge_grounded
        frozen={'request':self.request.model_copy(update={'kind':'summary'}).model_dump(),'evidence':[Evidence(ref=self.ref,text='프로세스는 실행 중인 프로그램입니다.',label='원문').model_dump()],'summary_selection_limit':1};job=submit_job(self.db,self.sid,'ai',frozen)
        for state,review in [('hypothesis',False),('condition',False),('example',False),('proposal',False),('decision',False),('unresolved',False),('fact',True)]:
            items=[{'title':str(i),'text':str(i),'event_type':state if i==2 else 'fact','review_required':review if i==2 else False,'evidence_ids':[self.ref.id],'coverage_groups':[0]}for i in range(3)]
            generated=AsyncMock(return_value=ProviderResult(text='{"selected_ids":["p0:0"]}',model='test',usage={},elapsed_ms=1))
            with patch('lecture_study.outputs.generate',new=generated):body,_=await merge_grounded(self.db,frozen,job['id'],[{'sections':items}])
            self.assertIn(items[2],body['sections']);self.assertEqual(generated.await_count,1)
            with self.db:self.db.execute('DELETE FROM artifact_parts WHERE job_id=?',(job['id'],))
    async def test_invalid_selection_is_not_success_just_because_protected_items_cover_the_range(self):
        from lecture_study.summary_grounding import merge_grounded
        frozen={'request':self.request.model_copy(update={'kind':'summary'}).model_dump(),'evidence':[Evidence(ref=self.ref,text='프로세스는 실행 중인 프로그램입니다.',label='원문').model_dump()],'summary_selection_limit':1};job=submit_job(self.db,self.sid,'ai',frozen)
        items=[{'title':str(i),'text':str(i),'event_type':'condition'if i==2 else 'fact','review_required':False,'evidence_ids':[self.ref.id],'coverage_groups':[0]}for i in range(3)]
        generate=AsyncMock(return_value=ProviderResult(text='{"selected_ids":["unknown"]}',model='test',usage={},elapsed_ms=1))
        with patch('lecture_study.outputs.generate',new=generate):body,_=await merge_grounded(self.db,frozen,job['id'],[{'sections':items}])
        self.assertEqual(generate.await_count,2);self.assertEqual(body['selection_incomplete_parts'],[0]);self.assertEqual(body['sections'],items)


class ProtectedBudgetTests(unittest.IsolatedAsyncioTestCase):
    setUp=test_answers.AnswerTests.setUp
    async def test_budget_failure_preserves_facts_even_when_protected_items_cover_all_bands(self):
        from lecture_study.summary_grounding import merge_grounded
        frozen={'request':self.request.model_copy(update={'kind':'summary'}).model_dump(),'evidence':[Evidence(ref=self.ref,text='프로세스는 실행 중인 프로그램입니다.',label='원문').model_dump()],'summary_grounding':'quotes-v1','summary_selection_limit':1}
        job=submit_job(self.db,self.sid,'ai',frozen)
        items=[{'title':str(i),'text':'설명','subject':'프로세스','event_type':'condition'if i==0 else'fact','review_required':False,'coverage_groups':[0,1,2],'evidence_ids':[self.ref.id]}for i in range(3)]
        with patch('lecture_study.outputs.check_budget',side_effect=ValueError('입력 예산 초과')),patch('lecture_study.outputs.generate',new=AsyncMock(side_effect=AssertionError('over budget'))):
            body,infos=await merge_grounded(self.db,frozen,job['id'],[{'sections':items}])
        self.assertEqual(body['sections'],items);self.assertEqual(body['selection_incomplete_parts'],[0]);self.assertEqual(infos,[])

class IncrementalSelectionTests(unittest.IsolatedAsyncioTestCase):
    setUp=test_answers.AnswerTests.setUp
    async def test_retry_additions_keep_first_valid_selection_without_false_incomplete_fallback(self):
        from lecture_study.summary_grounding import merge_grounded
        frozen={'request':self.request.model_copy(update={'kind':'summary'}).model_dump(),'evidence':[Evidence(ref=self.ref,text='프로세스는 실행 중인 프로그램입니다.',label='원문').model_dump()],'summary_grounding':'quotes-v1','summary_selection_limit':2}
        job=submit_job(self.db,self.sid,'ai',frozen)
        pieces=[{'sections':[{'title':f'{p}:{i}','text':'설명','subject':'프로세스','event_type':'fact','review_required':False,'coverage_groups':[0],'evidence_ids':[self.ref.id]}for i in range(3)]}for p in range(2)]
        generate=AsyncMock(side_effect=[ProviderResult(text='{"selected_ids":["p0:0"]}',model='test',usage={},elapsed_ms=1),ProviderResult(text='{"selected_ids":["p1:0"]}',model='test',usage={},elapsed_ms=1)])
        with patch('lecture_study.outputs.generate',new=generate):body,_=await merge_grounded(self.db,frozen,job['id'],pieces)
        self.assertEqual(generate.await_count,2);self.assertEqual(body['sections'],[pieces[0]['sections'][0],pieces[1]['sections'][0]]);self.assertEqual(body['selection_incomplete_parts'],[])

class CopiedSubjectTests(unittest.TestCase):
    source=GroundingTests.source
    def test_copied_subject_is_bound_to_its_direct_source_and_other_sources_do_not_repair_it(self):
        from lecture_study.summary_grounding import ground_sections
        evidence=[self.source(0,'어머니는 요리를 합니다.'),self.source(1,'아버지는 등산을 합니다.')]
        body={'sections':[{'title':'요리','text':'어머니는 요리를 한다.','subject_quote':'어머니','subject_source_id':'s0','event_type':'fact','evidence_ids':['s0']}]}
        result=ground_sections(body,evidence,copy_subject=True)['sections'][0]
        self.assertEqual(result['subject'],'어머니');self.assertFalse(result['review_required'])
        body['sections'][0]['subject_source_id']='s1'
        result=ground_sections(body,evidence,copy_subject=True)['sections'][0];self.assertTrue(result['review_required']);self.assertEqual(result['subject'],'불명확')
    def test_copy_schema_and_evidence_enum_keep_old_schema_compatible(self):
        from lecture_study.summary_grounding import grounded_schema
        from lecture_study.answers import evidence_schema
        from lecture_study.outputs import SUMMARY_PART_SCHEMA
        original=grounded_schema(SUMMARY_PART_SCHEMA);copied=evidence_schema(grounded_schema(SUMMARY_PART_SCHEMA,copy_subject=True),[self.source(0,'원문')])
        self.assertIn('subject',original['properties']['sections']['items']['properties']);props=copied['properties']['sections']['items']['properties']
        self.assertNotIn('subject',props);self.assertEqual(props['subject_source_id']['enum'],['','s0']);self.assertEqual(copied['properties']['sections']['maxItems'],8)
    def test_novel_number_in_text_or_title_is_not_a_supported_summary(self):
        from lecture_study.summary_grounding import ground_sections
        source=self.source(0,'모음집 2번 부분을 읽습니다.')
        for title,text in [('소개','모음집 1번 부분을 읽는다.'),('모음집 1번','모음집 2번 부분을 읽는다.')]:
            result=ground_sections({'sections':[{'title':title,'text':text,'subject':'모음집','event_type':'fact','evidence_ids':['s0']}]},[source])['sections'][0]
            self.assertTrue(result['review_required']);self.assertEqual(result['text'],source.text)

class SummaryConsistencyTests(unittest.TestCase):
    source=GroundingTests.source
    def test_another_copied_subject_cannot_leak_into_unrelated_item(self):
        from lecture_study.summary_grounding import ground_sections
        sources=[self.source(0,'예산 120만원은 제안이며 승인하지 않았습니다.'),self.source(1,'김민수는 담당자 후보입니다.')]
        body={'sections':[{'title':'예산','text':'김민수는 예산 120만원을 제안했다.','subject_quote':'예산 120만원','subject_source_id':'s0','event_type':'proposal','evidence_ids':['s0']},{'title':'담당 후보','text':'김민수는 담당자 후보입니다.','subject_quote':'김민수','subject_source_id':'s1','event_type':'proposal','evidence_ids':['s1']}]}
        section=ground_sections(body,sources,copy_subject=True)['sections'][0]
        self.assertTrue(section['review_required']);self.assertNotIn('김민수는 예산',section['text'])
    def test_identical_excerpts_are_removed_but_distinct_event_states_stay(self):
        from lecture_study.summary_grounding import ground_sections
        evidence=[self.source(0,'금요일 배치안은 취소했습니다.')]
        item={'title':'설명','text':'배치안을 취소했다.','subject':'불명확','event_type':'unclear','evidence_ids':['s0']}
        body=ground_sections({'sections':[item,item,item|{'event_type':'condition'}]},evidence)
        self.assertEqual(len(body['sections']),2)
    def test_cached_subject_must_be_supported_unless_an_excerpt_is_marked(self):
        from lecture_study.summary_grounding import checked_grounded
        evidence=[self.source(0,'예산을 검토했습니다.')]
        item={'title':'예산','text':'예산을 검토했다.','subject':'김민수','event_type':'fact','evidence_ids':['s0'],'review_required':False,'quotes':[{'text':evidence[0].text,'evidence_ids':['s0']}]}
        with self.assertRaises(ValueError):checked_grounded({'sections':[item]},evidence)

class InvalidSelectionRetryTests(unittest.IsolatedAsyncioTestCase):
    setUp=test_answers.AnswerTests.setUp
    async def test_invalid_retry_retains_valid_selection_and_falls_back_only_missing_part(self):
        from lecture_study.summary_grounding import merge_grounded
        frozen={'request':self.request.model_copy(update={'kind':'summary'}).model_dump(),'evidence':[Evidence(ref=self.ref,text='프로세스는 실행 중인 프로그램입니다.',label='원문').model_dump()],'summary_selection_limit':2};job=submit_job(self.db,self.sid,'ai',frozen)
        pieces=[{'sections':[{'title':f'{p}:{i}','text':'설명','subject':'프로세스','event_type':'fact','review_required':False,'coverage_groups':[0],'evidence_ids':[self.ref.id]}for i in range(3)]}for p in range(2)]
        generate=AsyncMock(side_effect=[ProviderResult(text='{"selected_ids":["p0:0"]}',model='test',usage={},elapsed_ms=1),ProviderResult(text='{"selected_ids":["unknown"]}',model='test',usage={},elapsed_ms=1)])
        with patch('lecture_study.outputs.generate',new=generate):body,_=await merge_grounded(self.db,frozen,job['id'],pieces)
        self.assertEqual(body['sections'],[pieces[0]['sections'][0],*pieces[1]['sections']]);self.assertEqual(body['selection_incomplete_parts'],[1])

class CopiedSubjectStatementTests(unittest.TestCase):
    source=GroundingTests.source
    def test_copying_a_clause_cannot_validate_an_unrelated_paraphrase(self):
        from lecture_study.summary_grounding import ground_sections
        source=self.source(0,'대신 힘들다고 말하는 거는 아버지가 더 편하죠 어머니는 마음이 아파하시니까')
        item={'title':'부모와 대화','text':'힘든 점은 어머니에게 더 많이 말하지만 아버지에게는 덜 한다.','subject_quote':'대신 힘들다고 말하는 거는','subject_source_id':'s0','event_type':'fact','evidence_ids':['s0']}
        section=ground_sections({'sections':[item]},[source],copy_subject=True)['sections'][0]
        self.assertTrue(section['review_required']);self.assertEqual(section['text'],source.text)
    def test_whitespace_changes_do_not_hide_a_valid_subject(self):
        from lecture_study.summary_grounding import ground_sections
        source=self.source(0,'행렬 A에 2를 대입하여 계산합니다.')
        item={'title':'예시','text':'행렬A에 2를 대입해 계산한다.','subject_quote':'행렬 A','subject_source_id':'s0','event_type':'example','evidence_ids':['s0']}
        self.assertFalse(ground_sections({'sections':[item]},[source],copy_subject=True)['sections'][0]['review_required'])

class InvalidFirstSelectionTests(unittest.IsolatedAsyncioTestCase):
    setUp=test_answers.AnswerTests.setUp
    async def test_no_valid_response_preserves_facts_even_in_a_part_covered_by_protected_items(self):
        from lecture_study.summary_grounding import merge_grounded
        frozen={'request':self.request.model_copy(update={'kind':'summary'}).model_dump(),'evidence':[Evidence(ref=self.ref,text='프로세스는 실행 중인 프로그램입니다.',label='원문').model_dump()],'summary_selection_limit':1};job=submit_job(self.db,self.sid,'ai',frozen)
        pieces=[{'sections':[{'title':f'{p}:{i}','text':'설명','subject':'프로세스','event_type':'condition'if p==0 and i==0 else'fact','review_required':False,'coverage_groups':[0,1,2],'evidence_ids':[self.ref.id]}for i in range(3)]}for p in range(2)]
        generate=AsyncMock(return_value=ProviderResult(text='{"selected_ids":["invalid"]}',model='test',usage={},elapsed_ms=1))
        with patch('lecture_study.outputs.generate',new=generate):body,_=await merge_grounded(self.db,frozen,job['id'],pieces)
        self.assertEqual(generate.await_count,2);self.assertEqual(body['sections'],[s for p in pieces for s in p['sections']]);self.assertEqual(body['selection_incomplete_parts'],[0,1])

class SourceCoverageTests(unittest.TestCase):
    source=GroundingTests.source
    def test_short_statement_and_same_band_late_instruction_remain_separate_excerpts(self):
        from lecture_study.summary_grounding import unquoted_sources
        evidence=[self.source(0,'학생입니다. 설명을 들었습니다.'),self.source(1,'실험을 끝냈습니다. 전원을 끄세요.')]
        sections=[{'quotes':[{'text':'설명을 들었습니다.','evidence_ids':['s0']},{'text':'실험을 끝냈습니다.','evidence_ids':['s1']}]}]
        self.assertEqual(unquoted_sources(sections,evidence),[{'text':'학생입니다.','evidence_ids':['s0']},{'text':'전원을 끄세요.','evidence_ids':['s1']}])
        self.assertEqual(unquoted_sources([{'quotes':[{'text':e.text,'evidence_ids':[e.ref.id]}for e in evidence]}],evidence),[])
    def test_copied_object_must_not_become_an_actor_without_review(self):
        from lecture_study.summary_grounding import ground_sections
        source=self.source(0,'연구원이 실험실을 향하여 걸어갑니다.')
        section=ground_sections({'sections':[{'title':'이동','text':'실험실이 걸어갑니다.','subject_quote':'실험실','subject_source_id':'s0','event_type':'fact','evidence_ids':['s0']}]},[source],copy_subject=True)['sections'][0]
        self.assertTrue(section['review_required']);self.assertEqual(section['text'],source.text)
    def test_legacy_joined_subject_cache_remains_readable_and_new_copy_contract_is_stricter(self):
        from lecture_study.summary_grounding import checked_grounded
        sources=[self.source(0,'부모님'),self.source(1,'어머니는 충청도 출신입니다.')]
        section={'title':'출신지','text':'부모님 어머니는 충청도 출신이다.','subject':'부모님 어머니','event_type':'fact','evidence_ids':['s0','s1'],'review_required':False,'quotes':[{'text':e.text,'evidence_ids':[e.ref.id]}for e in sources]}
        self.assertEqual(checked_grounded({'sections':[section]},sources)['sections'],[section])
        with self.assertRaises(ValueError):checked_grounded({'sections':[section]},sources,copy_subject=True)

class SubjectRoleFollowupTests(unittest.TestCase):
    source=GroundingTests.source
    def check(self,original,generated,subject):
        from lecture_study.summary_grounding import ground_sections
        item={'title':'발언','text':generated,'subject_quote':subject,'subject_source_id':'s0','event_type':'fact','evidence_ids':['s0']}
        return ground_sections({'sections':[item]},[self.source(0,original)],copy_subject=True)['sections'][0]
    def test_explicit_actor_cannot_become_only_the_recipient(self):
        original='김민수는 이서연에게 보고했습니다.'
        section=self.check(original,'이서연은 김민수에게 보고했습니다.','김민수')
        self.assertTrue(section['review_required']);self.assertEqual(section['text'],original)
    def test_person_in_a_spatial_expression_cannot_become_the_actor(self):
        original='어머니 앞에서는 제가 딸 노릇을 했습니다.'
        section=self.check(original,'어머니는 딸 노릇을 했습니다.','어머니')
        self.assertTrue(section['review_required']);self.assertEqual(section['text'],original)
    def test_actor_and_recipient_can_both_remain_in_a_faithful_paraphrase(self):
        section=self.check('김민수는 이서연에게 보고했습니다.','김민수가 이서연에게 보고했다.','김민수')
        self.assertFalse(section['review_required'])
    def test_descriptive_paraphrases_do_not_turn_into_role_reversal_warnings(self):
        for original,generated,subject in [('서울은 대한민국의 수도입니다.','대한민국의 수도는 서울로 알려져 있습니다.','서울'),('김민수는 문서 작성자입니다.','문서는 김민수의 작품입니다.','김민수')]:
            with self.subTest(original=original):self.assertFalse(self.check(original,generated,subject)['review_required'])
    def test_a_title_cannot_repair_an_actor_swapped_with_the_recipient_in_the_body(self):
        from lecture_study.summary_grounding import ground_sections
        original='김민수는 이서연에게 보고했습니다.'
        item={'title':'김민수는 보고했습니다','text':'이서연은 김민수에게 보고했습니다.','subject_quote':'김민수','subject_source_id':'s0','event_type':'fact','evidence_ids':['s0']}
        self.assertTrue(ground_sections({'sections':[item]},[self.source(0,original)],copy_subject=True)['sections'][0]['review_required'])
    def test_opposite_assumption_cannot_borrow_negation_from_an_unrelated_clause(self):
        from lecture_study.summary_grounding import ground_sections
        original='마찰이 없다고 가정하면 에너지가 보존됩니다. 실제 장치에 마찰이 없다는 뜻은 아닙니다.'
        item={'title':'보존 조건','text':'마찰이 있다고 가정하면 에너지가 보존됩니다. 실제 장치와 같다는 뜻은 아닙니다.','subject_quote':'마찰','subject_source_id':'s0','event_type':'condition','evidence_ids':['s0']}
        section=ground_sections({'sections':[item]},[self.source(0,original)],copy_subject=True)['sections'][0]
        self.assertTrue(section['review_required']);self.assertEqual(section['text'],original)
        item['text']='마찰이 있다면 에너지가 보존됩니다. 실제 장치와 같다는 뜻은 아닙니다.'
        self.assertTrue(ground_sections({'sections':[item]},[self.source(0,original)],copy_subject=True)['sections'][0]['review_required'])

class SubjectWhitespaceTests(unittest.TestCase):
    source=GroundingTests.source
    def test_only_unique_whitespace_differences_are_restored_from_the_direct_source(self):
        from lecture_study.summary_grounding import copied_span
        self.assertEqual(copied_span('행렬 A 에 2 를','행렬 A에 2를 대입합니다.'),'행렬 A에 2를')
        self.assertEqual(copied_span('세포 막','세포\n막은 경계입니다.'),'세포\n막')
        for quote,source in [('행렬 B','행렬 A'),('세포가','세포는'),('A 2','A1 2'),('세포 막','세포막과 세포 막'),('가가','가가가')]:
            expected=quote if quote in source else ''
            self.assertEqual(copied_span(quote,source),expected)
        self.assertEqual(copied_span('세 포','세포, 세포'),'')
    def test_restored_subject_is_exact_and_does_not_change_source(self):
        from lecture_study.summary_grounding import ground_sections
        source=self.source(0,'행렬 A에 2를 대입하는 예시입니다.')
        item={'title':'계산 예시','text':'행렬 A에 2를 대입하는 예시이다.','subject_quote':'행렬 A 에','subject_source_id':'s0','event_type':'example','evidence_ids':['s0']}
        section=ground_sections({'sections':[item]},[source],copy_subject=True)['sections'][0]
        self.assertEqual(section['subject'],'행렬 A에');self.assertFalse(section['review_required']);self.assertEqual(section['quotes'][0]['text'],source.text)

class ModalityScopeTests(unittest.TestCase):
    source=GroundingTests.source
    def run_item(self,sources,text,state='fact',ids=None):
        from lecture_study.summary_grounding import ground_sections
        item={'title':'발언','text':text,'subject':'김민수','event_type':state,'evidence_ids':ids or ['s0']}
        return ground_sections({'sections':[item]},sources)['sections'][0]
    def test_real_memory_is_not_reclassified_from_thinking_word_alone(self):
        text='김민수는 어제 있었던 일을 생각하니까 마음이 아프다고 말했다.'
        section=self.run_item([self.source(0,text)],text)
        self.assertEqual(section['event_type'],'fact');self.assertFalse(section['review_required'])
    def test_neighboring_condition_does_not_infect_a_complete_real_event(self):
        sources=[self.source(0,'만약 서버가 멈추면 복구를 검토합니다.'),self.source(1,'회의를 마쳤을 때 김민수가 담당자로 확정됐습니다.')]
        section=self.run_item(sources,'회의를 마친 뒤 김민수가 담당자로 확정됐다.',ids=['s1'])
        self.assertEqual(section['event_type'],'fact');self.assertFalse(section['review_required'])
    def test_condition_label_cannot_validate_a_dropped_premise(self):
        from lecture_study.summary_grounding import ground_sections
        source=self.source(0,'마찰이 없다고 가정하면 에너지가 보존됩니다. 실제 마찰이 없다고 단정하는 뜻은 아닙니다.')
        item={'title':'모형','text':'마찰 유무에 따라 에너지가 보존되며 실제 장치는 마찰이 존재함을 명시합니다.','subject':'마찰','event_type':'condition','evidence_ids':['s0']}
        section=ground_sections({'sections':[item]},[source])['sections'][0]
        self.assertTrue(section['review_required']);self.assertEqual(section['event_type'],'condition');self.assertEqual(section['text'],source.text)
    def test_clear_condition_and_negation_remain_clear_when_actually_preserved(self):
        text='김민수는 입력이 0이면 실행하고 1이면 실행하지 않는다고 설명했습니다.'
        section=self.run_item([self.source(0,text)],text,state='condition')
        self.assertFalse(section['review_required']);self.assertEqual(section['event_type'],'condition')

    def test_meeting_fact_label_cannot_bypass_candidate_owner_check(self):
        from lecture_study.summary_grounding import ground_sections
        source=self.source(0,'김민수는 담당자 후보이며 확정하지 않았습니다.')
        item={'title':'담당','text':'김민수가 담당하기로 확정했습니다.','subject':'김민수','event_type':'fact','evidence_ids':['s0']}
        section=ground_sections({'sections':[item]},[source],'meeting')['sections'][0]
        self.assertTrue(section['review_required']);self.assertEqual(section['event_type'],'unresolved');self.assertEqual(section['text'],source.text)

    def test_ramen_noun_is_not_a_condition(self):
        text='김민수는 라면을 먹었습니다.'
        section=self.run_item([self.source(0,text)],text)
        self.assertEqual(section['event_type'],'fact');self.assertFalse(section['review_required'])
    def test_latin_and_numeric_condition_values_keep_their_premise(self):
        from lecture_study.summary_grounding import ground_sections
        for value in ('A','1'):
            source=self.source(0,'입력이 '+value+'라면 실행합니다.')
            item={'title':'입력','text':'입력이 '+value+'입니다. 실행합니다.','subject':'입력','event_type':'fact','evidence_ids':['s0']}
            self.assertTrue(ground_sections({'sections':[item]},[source])['sections'][0]['review_required'])

    def test_equivalent_negative_meeting_word_is_not_lost_qualification(self):
        section=self.run_item([self.source(0,'김민수는 회의에 참석하지 않았습니다.')],'김민수는 회의에 불참했습니다.')
        self.assertFalse(section['review_required'])
    def test_bare_owner_claim_and_title_cannot_assign_a_candidate(self):
        from lecture_study.summary_grounding import ground_sections
        source=self.source(0,'김민수는 배포 담당 후보입니다.')
        for title,text in [('담당','김민수는 배포 담당자입니다.'),('김민수 담당자로 확정했습니다','김민수는 배포 담당 후보입니다.')]:
            item={'title':title,'text':text,'subject':'김민수','event_type':'fact','evidence_ids':['s0']}
            self.assertTrue(ground_sections({'sections':[item]},[source],'meeting')['sections'][0]['review_required'])
    def test_explicit_same_actor_late_confirmation_is_preserved(self):
        from lecture_study.summary_grounding import ground_sections
        source=self.source(0,'김민수는 담당 후보였습니다. 김민수는 오늘 담당자로 확정됐습니다.')
        item={'title':'담당 확정','text':'김민수는 오늘 담당자로 확정됐습니다.','subject':'김민수','event_type':'decision','evidence_ids':['s0']}
        section=ground_sections({'sections':[item]},[source],'meeting')['sections'][0]
        self.assertFalse(section['review_required']);self.assertEqual(section['event_type'],'decision')
    def test_numeric_exclusive_condition_cannot_swap_zero_and_one(self):
        from lecture_study.summary_grounding import ground_sections
        source=self.source(0,'입력이 0일 때만 실행합니다. 입력이 1일 때는 실행하지 않습니다.')
        for condition in ('1일 때만','1인 경우에만'):
            item={'title':'입력 조건','text':'입력이 '+condition+' 실행하고 0일 때는 실행하지 않습니다.','subject':'입력','event_type':'condition','evidence_ids':['s0']}
            section=ground_sections({'sections':[item]},[source])['sections'][0]
            self.assertTrue(section['review_required']);self.assertEqual(section['text'],source.text)


class GroundingBoundaryTests(unittest.TestCase):
    def test_whitespace_is_not_a_subject(self):
        from lecture_study.summary_grounding import copied_span
        self.assertEqual(copied_span(' ','김민수는 회의에 참석했습니다.'),'')
    def test_confirming_actor_is_not_the_assignee(self):
        from lecture_study.summary_grounding import ground_sections
        source=ModalityScopeTests.source(self,0,'김민수는 배포 담당 후보였습니다. 김민수가 서연을 담당자로 확정했습니다.')
        item={'title':'담당 확정','text':'김민수는 배포 담당자로 확정됐습니다.','subject':'김민수','event_type':'decision','evidence_ids':['s0']}
        section=ground_sections({'sections':[item]},[source],'meeting')['sections'][0]
        self.assertTrue(section['review_required']);self.assertEqual(section['text'],source.text)

    def test_model_citation_order_cannot_reverse_a_later_retraction(self):
        from lecture_study.summary_grounding import ground_sections
        sources=[ModalityScopeTests.source(self,0,'김민수는 다른 후보가 없어 담당자로 확정됐습니다.'),ModalityScopeTests.source(self,1,'김민수는 담당 후보로 정정됐으며 아직 미확정입니다.')]
        item={'title':'담당 확정','text':'김민수는 다른 후보가 없어 담당자로 확정됐습니다.','subject':'김민수','event_type':'decision','evidence_ids':['s1','s0']}
        section=ground_sections({'sections':[item]},sources,'meeting')['sections'][0]
        self.assertTrue(section['review_required'])

    def test_common_conditional_paraphrase_is_not_an_ambiguity(self):
        from lecture_study.summary_grounding import ground_sections
        source=ModalityScopeTests.source(self,0,'입력이 0일 때만 실행합니다. 입력이 1일 때에는 실행하지 않습니다.')
        item={'title':'입력 조건','text':'입력이 0인 경우에만 실행하며 1에서는 실행하지 않습니다.','subject':'입력','event_type':'condition','evidence_ids':['s0']}
        self.assertFalse(ground_sections({'sections':[item]},[source])['sections'][0]['review_required'])
    def test_numeric_imyeon_premise_cannot_be_dropped(self):
        from lecture_study.summary_grounding import ground_sections
        source=ModalityScopeTests.source(self,0,'입력이 1이면 실행합니다.')
        item={'title':'입력','text':'입력이 1입니다. 실행합니다.','subject':'입력','event_type':'fact','evidence_ids':['s0']}
        self.assertTrue(ground_sections({'sections':[item]},[source])['sections'][0]['review_required'])

    def test_explicit_assumption_with_object_particle_stays_clear(self):
        from lecture_study.summary_grounding import ground_sections
        source=ModalityScopeTests.source(self,0,'마찰이 없다고 가정하면 역학적 에너지가 보존됩니다.')
        item={'title':'보존 조건','text':'마찰이 없는 가정을 하면 역학적 에너지가 보존됩니다.','subject':'마찰','event_type':'hypothesis','evidence_ids':['s0']}
        self.assertFalse(ground_sections({'sections':[item]},[source])['sections'][0]['review_required'])

    def test_conditional_clause_is_preserved_without_guessing_a_short_subject(self):
        from lecture_study.summary_grounding import ground_sections
        source=ModalityScopeTests.source(self,0,'마찰이 없다고 가정하면 역학적 에너지가 보존됩니다. 실제 장치에 마찰이 없다는 뜻은 아닙니다.')
        item={'title':'보존 조건','text':'마찰이 없는 가정을 하면 역학적 에너지가 보존되지만, 실제 장치에 마찰이 없는 것을 의미하지 않습니다.','subject_quote':'마찰이 없다고 가정하면','subject_source_id':'s0','event_type':'hypothesis','evidence_ids':['s0']}
        original=dict(item);section=ground_sections({'sections':[item]},[source],copy_subject=True)['sections'][0]
        self.assertEqual(section['subject'],item['subject_quote']);self.assertTrue(section['review_required']);self.assertEqual(section['event_type'],'hypothesis');self.assertEqual(section['title'],'원문 가정·조건 발췌');self.assertEqual(section['text'],source.text);self.assertEqual(item,original)
    def test_copied_clause_never_guesses_a_nominal_or_role(self):
        from lecture_study.summary_grounding import copied_span
        for text in ('김민수가 이서연을 담당자로 제안한다면','김민수가 이서연이 담당이라고 가정하면','제가 외동이라면','김민수가 회의를 마쳤을 때','길이 같다고 가정하면','고양이 없다고 가정하면','김민수가 이서연을담당자로 정한다면'):
            self.assertEqual(copied_span(text,text),text)

    def test_unspaced_assignee_is_not_the_confirming_actor(self):
        from lecture_study.summary_grounding import ground_sections
        source=ModalityScopeTests.source(self,0,'김민수는 배포 담당 후보였습니다. 김민수가 서연을담당자로 확정했습니다.')
        item={'title':'담당 확정','text':'김민수는 배포 담당자로 확정됐습니다.','subject':'김민수','event_type':'decision','evidence_ids':['s0']}
        section=ground_sections({'sections':[item]},[source],'meeting')['sections'][0]
        self.assertTrue(section['review_required']);self.assertEqual(section['text'],source.text)

    def test_habit_cannot_become_a_confirmed_decision_in_lecture_mode(self):
        from lecture_study.summary_grounding import ground_sections
        source=ModalityScopeTests.source(self,0,'가족은 시간이 맞으면 함께 등산을 갑니다.')
        item={'title':'가족 활동','text':'가족은 시간이 맞으면 함께 등산을 가기로 결정했다.','subject_quote':'가족','subject_source_id':'s0','event_type':'fact','evidence_ids':['s0']}
        section=ground_sections({'sections':[item]},[source],copy_subject=True)['sections'][0]
        self.assertTrue(section['review_required']);self.assertEqual(section['text'],source.text)

    def test_possessive_topic_cannot_become_the_person_who_does_not_know(self):
        from lecture_study.summary_grounding import ground_sections
        source=ModalityScopeTests.source(self,0,'남편의 공부가 무엇인가? 자세히 모른다.')
        item={'title':'공부 내용','text':'남편은 공부가 무엇인지 자세히 모른다.','subject_quote':'남편','subject_source_id':'s0','event_type':'fact','evidence_ids':['s0']}
        section=ground_sections({'sections':[item]},[source],copy_subject=True)['sections'][0]
        self.assertTrue(section['review_required']);self.assertEqual(section['text'],source.text)
        item['text']='남편의 공부 내용은 불명확하다.'
        self.assertFalse(ground_sections({'sections':[item]},[source],copy_subject=True)['sections'][0]['review_required'])
