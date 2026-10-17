import json,unittest
from unittest.mock import AsyncMock,patch
from lecture_study.models import Evidence,SourceRef,ProviderConfig,ProviderResult
from lecture_study.answers import freeze_request,get_artifact
from lecture_study.outputs import summarize_session,cached_summary_parts
from lecture_study.jobs import submit_job
from lecture_study.materials import save_note
from tests import test_answers


class ExcerptTests(unittest.TestCase):
    def sources(self):
        return [Evidence(ref=SourceRef(id='s'+str(i),kind='transcript',session_id='session',start_ms=i*1000,end_ms=(i+1)*1000),text=text,label='전사')for i,text in enumerate(('아내는 여러 장면을 상상했다.','친구들이 술을 마시는 광경이 보였다.','실제로 남편은 아직 돌아오지 않았다.','그 뒤에 문이 열렸다.','마지막으로 할멈이 나갔다.'))]
    def test_anchor_ids_are_unique_valid_and_expand_without_overlap(self):
        from lecture_study.summary_excerpts import validated_anchors,anchor_ranges
        sources=self.sources()
        self.assertEqual(validated_anchors({'evidence_ids':['s3','s1']},sources),[1,3])
        self.assertEqual(anchor_ranges([1,3],len(sources)),[(1,2),(3,4)])
        self.assertEqual(anchor_ranges([0],len(sources)),[(0,3)])
        for ids in (['missing'],['s1','s1'],[],[{}],['s0']*9):
            with self.subTest(ids=ids),self.assertRaises(ValueError):validated_anchors({'evidence_ids':ids},sources)
    def test_server_copies_original_context_without_semantic_labels(self):
        from lecture_study.summary_excerpts import excerpt_section,checked_excerpts
        sources=self.sources();aliases={e.ref.id:e.ref.id for e in sources}
        section=excerpt_section(sources,[sources[1]],aliases,{'s1':'s1'},[0],False)
        self.assertIn(sources[0].text,section['text']);self.assertEqual(section['text'],'\n'.join(q['text']for q in section['quotes']))
        self.assertNotIn('subject',section);self.assertNotIn('event_type',section)
        checked_excerpts({'sections':[section]},sources)
        changed=json.loads(json.dumps(section));changed['text']='남편이 부활했다.'
        with self.assertRaises(ValueError):checked_excerpts({'sections':[changed]},sources)
        changed=json.loads(json.dumps(section));changed['quotes'][0]['evidence_ids']=[[]]
        for malformed in (None,changed):
            with self.subTest(section=malformed),self.assertRaises(ValueError):checked_excerpts({'sections':[malformed]},sources)
    def test_partial_unit_of_one_long_source_keeps_literal_preceding_context(self):
        from lecture_study.summary_excerpts import excerpt_section
        text='마찰이 없다는 전제입니다. '+''.join(chr(0xAC00+i)for i in range(450))
        original=Evidence(ref=SourceRef(id='s0',kind='note',session_id='session'),text=text,label='노트')
        selected=original.model_copy(update={'ref':original.ref.model_copy(update={'id':'s0u9'}),'text':text[370:390]})
        section=excerpt_section([original],[selected],{'s0':'s0'},{'s0u9':'s0'},[1],False)
        self.assertEqual(section['quotes'],[{'text':text[50:370],'evidence_ids':['s0']},{'text':text[370:390],'evidence_ids':['s0']}])
    def test_preceding_context_cap_combines_other_sources_and_same_source_unit(self):
        from lecture_study.summary_excerpts import excerpt_section
        previous=Evidence(ref=SourceRef(id='s0',kind='transcript',session_id='session',start_ms=0,end_ms=1000),text='외'*300,label='전사')
        current=Evidence(ref=SourceRef(id='s1',kind='transcript',session_id='session',start_ms=1000,end_ms=2000),text='가'*320+'나'*320,label='전사')
        selected=current.model_copy(update={'ref':current.ref.model_copy(update={'id':'s1u1'}),'text':'나'*320})
        section=excerpt_section([previous,current],[selected],{'s0':'s0','s1':'s1'},{'s1u1':'s1'},[1],False)
        self.assertEqual(section['quotes'],[{'text':'가'*320,'evidence_ids':['s1']},{'text':'나'*320,'evidence_ids':['s1']}])


