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
