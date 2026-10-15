import json,unittest
from lecture_study.outputs import cached_summary_parts
from lecture_study.jobs import submit_job
from lecture_study.answers import freeze_request
from unittest.mock import patch,AsyncMock
from lecture_study.models import ProviderResult
from lecture_study.outputs import summarize_session
from tests import test_summary_context

class PartialSummaryTests(unittest.IsolatedAsyncioTestCase):
    setUp=test_summary_context.ContextSummaryTests.setUp
    async def test_failed_merge_preserves_parts_with_source_links(self):
        frozen=await freeze_request(self.db,self.request.model_copy(update={'kind':'summary'}));job=submit_job(self.db,self.sid,'ai',frozen)
        body={'sections':[{'title':'정의','text':'프로세스 정의','subject_quote':'프로세스','subject_source_id':'s1','event_type':'fact','evidence_ids':['s1']}]}
        with patch('lecture_study.outputs.generate',new=AsyncMock(return_value=ProviderResult(text=json.dumps(body),model='test',usage={},elapsed_ms=1))),patch('lecture_study.merging.merge_generated',new=AsyncMock(side_effect=ValueError('병합 실패'))):
            with self.assertRaisesRegex(ValueError,'병합 실패'):await summarize_session(self.db,frozen,job['id'])
        cached=cached_summary_parts(self.db,job['id'])
        self.assertEqual(len(cached['parts']),1);self.assertEqual(cached['parts'][0]['sections'][0]['evidence_ids'],[self.ref.id]);self.assertEqual(cached['parts'][0]['source_ids'],[self.ref.id])
        self.db.execute('UPDATE sources SET deleted=1 WHERE id=?',(self.ref.id,));self.db.commit()
        with self.assertRaises(ValueError):cached_summary_parts(self.db,job['id'])
    async def test_corrupt_cached_citation_is_rejected(self):
        frozen=await freeze_request(self.db,self.request.model_copy(update={'kind':'summary'}));job=submit_job(self.db,self.sid,'ai',frozen)
        with self.db:self.db.execute('INSERT INTO artifact_parts VALUES(?,?,?,?)',(job['id'],0,json.dumps({'sections':[{'title':'가짜','text':'가짜','evidence_ids':['unknown']}]}),'{}'))
        with self.assertRaises(ValueError):cached_summary_parts(self.db,job['id'])

    async def test_unquoted_short_source_is_saved_and_exported_without_being_added_as_generated_summary(self):
        from lecture_study.materials import save_note
        from lecture_study.answers import get_artifact
        from lecture_study.outputs import export_markdown
        save_note(self.db,self.sid,'프로세스는 실행 중인 프로그램입니다. 학생입니다.')
        frozen=await freeze_request(self.db,self.request.model_copy(update={'kind':'summary'}));job=submit_job(self.db,self.sid,'ai',frozen)
        raw={'sections':[{'title':'정의','text':'프로세스는 실행 중인 프로그램이다.','subject_quote':'프로세스','subject_source_id':'s1u0','event_type':'fact','evidence_ids':['s1u0']}]}
        with patch('lecture_study.outputs.generate',new=AsyncMock(return_value=ProviderResult(text=json.dumps(raw),model='test',usage={},elapsed_ms=1))):result=await summarize_session(self.db,frozen,job['id'])
        body=get_artifact(self.db,result.id)['body'];self.assertEqual(body['unquoted_sources'][0]['text'],'학생입니다.');self.assertNotIn('학생입니다.',' '.join(s['text']for s in body['sections']))
        exported=export_markdown(self.db,result.id);self.assertIn('직접 인용하지 않은 원문',exported);self.assertIn('학생입니다.',exported)

    async def test_source_sampling_is_frozen_and_legacy_requests_keep_defaults(self):
        from lecture_study.outputs import summarize_session
        request=self.request.model_copy(update={'kind':'summary'})
        frozen=await freeze_request(self.db,request);self.assertEqual(frozen['source_sampling'],'copy-v1')
        response=ProviderResult(text=json.dumps({'sections':[{'title':'정의','text':'프로세스 정의','subject_quote':'프로세스','subject_source_id':'s1','event_type':'fact','evidence_ids':['s1']}]}),model='test',usage={},elapsed_ms=1)
        for modern in (True,False):
            current=dict(frozen)
            if not modern:current.pop('source_sampling')
            job=submit_job(self.db,self.sid,'ai',current)
            with patch('lecture_study.outputs.generate',new=AsyncMock(return_value=response))as generated:await summarize_session(self.db,current,job['id'])
            self.assertEqual(generated.call_args.kwargs.get('source_copy',False),modern)

class ExperimentReuseTests(unittest.TestCase):
    def test_failed_experiment_cannot_reuse_maps_under_changed_policy(self):
        from experiments.validate_recording_assistance import assert_same_summary_request,completed_grounded_parts
        frozen={'source_sampling':'copy-v1','summary_instruction':'copy original subject'}
        old={'validated':False,'frozen_request':dict(frozen)}
        assert_same_summary_request(old,frozen)
        with self.assertRaises(AssertionError):completed_grounded_parts(old,frozen)
        for key in ('source_sampling','summary_instruction'):
            changed=dict(frozen);changed.pop(key)
            with self.assertRaises(AssertionError):assert_same_summary_request(old,changed)
        with self.assertRaises(KeyError):assert_same_summary_request({'validated':False},frozen)