class ExcerptDispatchTests(unittest.IsolatedAsyncioTestCase):
    setUp=test_answers.AnswerTests.setUp
    async def test_only_new_local_general_summaries_default_to_excerpts(self):
        request=self.request.model_copy(update={'kind':'summary','provider':ProviderConfig(provider='ollama',model='test')})
        frozen=await freeze_request(self.db,request)
        self.assertEqual(frozen.get('summary_format'),'excerpts-v1');self.assertEqual(frozen['summary_output_limit'],512)
        api=await freeze_request(self.db,self.request.model_copy(update={'kind':'summary'}))
        self.assertNotIn('summary_format',api);self.assertEqual(api['summary_grounding'],'quotes-v1')
    async def test_missing_tail_repairs_once_then_keeps_literal_fallback_and_cache(self):
        refs=[self.ref]+[save_note(self.db,self.sid,'마지막에는 계약을 취소했습니다.'if i==6 else '중간 설명 '+str(i)+'에서는 배치 계획을 정정했습니다.')for i in range(1,9)]
        evidence=[Evidence(ref=ref,text=self.db.execute('select text_snapshot from sources where id=?',(ref.id,)).fetchone()[0],label='노트')for ref in refs]
        request=self.request.model_copy(update={'kind':'summary','provider':ProviderConfig(provider='ollama',model='test')})
        frozen={'request':request.model_dump(),'evidence':[e.model_dump()for e in evidence],'summary_parts':[[e.model_dump()for e in evidence]],'summary_format':'excerpts-v1','cutoff_ms':None,'warning':''}
        job=submit_job(self.db,self.sid,'ai',frozen)
        results=[ProviderResult(text=json.dumps({'evidence_ids':[ident]}),model='test',usage={},elapsed_ms=1)for ident in ('s1','s2')]
        with patch('lecture_study.outputs.generate',new=AsyncMock(side_effect=results))as generated:result=await summarize_session(self.db,frozen,job['id'])
        self.assertEqual(generated.await_count,2);self.assertEqual(generated.call_args.kwargs['output_limit'],512);self.assertEqual(result.body['summary_format'],'excerpts-v1');self.assertEqual(result.body['selection_incomplete_parts'],[0])
        self.assertNotIn('s2',generated.call_args.args[3]['properties']['evidence_ids']['items']['enum'])
        self.assertEqual(len(result.body['sections']),2);self.assertTrue(result.body['sections'][-1]['review_required'])
        self.assertIn('계약을 취소',result.body['sections'][-1]['text']);self.assertEqual(set(result.body['covered_source_ids']),{r.id for r in refs})
        self.assertEqual(cached_summary_parts(self.db,job['id'])['summary_format'],'excerpts-v1')
        with patch('lecture_study.outputs.generate',new=AsyncMock(side_effect=AssertionError('cached parts must not regenerate'))):await summarize_session(self.db,frozen,job['id'])
        saved=get_artifact(self.db,result.id);self.assertEqual(saved['metadata']['elapsed_ms'],2)
    async def test_invalid_repair_keeps_first_selection_and_orders_literal_fallbacks(self):
        refs=[self.ref,save_note(self.db,self.sid,'중간에는 배치 계획을 정정했습니다.'),save_note(self.db,self.sid,'마지막에는 계약을 취소했습니다.')]
        evidence=[Evidence(ref=ref,text=self.db.execute('select text_snapshot from sources where id=?',(ref.id,)).fetchone()[0],label='노트')for ref in refs]
        request=self.request.model_copy(update={'kind':'summary','provider':ProviderConfig(provider='ollama',model='test')})
        frozen={'request':request.model_dump(),'evidence':[e.model_dump()for e in evidence],'summary_parts':[[e.model_dump()for e in evidence]],'summary_format':'excerpts-v1','summary_output_limit':512,'cutoff_ms':None,'warning':''};job=submit_job(self.db,self.sid,'ai',frozen)
        results=[ProviderResult(text=json.dumps(body),model='test',usage={},elapsed_ms=1)for body in ({'evidence_ids':['s3']},{'evidence_ids':['unknown']})]
        with patch('lecture_study.outputs.generate',new=AsyncMock(side_effect=results))as generated:result=await summarize_session(self.db,frozen,job['id'])
        self.assertEqual(generated.await_count,2);self.assertEqual([s['evidence_ids']for s in result.body['sections']],[[ref.id]for ref in refs]);self.assertEqual([s['review_required']for s in result.body['sections']],[True,True,False])
        saved=json.loads(self.db.execute('select body from artifact_parts where job_id=?',(job['id'],)).fetchone()[0]);saved['sections'][0]['quotes'][0]['text']='원문에 없는 부활';saved['sections'][0]['text']='원문에 없는 부활'
        with self.db:self.db.execute('update artifact_parts set body=? where job_id=?',(json.dumps(saved),job['id']))
        with self.assertRaises(ValueError):cached_summary_parts(self.db,job['id'])
    async def test_near_full_input_repairs_with_only_missing_bands_and_restores_original_ids(self):
        from lecture_study.answers import evidence_schema
        from lecture_study.outputs import contextual_summary_messages
        from lecture_study.summary_grounding import grounded_units
        from lecture_study.summary_excerpts import SCHEMA,INSTRUCTION
        refs=[self.ref]+[save_note(self.db,self.sid,'실제 검증 원문 '+str(i)+'에서 조건과 정정을 설명했습니다.')for i in range(1,30)]
        evidence=[Evidence(ref=ref,text=self.db.execute('select text_snapshot from sources where id=?',(ref.id,)).fetchone()[0],label='노트')for ref in refs]
        request=self.request.model_copy(update={'kind':'summary','provider':ProviderConfig(provider='ollama',model='test',context_limit=8192)})
        aliases={e.ref.id:'s'+str(i+1)for i,e in enumerate(evidence)};units,_=grounded_units(evidence,aliases)
        _,bound=contextual_summary_messages(request,units,INSTRUCTION,evidence_schema(SCHEMA,units),[],output_limit=512)
        self.assertLess(bound+515,8192);request=request.model_copy(update={'provider':request.provider.model_copy(update={'context_limit':bound+515})})
        frozen={'request':request.model_dump(),'evidence':[e.model_dump()for e in evidence],'summary_parts':[[e.model_dump()for e in evidence]],'summary_format':'excerpts-v1','summary_output_limit':512,'summary_instruction':INSTRUCTION,'cutoff_ms':None,'warning':''};job=submit_job(self.db,self.sid,'ai',frozen)
        results=[ProviderResult(text=json.dumps({'evidence_ids':ids}),model='test',usage={},elapsed_ms=1)for ids in (['s1'],['s11','s21'])]
        with patch('lecture_study.outputs.generate',new=AsyncMock(side_effect=results))as generated:result=await summarize_session(self.db,frozen,job['id'])
        self.assertEqual(generated.await_count,2)
        second=json.loads(generated.call_args_list[1].args[1][1]['content'])['evidence'];self.assertEqual([e['source_id']for e in second],['s'+str(i)for i in range(11,31)])
        self.assertEqual(result.body['selection_incomplete_parts'],[]);self.assertFalse(any(s['review_required']for s in result.body['sections']))
        self.assertIn(refs[10].id,result.body['cited_source_ids']);self.assertIn(refs[20].id,result.body['cited_source_ids'])


