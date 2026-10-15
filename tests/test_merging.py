import json,unittest
from unittest.mock import AsyncMock,patch
from tests import test_answers
from lecture_study.models import Evidence,AIRequest,Scope,ProviderResult
from lecture_study.materials import save_note
from lecture_study.jobs import submit_job
from lecture_study.merging import remap_ids

class MergeTests(unittest.IsolatedAsyncioTestCase):
    setUp=test_answers.AnswerTests.setUp
    async def test_merge_keeps_correction_sources_and_reuses_completed_merge(self):
        from lecture_study.merging import merge_generated
        other=save_note(self.db,self.sid,'정정: 금요일 4개가 아니라 월요일 3개입니다. 아직 제안입니다.')
        request=AIRequest(session_id=self.sid,kind='summary',prompt='전체 요약',scope=Scope(session_id=self.sid),provider=self.request.provider)
        evidence=[Evidence(ref=self.ref,text='프로세스는 실행 중인 프로그램입니다.',label='이전'),Evidence(ref=other,text='정정: 금요일 4개가 아니라 월요일 3개입니다. 아직 제안입니다.',label='후반 정정')]
        frozen={'request':request.model_dump(),'evidence':[e.model_dump() for e in evidence]};job=submit_job(self.db,self.sid,'ai',frozen)
        pieces=[{'sections':[{'title':'처음 설명','text':'금요일 4개로 제안','evidence_ids':[self.ref.id]}]},{'sections':[{'title':'정정','text':'월요일 3개로 정정. 아직 확정 아님.','evidence_ids':[other.id]}]}]
        body={'sections':[{'title':'정정 경위','text':'초기 금요일 4개 제안은 월요일 3개로 정정되었으며 아직 확정이 아니다.','evidence_ids':[self.ref.id,other.id]}]}
        generated=AsyncMock(return_value=ProviderResult(text=json.dumps(remap_ids(body,{self.ref.id:'s1',other.id:'s2'})),model='test',usage={},elapsed_ms=1))
        with patch('lecture_study.outputs.generate',new=generated):
            result,infos=await merge_generated(self.db,frozen,job['id'],pieces,'summary')
            repeated,_=await merge_generated(self.db,frozen,job['id'],pieces,'summary')
        self.assertEqual(result,body);self.assertEqual(repeated,body);self.assertEqual(generated.await_count,1)
        self.assertEqual(len(infos),1)
        messages=generated.call_args.args[1]
        self.assertIn('정정',messages[0]['content']);self.assertIn('금요일 4개',messages[1]['content']);self.assertIn('월요일 3개',messages[1]['content'])
    async def test_merge_rejects_lost_source_and_keeps_original_parts(self):
        from lecture_study.merging import merge_generated
        other=save_note(self.db,self.sid,'후반 내용')
        request=AIRequest(session_id=self.sid,kind='summary',prompt='요약',scope=Scope(session_id=self.sid),provider=self.request.provider)
        evidence=[Evidence(ref=self.ref,text='프로세스는 실행 중인 프로그램입니다.',label='처음'),Evidence(ref=other,text='후반 내용',label='후반')]
        frozen={'request':request.model_dump(),'evidence':[e.model_dump() for e in evidence]};job=submit_job(self.db,self.sid,'ai',frozen)
        pieces=[{'sections':[{'title':'처음','text':'처음','evidence_ids':[self.ref.id]}]},{'sections':[{'title':'후반','text':'후반','evidence_ids':[other.id]}]}]
        bad={'sections':[{'title':'누락','text':'후반 정정 없음','evidence_ids':[self.ref.id]}]}
        with patch('lecture_study.outputs.generate',new=AsyncMock(return_value=ProviderResult(text=json.dumps(remap_ids(bad,{self.ref.id:'s1',other.id:'s2'})),model='test',usage={},elapsed_ms=1))):
            with self.assertRaisesRegex(ValueError,'누락'):await merge_generated(self.db,frozen,job['id'],pieces,'summary')
        self.assertEqual(pieces[1]['sections'][0]['text'],'후반')
        self.assertEqual(self.db.execute('SELECT count(*) FROM artifact_parts').fetchone()[0],0)

    async def test_twenty_distinct_citations_fit_default_budget(self):
        from lecture_study.merging import merge_generated,cited_ids
        refs=[save_note(self.db,self.sid,'구간 '+str(n)) for n in range(20)]
        evidence=[Evidence(ref=r,text='구간 '+str(n),label='구간') for n,r in enumerate(refs)]
        request=AIRequest(session_id=self.sid,kind='summary',prompt='요약',scope=Scope(session_id=self.sid),provider=self.request.provider.model_copy(update={'context_limit':8192}))
        frozen={'request':request.model_dump(),'evidence':[e.model_dump() for e in evidence]};job=submit_job(self.db,self.sid,'ai',frozen)
        pieces=[{'sections':[{'title':'주제','text':'짧은 내용','evidence_ids':[r.id]}]} for r in refs]
        async def reduced(config,messages,images,schema,**kwargs):
            from lecture_study.outputs import check_budget
            check_budget(config,messages,schema)
            data=json.loads(messages[1]['content']);ids=sorted(cited_ids(data['chronological_parts']))
            return ProviderResult(text=json.dumps({'sections':[{'title':'병합','text':'요약','evidence_ids':ids}]}),model='test',usage={},elapsed_ms=1)
        with patch('lecture_study.outputs.generate',new=reduced):result,_=await merge_generated(self.db,frozen,job['id'],pieces,'summary')
        self.assertEqual(cited_ids(result),{r.id for r in refs})

    async def test_completed_merge_survives_later_failure_and_retry(self):
        from lecture_study.merging import merge_generated,cited_ids
        from lecture_study.outputs import check_budget as original_budget
        refs=[save_note(self.db,self.sid,'구간 '+str(n)) for n in range(4)]
        evidence=[Evidence(ref=r,text='구간 '+str(n),label='구간') for n,r in enumerate(refs)]
        request=AIRequest(session_id=self.sid,kind='summary',prompt='요약',scope=Scope(session_id=self.sid),provider=self.request.provider)
        frozen={'request':request.model_dump(),'evidence':[e.model_dump() for e in evidence]};job=submit_job(self.db,self.sid,'ai',frozen)
        pieces=[{'sections':[{'title':'주제','text':'내용','evidence_ids':[r.id]}]} for r in refs];calls=0
        def budget(config,messages,schema):
            if len(json.loads(messages[1]['content'])['chronological_parts'])>2:raise ValueError('fixture input bound')
            original_budget(config,messages,schema)
        async def generated(config,messages,*args,**kwargs):
            nonlocal calls
            calls+=1
            if calls==2:raise ValueError('fixture provider failure')
            ids=sorted(cited_ids(json.loads(messages[1]['content'])))
            return ProviderResult(text=json.dumps({'sections':[{'title':'병합','text':'내용','evidence_ids':ids}]}),model='test',usage={},elapsed_ms=1)
        with patch('lecture_study.outputs.check_budget',new=budget),patch('lecture_study.outputs.generate',new=generated):
            with self.assertRaisesRegex(ValueError,'provider failure'):await merge_generated(self.db,frozen,job['id'],pieces,'summary')
            self.assertEqual(self.db.execute('SELECT count(*) FROM artifact_parts').fetchone()[0],1)
            result,infos=await merge_generated(self.db,frozen,job['id'],pieces,'summary')
        self.assertEqual(calls,4);self.assertEqual(len(infos),3);self.assertEqual(cited_ids(result),{r.id for r in refs})

    async def test_minutes_merge_still_validates_original_quotes(self):
        from tests.test_assistance import AssistanceTests
        from lecture_study.answers import freeze_request
        from lecture_study.merging import merge_generated
        with self.db:self.db.execute("UPDATE sessions SET kind='meeting' WHERE id=?",(self.sid,))
        tid=AssistanceTests.speech(self)
        request=AIRequest(session_id=self.sid,kind='minutes',prompt='회의록',scope=Scope(session_id=self.sid),provider=self.request.provider)
        frozen=await freeze_request(self.db,request);job=submit_job(self.db,self.sid,'ai',frozen)
        piece={'topics':[{'title':'질문','text':'공유 자원 접근','evidence_ids':[tid]}],'decisions':[],'actions':[],'unresolved':[]}
        body=remap_ids(piece,{tid:'s1'})|{'decisions':[{'text':'결정','quote':'확정하기로 결정했습니다.','evidence_ids':['s1']}]}
        with patch('lecture_study.outputs.generate',new=AsyncMock(return_value=ProviderResult(text=json.dumps(body),model='test',usage={},elapsed_ms=1))):
            with self.assertRaisesRegex(ValueError,'결정'):await merge_generated(self.db,frozen,job['id'],[piece,piece],'minutes')
        self.assertEqual(self.db.execute('SELECT count(*) FROM artifact_parts').fetchone()[0],0)

    async def test_selective_merge_bounds_sections_and_citations(self):
        from lecture_study.merging import merge_generated
        refs=[save_note(self.db,self.sid,'근거 '+str(n)) for n in range(7)]
        evidence=[Evidence(ref=r,text='근거 '+str(n),label='원문')for n,r in enumerate(refs)]
        request=self.request.model_copy(update={'kind':'summary'})
        frozen={'request':request.model_dump(),'evidence':[e.model_dump()for e in evidence],'summary_policy':'context-v1'};job=submit_job(self.db,self.sid,'ai',frozen)
        pieces=[{'sections':[{'title':'원문','text':'원문','evidence_ids':[r.id]}]}for r in refs]
        bad={'sections':[{'title':'너무 긴 인용','text':'요약','evidence_ids':['s'+str(n+1)for n in range(7)]}]}
        with patch('lecture_study.outputs.generate',new=AsyncMock(return_value=ProviderResult(text=json.dumps(bad),model='test',usage={},elapsed_ms=1)))as generated:
            with self.assertRaisesRegex(ValueError,'너무 길'):await merge_generated(self.db,frozen,job['id'],pieces,'summary')
        schema=generated.call_args.args[3]
        self.assertEqual(schema['properties']['sections']['maxItems'],6)
        self.assertEqual(schema['properties']['sections']['items']['properties']['evidence_ids']['maxItems'],6)
        self.assertEqual(self.db.execute('SELECT count(*) FROM artifact_parts WHERE job_id=?',(job['id'],)).fetchone()[0],0)