class CompleteExcerptTests(unittest.TestCase):
    def units(self,texts):
        return [Evidence(ref=SourceRef(id='s'+str(i),kind='transcript',session_id='session',start_ms=i*1000,end_ms=(i+1)*1000),text=text,label='전사')for i,text in enumerate(texts)]

    def ranges(self,units,anchors=None,restore=None):
        from lecture_study.summary_excerpts import complete_ranges
        return complete_ranges([0]if anchors is None else anchors,units,restore or {e.ref.id:e.ref.id for e in units})

    def test_imagery_clause_keeps_the_following_predicate(self):
        units=self.units(['설명은 여기까지였다','모두 잠시 쉬었다','강사는 사례를 다시 들었다','학생이 떠올린 가정과 예시가','다시 논의의 주제로 돌아왔다'])
        self.assertEqual(self.ranges(units),[(0,4)])

    def test_final_departure_keeps_short_predicate_and_legacy_range_is_unchanged(self):
        from lecture_study.summary_excerpts import anchor_ranges
        units=self.units(['담당자는 방으로 들어왔다','동료는 출입문에 멈춰 선 채','두 번 손을 흔들고는','그 방향으로','돌아갔다'])
        self.assertEqual(anchor_ranges([0],len(units)),[(0,3)])
        self.assertEqual(self.ranges(units),[(0,4)])

    def test_finished_fourth_unit_does_not_pull_in_another_sentence(self):
        for ending in ('확정했습니다.','확정했다','확정했어요','확정했죠','확정인가요?','확정이다.”'):
            with self.subTest(ending=ending):
                self.assertEqual(self.ranges(self.units(['첫 번째 원문','두 번째 원문','세 번째 원문',ending,'다음 주제는 미정이다'])),[(0,3)])

    def test_unfinished_range_extends_by_at_most_four_units(self):
        units=self.units(['아직 이어지는 원문 '+str(i)for i in range(8)]+['이제야 마쳤다'])
        self.assertEqual(self.ranges(units),[(0,7)])

    def test_causal_clause_ending_in_nikka_keeps_the_following_decision(self):
        units=self.units(['앞 문장이다','설명을 시작한다','선행 조건이다','시간이 없으니까','제출일을 미루기로 했다'])
        self.assertEqual(self.ranges(units),[(0,4)])

    def test_extension_stops_at_session_gap_missing_time_or_reverse_time(self):
        base=self.units(['첫 번째 원문','두 번째 원문','세 번째 원문','조건이 성립한다면','결과가 달라진다'])
        changes=({'session_id':'other-session'},{'start_ms':64000,'end_ms':65000},{'start_ms':None,'end_ms':None},{'start_ms':2000,'end_ms':3000})
        for change in changes:
            with self.subTest(change=change):
                units=base[:4]+[base[4].model_copy(update={'ref':base[4].ref.model_copy(update=change)})]
                self.assertEqual(self.ranges(units),[(0,3)])

    def test_extension_does_not_cross_original_note_or_material_source(self):
        for kind in ('note','material'):
            with self.subTest(kind=kind):
                units=[e.model_copy(update={'ref':e.ref.model_copy(update={'kind':kind,'start_ms':None,'end_ms':None})})for e in self.units(['첫 번째 원문','두 번째 원문','세 번째 원문','조건이 성립한다면','결과가 달라진다'])]
                restore={e.ref.id:('source-a'if i<4 else 'source-b')for i,e in enumerate(units)}
                self.assertEqual(self.ranges(units,restore=restore),[(0,3)])
                self.assertEqual(self.ranges(units,restore={e.ref.id:'source-a'for e in units}),[(0,4)])

    def test_base_range_also_stops_before_an_unrelated_session(self):
        units=self.units(['첫 번째 원문','아직 끝나지 않은 조건','다른 수업의 원문','다른 수업의 끝이다'])
        units[2]=units[2].model_copy(update={'ref':units[2].ref.model_copy(update={'session_id':'other-session'})})
        self.assertEqual(self.ranges(units),[(0,1)])

    def test_overlapping_completed_ranges_are_merged(self):
        units=self.units(['첫 번째 원문','두 번째 원문','세 번째 원문','조건이 성립한다면','결과가 달라진다','이어지는 설명','마무리 설명','마쳤다'])
        self.assertEqual(self.ranges(units,[0,4]),[(0,7)])

    def test_repeated_phrase_does_not_acquire_first_occurrences_subject_context(self):
        from lecture_study.summary_excerpts import excerpt_section,checked_excerpts
        from lecture_study.summary_grounding import grounded_units
        original=Evidence(ref=SourceRef(id='original',kind='note',session_id='session'),text='철수의 가정입니다. 결과는 같습니다. '+'중간 설명 '*80+'. 영희의 실제 경험입니다. 결과는 같습니다.',label='노트')
        aliases={'original':'s1'};units,restore=grounded_units([original],aliases)
        legacy=excerpt_section([original],[units[-1]],aliases,restore,[2],False)
        self.assertIn('철수',legacy['text'])
        section=excerpt_section([original],[units[-1]],aliases,restore,[2],False,complete=True)
        self.assertEqual(section['quotes'],[{'text':'결과는 같습니다.','evidence_ids':['original']}])
        self.assertTrue(section['review_required']);self.assertNotIn('subject',section);self.assertNotIn('event_type',section)
        checked_excerpts({'sections':[section]},[original])

    def test_repeated_selected_sentence_keeps_both_occurrences_in_source_order(self):
        from lecture_study.summary_excerpts import excerpt_section,checked_excerpts
        from lecture_study.summary_grounding import grounded_units
        texts=['철수는 가정을 말했다.','내일 비가 온다.','영희는 실제 경험을 말했다.','내일 비가 온다.']
        original=Evidence(ref=SourceRef(id='original',kind='note',session_id='session'),text=' '.join(texts),label='노트')
        aliases={'original':'s1'};units,restore=grounded_units([original],aliases)
        legacy=excerpt_section([original],units,aliases,restore,[0,1,2],False)
        self.assertEqual([q['text']for q in legacy['quotes']],texts[:3])
        section=excerpt_section([original],units,aliases,restore,[0,1,2],False,complete=True)
        self.assertEqual([q['text']for q in section['quotes']],texts)
        self.assertFalse(section['review_required'])
        checked_excerpts({'sections':[section]},[original])

    def test_unfinished_extension_limit_is_marked_for_review_without_rewriting(self):
        from lecture_study.summary_excerpts import excerpt_section,checked_excerpts
        units=self.units(['아직 이어지는 원문 '+str(i)for i in range(8)]+['마쳤다'])
        aliases={e.ref.id:e.ref.id for e in units};start,end=self.ranges(units)[0]
        section=excerpt_section(units,units[start:end+1],aliases,aliases,[0,1,2],False,complete=True)
        self.assertTrue(section['review_required'])
        self.assertEqual([q['text']for q in section['quotes']],[e.text for e in units[:8]])
        checked_excerpts({'sections':[section]},units)

    def test_preceding_self_context_survives_a_short_pause_and_thirty_three_seconds(self):
        from lecture_study.summary_excerpts import excerpt_section,checked_excerpts
        texts=['저는 형제가 없는 외동으로 자랐어요.','지금은 부모님과 같은 집에서 지냅니다.','네, 그렇습니다.','잠깐 생각을 정리한 뒤에 이어서 이야기할게요.','그래서 제 가족을 설명하자면','저와 부모님이 함께 사는 세 식구예요.']
        times=[(168400,175630),(175630,182740),(182740,184460),(195920,199220),(199980,201700),(201700,205000)]
        units=[e.model_copy(update={'ref':e.ref.model_copy(update={'start_ms':start,'end_ms':end})})for e,(start,end)in zip(self.units(texts),times)]
        aliases={e.ref.id:e.ref.id for e in units}
        section=excerpt_section(units,[units[-1]],aliases,aliases,[1],False,complete=True)
        self.assertEqual([q['text']for q in section['quotes']],texts)
        self.assertFalse(section['review_required'])
        self.assertNotIn('subject',section);self.assertNotIn('event_type',section)
        checked_excerpts({'sections':[section]},units)

    def test_preceding_context_stops_at_session_missing_time_total_time_and_gap_limits(self):
        from lecture_study.summary_excerpts import excerpt_section
        base=self.units(['저는 어린 시절 외동으로 자랐어요.','지금 가족에 관한 설명입니다.'])
        selected=base[1].model_copy(update={'ref':base[1].ref.model_copy(update={'start_ms':201700,'end_ms':205000})})
        changes=[{'session_id':'other-session','start_ms':200700,'end_ms':201700},{'start_ms':None,'end_ms':None},{'start_ms':156699,'end_ms':201000},{'start_ms':165000,'end_ms':171699}]
        for change in changes:
            with self.subTest(change=change):
                units=[base[0].model_copy(update={'ref':base[0].ref.model_copy(update=change)}),selected];aliases={e.ref.id:e.ref.id for e in units}
                section=excerpt_section(units,[selected],aliases,aliases,[1],False,complete=True)
                self.assertEqual(section['quotes'],[{'text':selected.text,'evidence_ids':[selected.ref.id]}])

    def test_forward_completion_keeps_its_three_second_gap_limit(self):
        units=self.units(['첫 설명입니다.','두 번째 설명입니다.','세 번째 설명입니다.','조건을 만족하면','결과가 달라집니다.'])
        units[-1]=units[-1].model_copy(update={'ref':units[-1].ref.model_copy(update={'start_ms':7001,'end_ms':8001})})
        self.assertEqual(self.ranges(units),[(0,3)])

    def test_preceding_context_retains_eight_unit_and_six_hundred_forty_character_caps(self):
        from lecture_study.summary_excerpts import excerpt_section
        for texts,expected in ((['문맥 '+str(i)+'입니다.'for i in range(10)],list(range(1,10))),(['가'*320,'나'*320,'다'*320,'마쳤다'],[1,2,3])):
            with self.subTest(lengths=[len(text)for text in texts]):
                units=self.units(texts);aliases={e.ref.id:e.ref.id for e in units}
                section=excerpt_section(units,[units[-1]],aliases,aliases,[1],False,complete=True)
                self.assertEqual([q['text']for q in section['quotes']],[texts[i]for i in expected])
                self.assertLessEqual(sum(len(q['text'])for q in section['quotes'][:-1]),640)


class ConsolidatedExcerptTests(unittest.TestCase):
    def sources(self,count=25):
        return [Evidence(ref=SourceRef(id='source-'+str(i),kind='transcript',session_id='session',start_ms=i*1000,end_ms=(i+1)*1000),text='서로 다른 원문 '+str(i)+'입니다.',label='전사')for i in range(count)]

    def section(self,units,groups=None,review=False):
        quotes=[{'text':e.text,'evidence_ids':[e.ref.id]}for e in units]
        return {'title':'핵심 원문','text':'\n'.join(q['text']for q in quotes),'evidence_ids':list(dict.fromkeys(e.ref.id for e in units)),'quotes':quotes,'review_required':review,'coverage_groups':groups or []}

    def consolidate(self,sections,evidence):
        from lecture_study.summary_excerpts import consolidate_excerpts,checked_excerpts
        result=consolidate_excerpts(sections,evidence)
        checked_excerpts({'sections':result},evidence)
        return result

    def test_overlapping_context_chain_keeps_each_exact_source_unit_once_and_originals_unchanged(self):
        evidence=self.sources();spans=[(2,10),(3,14),(10,18),(11,19),(12,22)]
        sections=[self.section(evidence[start:end+1],[min(2,i)])for i,(start,end)in enumerate(spans)]
        before=json.loads(json.dumps(sections));result=self.consolidate(sections,evidence)
        self.assertEqual(result,[self.section(evidence[2:23],[0,1,2])]);self.assertEqual(sections,before)

    def test_identical_text_with_different_source_ids_is_retained(self):
        evidence=self.sources(3);evidence[2]=evidence[2].model_copy(update={'text':evidence[0].text})
        sections=[self.section(evidence[:2],[0]),self.section(evidence[1:],[2])]
        result=self.consolidate(sections,evidence)
        self.assertEqual(result,[self.section(evidence,[0,2])])
        self.assertEqual(self.consolidate([self.section([evidence[0]]),self.section([evidence[2]])],evidence),[self.section([evidence[0]]),self.section([evidence[2]])])

    def test_repeated_unit_within_one_source_is_ambiguous_and_stays_separate(self):
        from lecture_study.summary_grounding import grounded_units
        original=Evidence(ref=SourceRef(id='same-source',kind='note',session_id='session'),text='가정의 앞 문장입니다. 결과는 같습니다. 실제 사건의 앞 문장입니다. 결과는 같습니다.',label='노트')
        units,_=grounded_units([original],{'same-source':'alias'})
        units=[e.model_copy(update={'ref':original.ref})for e in units]
        sections=[self.section(units[:3],[0]),self.section(units[1:],[2])]
        self.assertEqual(self.consolidate(sections,[original]),sections)

    def test_partial_quote_without_an_exact_source_unit_stays_separate(self):
        evidence=self.sources(4);partial=evidence[1].model_copy(update={'text':evidence[1].text[:5]})
        sections=[self.section([evidence[0],partial]),self.section(evidence[1:])]
        self.assertEqual(self.consolidate(sections,evidence),sections)

    def test_reviewed_fallback_remains_unchanged_and_blocks_consolidation_across_it(self):
        evidence=self.sources(7)
        sections=[self.section(evidence[:4],[0]),self.section(evidence[2:5],[],True),self.section(evidence[3:6],[1]),self.section(evidence[4:],[2])]
        result=self.consolidate(sections,evidence)
        self.assertEqual(result,[sections[0],sections[1],self.section(evidence[3:],[1,2])])
        self.assertEqual(result[1],sections[1]);self.assertTrue(result[1]['review_required'])

    def test_gaps_reverse_chronology_and_noncontiguous_quotes_are_not_joined(self):
        evidence=self.sources(10)
        for sections in (
            [self.section(evidence[:3]),self.section(evidence[4:7])],
            [self.section(evidence[3:7]),self.section(evidence[2:8])],
            [self.section([evidence[0],evidence[2]]),self.section(evidence[2:5])],
            [self.section([evidence[3],evidence[2]]),self.section(evidence[2:5])],
        ):
            with self.subTest(quotes=[s['evidence_ids']for s in sections]):self.assertEqual(self.consolidate(sections,evidence),sections)

    def test_fully_contained_exact_section_keeps_coverage_without_repeating_quotes(self):
        evidence=self.sources(6);sections=[self.section(evidence,[0]),self.section(evidence[2:5],[1,2])]
        self.assertEqual(self.consolidate(sections,evidence),[self.section(evidence,[0,1,2])])


class CompleteExcerptDispatchTests(unittest.IsolatedAsyncioTestCase):
    setUp=test_answers.AnswerTests.setUp

    def frozen(self,policy=None,text=None):
        text=text or '\n'.join(('담당자는 방으로 들어왔다','동료는 출입문에 멈춰 선 채','두 번 손을 흔들고는','그 방향으로','돌아갔다'))
        ref=save_note(self.db,self.sid,text);evidence=Evidence(ref=ref,text=text,label='노트')
        request=self.request.model_copy(update={'kind':'summary','provider':ProviderConfig(provider='ollama',model='test')})
        frozen={'request':request.model_dump(),'evidence':[evidence.model_dump()],'summary_parts':[[evidence.model_dump()]],'summary_format':'excerpts-v1','summary_output_limit':512,'cutoff_ms':None,'warning':''}
        if policy is not None:frozen['summary_excerpt_policy']=policy
        return frozen

    def selection(self):
        return ProviderResult(text=json.dumps({'evidence_ids':['s1u0']}),model='test',usage={},elapsed_ms=1)

    async def test_new_local_frozen_requests_have_complete_policy_but_api_requests_do_not(self):
        for provider in ('ollama','local'):
            with self.subTest(provider=provider),patch('lecture_study.token_budget.local_profile',return_value=None):
                request=self.request.model_copy(update={'kind':'summary','provider':ProviderConfig(provider=provider,model='test')})
                frozen=await freeze_request(self.db,request)
                self.assertEqual(frozen.get('summary_excerpt_policy'),'complete-v1')
        api=await freeze_request(self.db,self.request.model_copy(update={'kind':'summary'}))
        self.assertNotIn('summary_excerpt_policy',api)

    async def test_complete_policy_dispatch_keeps_final_short_predicate_without_another_call(self):
        frozen=self.frozen('complete-v1');job=submit_job(self.db,self.sid,'ai',frozen)
        with patch('lecture_study.outputs.generate',new=AsyncMock(return_value=self.selection()))as generated:result=await summarize_session(self.db,frozen,job['id'])
        self.assertEqual(generated.await_count,1)
        self.assertEqual(result.body['sections'][0]['quotes'][-1]['text'],'돌아갔다')
        self.assertEqual(result.body['selection_incomplete_parts'],[])
        self.assertEqual(result.body['unquoted_sources'],[])
        self.assertFalse(result.body['sections'][0]['review_required'])

    async def test_frozen_request_without_policy_keeps_original_four_units(self):
        frozen=self.frozen();job=submit_job(self.db,self.sid,'ai',frozen)
        with patch('lecture_study.outputs.generate',new=AsyncMock(return_value=self.selection()))as generated:result=await summarize_session(self.db,frozen,job['id'])
        self.assertEqual(generated.await_count,1)
        self.assertEqual(result.body['sections'][0]['quotes'][-1]['text'],'그 방향으로')
        self.assertNotIn('돌아갔다',result.body['sections'][0]['text'])
        self.assertNotIn('summary_excerpt_policy',frozen)

    async def test_cached_parts_remain_byte_identical_for_both_frozen_policies(self):
        for policy in (None,'complete-v1'):
            with self.subTest(policy=policy):
                frozen=self.frozen(policy);job=submit_job(self.db,self.sid,'ai',frozen)
                with patch('lecture_study.outputs.generate',new=AsyncMock(return_value=self.selection())):first=await summarize_session(self.db,frozen,job['id'])
                before=[tuple(row)for row in self.db.execute('select part_no,body,metadata from artifact_parts where job_id=? order by part_no',(job['id'],))]
                with patch('lecture_study.outputs.generate',new=AsyncMock(side_effect=AssertionError('cached parts must not regenerate')))as generated:resumed=await summarize_session(self.db,frozen,job['id'])
                generated.assert_not_awaited()
                after=[tuple(row)for row in self.db.execute('select part_no,body,metadata from artifact_parts where job_id=? order by part_no',(job['id'],))]
                self.assertEqual(after,before);self.assertEqual(resumed.body['sections'],first.body['sections'])
                self.assertEqual(cached_summary_parts(self.db,job['id'])['parts'][0]['sections'],first.body['sections'])

    async def test_final_overlap_consolidation_preserves_original_parts_and_cached_retry(self):
        lines=['원문 '+str(i)+'의 고유한 설명을 마쳤습니다.'for i in range(24)]
        frozen=self.frozen('complete-v1','\n'.join(lines));job=submit_job(self.db,self.sid,'ai',frozen)
        selection=ProviderResult(text=json.dumps({'evidence_ids':['s1u0','s1u8','s1u16','s1u20']}),model='test',usage={},elapsed_ms=1)
        with patch('lecture_study.outputs.generate',new=AsyncMock(return_value=selection))as generated:first=await summarize_session(self.db,frozen,job['id'])
        self.assertEqual(generated.await_count,1);self.assertEqual(len(first.body['sections']),1)
        self.assertEqual([q['text']for q in first.body['sections'][0]['quotes']],lines)
        self.assertEqual(first.body['sections'][0]['coverage_groups'],[0,1,2])
        self.assertEqual(first.body['selection_incomplete_parts'],[]);self.assertEqual(first.body['unquoted_sources'],[])
        before=tuple(self.db.execute('select body,metadata from artifact_parts where job_id=?',(job['id'],)).fetchone())
        original=json.loads(before[0])['sections'];self.assertEqual(len(original),4)
        self.assertEqual(first.body['part_sections'],original)
        self.assertEqual(cached_summary_parts(self.db,job['id'])['parts'][0]['sections'],original)
        self.assertEqual(first.body['cited_source_ids'],[frozen['evidence'][0]['ref']['id']])
        with patch('lecture_study.outputs.generate',new=AsyncMock(side_effect=AssertionError('cached parts must not regenerate')))as generated:resumed=await summarize_session(self.db,frozen,job['id'])
        generated.assert_not_awaited()
        self.assertEqual(tuple(self.db.execute('select body,metadata from artifact_parts where job_id=?',(job['id'],)).fetchone()),before)
        self.assertEqual(resumed.body,first.body)

    async def test_final_consolidation_does_not_cross_part_boundaries(self):
        frozen=self.frozen('complete-v1');frozen['summary_parts']*=2;job=submit_job(self.db,self.sid,'ai',frozen)
        with patch('lecture_study.outputs.generate',new=AsyncMock(return_value=self.selection()))as generated:result=await summarize_session(self.db,frozen,job['id'])
        self.assertEqual(generated.await_count,2);self.assertEqual(len(result.body['sections']),2)
        self.assertEqual(result.body['sections'],result.body['part_sections'])

    async def test_short_final_unit_repairs_once_then_survives_as_reviewed_literal_fallback(self):
        lines=['원문 '+str(i)+'의 긴 설명을 정리했습니다.'for i in range(10)]+['돌아갔다']
        frozen=self.frozen('complete-v1','\n'.join(lines));job=submit_job(self.db,self.sid,'ai',frozen)
        results=[ProviderResult(text=json.dumps({'evidence_ids':ids}),model='test',usage={},elapsed_ms=1)for ids in (['s1u0','s1u3','s1u6'],[])]
        with patch('lecture_study.outputs.generate',new=AsyncMock(side_effect=results))as generated:result=await summarize_session(self.db,frozen,job['id'])
        self.assertEqual(generated.await_count,2)
        self.assertEqual(generated.call_args_list[1].args[3]['properties']['evidence_ids']['items']['enum'],['s1u7','s1u8','s1u9','s1u10'])
        selected=result.body['sections'][:-1];fallback=result.body['sections'][-1]
        self.assertEqual({group for section in selected for group in section['coverage_groups']},{0,1,2})
        self.assertFalse(any(section['review_required']for section in selected))
        self.assertEqual(fallback['quotes'][-1]['text'],'돌아갔다');self.assertTrue(fallback['review_required'])
        self.assertEqual(fallback['coverage_groups'],[]);self.assertEqual(result.body['selection_incomplete_parts'],[0])
        self.assertEqual(result.body['unquoted_sources'],[])
        self.assertTrue(json.loads(self.db.execute('select body from artifact_parts where job_id=?',(job['id'],)).fetchone()[0])['selection_incomplete'])

    async def test_copied_cache_is_rejected_across_policy_boundaries_in_both_read_paths(self):
        for source_policy,target_policy in ((None,'complete-v1'),('complete-v1',None)):
            with self.subTest(source_policy=source_policy,target_policy=target_policy):
                original=self.frozen(source_policy);source=submit_job(self.db,self.sid,'ai',original)
                with patch('lecture_study.outputs.generate',new=AsyncMock(return_value=self.selection())):await summarize_session(self.db,original,source['id'])
                target_frozen=dict(original);target_frozen.pop('summary_excerpt_policy',None)
                if target_policy:target_frozen['summary_excerpt_policy']=target_policy
                target=submit_job(self.db,self.sid,'ai',target_frozen)
                saved=self.db.execute('select body,metadata from artifact_parts where job_id=?',(source['id'],)).fetchone();info=json.loads(saved['metadata'])
                if source_policy is None:info.pop('excerpt_policy',None)
                with self.db:self.db.execute('insert into artifact_parts values(?,?,?,?)',(target['id'],0,saved['body'],json.dumps(info)))
                with patch('lecture_study.outputs.generate',new=AsyncMock(side_effect=AssertionError('mixed cache must not generate')))as generated:
                    with self.assertRaisesRegex(ValueError,'정책'):await summarize_session(self.db,target_frozen,target['id'])
                    with self.assertRaisesRegex(ValueError,'정책'):cached_summary_parts(self.db,target['id'])
                generated.assert_not_awaited()
                self.assertEqual(self.db.execute('select count(*) from artifacts where job_id=?',(target['id'],)).fetchone()[0],0)

    def multipart_frozen(self):
        frozen=self.frozen('complete-v1');ref=save_note(self.db,self.sid,'새로운 마지막 조건은 변경하지 않는다.')
        second=Evidence(ref=ref,text='새로운 마지막 조건은 변경하지 않는다.',label='노트').model_dump()
        frozen['evidence'].append(second);frozen['summary_parts'].append([second])
        return frozen

    async def cache_first_part_before_interruption(self,frozen,job_id):
        with patch('lecture_study.outputs.generate',new=AsyncMock(side_effect=[self.selection(),RuntimeError('검증용 두 번째 구간 중단')]))as generated:
            with self.assertRaisesRegex(RuntimeError,'두 번째 구간 중단'):await summarize_session(self.db,frozen,job_id)
        self.assertEqual(generated.await_count,2)
        saved=self.db.execute('select part_no,body,metadata from artifact_parts where job_id=?',(job_id,)).fetchall()
        self.assertEqual(len(saved),1);self.assertEqual(saved[0]['part_no'],0)
        self.assertEqual(json.loads(saved[0]['metadata'])['excerpt_policy'],'complete-v1')
        return tuple(saved[0])

    async def test_partial_new_policy_resume_reuses_first_part_and_generates_only_the_missing_part(self):
        frozen=self.multipart_frozen();job=submit_job(self.db,self.sid,'ai',frozen)
        before=await self.cache_first_part_before_interruption(frozen,job['id'])
        self.assertEqual(len(cached_summary_parts(self.db,job['id'])['parts']),1)
        second=ProviderResult(text=json.dumps({'evidence_ids':['s2']}),model='test',usage={},elapsed_ms=1)
        with patch('lecture_study.outputs.generate',new=AsyncMock(return_value=second))as generated:result=await summarize_session(self.db,frozen,job['id'])
        self.assertEqual(generated.await_count,1)
        self.assertEqual(generated.call_args.args[3]['properties']['evidence_ids']['items']['enum'],['s2'])
        after=self.db.execute('select part_no,body,metadata from artifact_parts where job_id=? order by part_no',(job['id'],)).fetchall()
        self.assertEqual(tuple(after[0]),before);self.assertEqual(len(after),2)
        self.assertTrue(all(json.loads(row['metadata'])['excerpt_policy']=='complete-v1'for row in after))
        self.assertEqual(result.body['completed_parts'],2);self.assertEqual(result.body['selection_incomplete_parts'],[])

    async def test_partial_new_policy_resume_rejects_old_cache_in_later_part(self):
        frozen=self.multipart_frozen();job=submit_job(self.db,self.sid,'ai',frozen)
        await self.cache_first_part_before_interruption(frozen,job['id'])
        legacy=dict(frozen);legacy.pop('summary_excerpt_policy');legacy['summary_parts']=[frozen['summary_parts'][1]]
        old_job=submit_job(self.db,self.sid,'ai',legacy)
        second=ProviderResult(text=json.dumps({'evidence_ids':['s2']}),model='test',usage={},elapsed_ms=1)
        with patch('lecture_study.outputs.generate',new=AsyncMock(return_value=second)):await summarize_session(self.db,legacy,old_job['id'])
        saved=self.db.execute('select body,metadata from artifact_parts where job_id=?',(old_job['id'],)).fetchone();info=json.loads(saved['metadata']);info.pop('excerpt_policy',None)
        with self.db:self.db.execute('insert into artifact_parts values(?,?,?,?)',(job['id'],1,saved['body'],json.dumps(info)))
        before=[tuple(row)for row in self.db.execute('select part_no,body,metadata from artifact_parts where job_id=? order by part_no',(job['id'],))]
        with patch('lecture_study.outputs.generate',new=AsyncMock(side_effect=AssertionError('mixed cache must not generate')))as generated:
            with self.assertRaisesRegex(ValueError,'정책'):await summarize_session(self.db,frozen,job['id'])
            with self.assertRaisesRegex(ValueError,'정책'):cached_summary_parts(self.db,job['id'])
        generated.assert_not_awaited()
        after=[tuple(row)for row in self.db.execute('select part_no,body,metadata from artifact_parts where job_id=? order by part_no',(job['id'],))]
        self.assertEqual(after,before)
        self.assertEqual(self.db.execute('select count(*) from artifacts where job_id=?',(job['id'],)).fetchone()[0],0)
