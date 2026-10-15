import asyncio
import json
import unittest
from unittest.mock import AsyncMock,patch
from tests import test_answers
from lecture_study.models import ProviderResult
from lecture_study.answers import freeze_request,get_artifact
from lecture_study.jobs import submit_job
from lecture_study.outputs import summarize_session,create_quiz,submit_attempt,override_attempt,public_artifact

class StudyTests(unittest.IsolatedAsyncioTestCase):
    setUp=test_answers.AnswerTests.setUp

    async def test_summary_covers_tail_and_resumes_completed_parts(self):
        from lecture_study.materials import save_note
        from lecture_study.audio import start_recording,append_pcm
        from lecture_study.transcription import plan_chunks,accept_transcription,list_transcripts
        save_note(self.db,self.sid,'\n\n'.join('프로세스의 설명 '+str(n)+' 내용입니다.'*20 for n in range(40)))
        rid=start_recording(self.db,self.sid,48000);append_pcm(self.db,rid,0,0,48000,b'\x00\x01'*48000)
        chunk=plan_chunks(self.db,rid,True)[0]
        accept_transcription(self.db,rid,chunk['id'],chunk['revision'],True,[{'start_ms':0,'end_ms':1000,'text':'후반부 고유 개념은 선점 스케줄링입니다.'}])
        tail=list_transcripts(self.db,self.sid)[0]['id']+':v1'
        request=self.request.model_copy(update={'kind':'summary','prompt':'전체 확정 기록 요약'})
        frozen=await freeze_request(self.db,request);frozen.pop('summary_grounding',None);job=submit_job(self.db,self.sid,'ai',frozen)
        calls=[];fail=True
        async def generate(config,messages,images,schema,**kw):
            nonlocal fail
            data=json.loads(messages[-1]['content']);calls.append(data)
            if fail and len(calls)==3: raise ValueError('중간 실패')
            if 'chronological_parts' in data:
                from lecture_study.merging import cited_ids
                content=json.dumps(data['chronological_parts'],ensure_ascii=False)
                sections=[{'title':'병합','text':'중복 설명을 병합했습니다.'+('후반부 고유 개념은 선점 스케줄링입니다.' if '후반부 고유 개념' in content else ''),'evidence_ids':sorted(cited_ids(data['chronological_parts']))}]
            else:sections=[{'title':'요약','text':e['text'][:120],'evidence_ids':[e['source_id']]} for e in data['evidence']]
            return ProviderResult(text=json.dumps({'sections':sections}),model=config.model,usage={'output_tokens':12},elapsed_ms=1)
        with patch('lecture_study.outputs.generate',new=generate):
            with self.assertRaisesRegex(ValueError,'중간 실패'): await summarize_session(self.db,frozen,job['id'],secret='test-key')
            completed=self.db.execute('SELECT count(*) FROM artifact_parts WHERE job_id=?',(job['id'],)).fetchone()[0]
            self.assertEqual(completed,2);first_calls=json.dumps(calls[:2],ensure_ascii=False);calls.clear();fail=False
            result=await summarize_session(self.db,frozen,job['id'],secret='test-key')
        self.assertEqual(len(calls),result.body['completed_parts']-completed+result.body['merge_steps'])
        self.assertIn(tail,{r['source_id'] for r in result.body['covered_ranges']})
        self.assertIn('후반부 고유 개념','\n'.join(s['text'] for s in result.body['sections']))
        self.assertEqual(self.db.execute('SELECT count(*) FROM artifacts WHERE job_id=?',(job['id'],)).fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM artifact_parts WHERE job_id=?',(job['id'],)).fetchone()[0],result.body['completed_parts']+result.body['merge_steps'])

    async def test_summary_does_not_send_source_labels_as_narrative(self):
        from lecture_study.models import Evidence
        from lecture_study.outputs import output_messages,SUMMARY_INSTRUCTION
        evidence=Evidence(ref=self.ref,text='바느질하다 손가락을 찔렀다.',label='긴 사람 음성 동시 실행 검증')
        for kind in ('summary','note'):
            request=self.request.model_copy(update={'kind':kind})
            data=json.loads(output_messages(request,[evidence],SUMMARY_INSTRUCTION)[-1]['content'])
            self.assertNotIn('label',data['evidence'][0])
            self.assertEqual(data['evidence'][0]['text'],evidence.text)
        self.assertEqual(evidence.label,'긴 사람 음성 동시 실행 검증')

    async def test_summary_schema_requires_citations_like_saved_sections(self):
        from lecture_study.outputs import SUMMARY_SCHEMA
        citations=SUMMARY_SCHEMA['properties']['sections']['items']['properties']['evidence_ids']
        self.assertEqual(citations.get('minItems'),1)
        self.assertEqual(citations.get('maxItems'),64)

    async def test_summary_parts_respect_budget_and_preserve_split_text(self):
        from lecture_study.models import Evidence
        from lecture_study.outputs import summary_parts,SUMMARY_SCHEMA,SUMMARY_INSTRUCTION,output_messages,check_budget
        from lecture_study.answers import evidence_schema
        request=self.request.model_copy(update={'kind':'summary','provider':self.request.provider.model_copy(update={'context_limit':8192})})
        evidence=[Evidence(ref=self.ref.model_copy(update={'id':f'chunk-{i}'}),text='한글과 숫자 123 정정 미확정. '*15,label=str(i)) for i in range(20)]
        evidence.append(Evidence(ref=self.ref.model_copy(update={'id':'large-source'}),text='긴 원문을 빠짐없이 보존합니다. '*400,label='끝'))
        parts=summary_parts(request,evidence);self.assertGreater(len(parts),1)
        restored={e.ref.id:'' for e in evidence}
        for part in parts:
            check_budget(request.provider,output_messages(request,part,SUMMARY_INSTRUCTION),evidence_schema(SUMMARY_SCHEMA,part))
            for e in part:restored[e.ref.id]+=e.text
        self.assertEqual(restored,{e.ref.id:e.text for e in evidence})

    async def test_summary_uses_short_aliases_and_restores_original_ids(self):
        request=self.request.model_copy(update={'kind':'summary','prompt':'전체 요약'})
        frozen=await freeze_request(self.db,request);frozen.pop('summary_grounding',None);job=submit_job(self.db,self.sid,'ai',frozen)
        async def generated(config,messages,images,schema,**kw):
            ids=[e['source_id'] for e in json.loads(messages[-1]['content'])['evidence']]
            self.assertEqual(ids,['s1'])
            return ProviderResult(text=json.dumps({'sections':[{'title':'정의','text':'프로그램','evidence_ids':ids}]}),model='test',usage={},elapsed_ms=1)
        with patch('lecture_study.outputs.generate',new=generated):result=await summarize_session(self.db,frozen,job['id'])
        self.assertEqual(result.body['sections'][0]['evidence_ids'],[self.ref.id])

    async def test_legacy_summary_rejects_missing_source_in_batch(self):
        from lecture_study.audio import start_recording,append_pcm
        from lecture_study.transcription import plan_chunks,accept_transcription
        rid=start_recording(self.db,self.sid,48000);append_pcm(self.db,rid,0,0,48000,b'\x00\x01'*48000)
        chunk=plan_chunks(self.db,rid,True)[0]
        accept_transcription(self.db,rid,chunk['id'],chunk['revision'],True,[{'start_ms':0,'end_ms':500,'text':'금요일 네 대 설치 제안입니다.'},{'start_ms':500,'end_ms':1000,'text':'월요일 세 대로 정정했지만 미확정입니다.'}])
        request=self.request.model_copy(update={'kind':'summary','prompt':'전체 요약','provider':self.request.provider.model_copy(update={'context_limit':16384})})
        original=await freeze_request(self.db,request);original.pop('summary_policy');original.pop('summary_grounding',None);original['summary_parts']=[original['evidence']];self.assertGreater(len(original['summary_parts'][0]),1)
        for provider,expected_calls in (('openai',1),('ollama',1)):
            frozen=json.loads(json.dumps(original));frozen['request']['provider']['provider']=provider
            job=submit_job(self.db,self.sid,'ai',frozen);calls=[]
            async def generated(config,messages,images,schema,**kw):
                calls.append(messages);ident=json.loads(messages[-1]['content'])['evidence'][0]['source_id']
                return ProviderResult(text=json.dumps({'sections':[{'title':'초기 제안','text':'금요일 네 대 설치 제안','evidence_ids':[ident]}]}),model='test',usage={},elapsed_ms=1)
            with patch('lecture_study.outputs.generate',new=generated):
                with self.assertRaisesRegex(ValueError,'근거가 누락'):await summarize_session(self.db,frozen,job['id'])
            self.assertEqual(len(calls),expected_calls)
            self.assertEqual(self.db.execute('SELECT count(*) FROM artifact_parts WHERE job_id=?',(job['id'],)).fetchone()[0],0)

    async def test_summary_aliases_are_unique_across_parts(self):
        from lecture_study.audio import start_recording,append_pcm
        from lecture_study.transcription import plan_chunks,accept_transcription
        rid=start_recording(self.db,self.sid,48000);append_pcm(self.db,rid,0,0,48000,b'\x00\x01'*48000)
        chunk=plan_chunks(self.db,rid,True)[0]
        accept_transcription(self.db,rid,chunk['id'],chunk['revision'],True,[{'start_ms':i*100,'end_ms':(i+1)*100,'text':f'내용 {i}'} for i in range(9)])
        request=self.request.model_copy(update={'kind':'summary','provider':self.request.provider.model_copy(update={'context_limit':16384})})
        frozen=await freeze_request(self.db,request);frozen.pop('summary_grounding',None);job=submit_job(self.db,self.sid,'ai',frozen);seen=set()
        async def generated(config,messages,images,schema,**kw):
            data=json.loads(messages[-1]['content'])
            if 'evidence' in data:
                ids=[e['source_id'] for e in data['evidence']];self.assertFalse(seen.intersection(ids));seen.update(ids)
            else:
                from lecture_study.merging import cited_ids
                ids=sorted(cited_ids(data['chronological_parts']))
            return ProviderResult(text=json.dumps({'sections':[{'title':'내용','text':'핵심 내용','evidence_ids':ids[i:i+6]}for i in range(0,len(ids),6)]}),model='test',usage={},elapsed_ms=1)
        with patch('lecture_study.outputs.generate',new=generated):await summarize_session(self.db,frozen,job['id'])
        self.assertEqual(seen,{'s'+str(i+1) for i in range(len(frozen['evidence']))})

    async def test_merge_subset_keeps_global_alias_numbers(self):
        from lecture_study.audio import start_recording,append_pcm
        from lecture_study.transcription import plan_chunks,accept_transcription
        from lecture_study.merging import merge_generated,cited_ids
        rid=start_recording(self.db,self.sid,48000);append_pcm(self.db,rid,0,0,48000,b'\x00\x01'*48000)
        chunk=plan_chunks(self.db,rid,True)[0]
        accept_transcription(self.db,rid,chunk['id'],chunk['revision'],True,[{'start_ms':0,'end_ms':500,'text':'초기 제안'},{'start_ms':500,'end_ms':1000,'text':'후반 정정'}])
        request=self.request.model_copy(update={'kind':'summary'});frozen=await freeze_request(self.db,request);frozen.pop('summary_grounding',None);job=submit_job(self.db,self.sid,'ai',frozen)
        ids=[e['ref']['id'] for e in frozen['evidence']];pieces=[{'sections':[{'title':'내용','text':'근거 [s'+str(i+1)+']','evidence_ids':[ids[i]]}]} for i in (1,2)]
        async def generated(config,messages,images,schema,**kw):
            data=json.loads(messages[-1]['content']);self.assertEqual(cited_ids(data['chronological_parts']),{'s2','s3'})
            return ProviderResult(text=json.dumps({'sections':[{'title':'내용','text':'근거 [s2], [s3]','evidence_ids':['s2','s3']}]}),model='test',usage={},elapsed_ms=1)
        with patch('lecture_study.outputs.generate',new=generated):body,_=await merge_generated(self.db,frozen,job['id'],pieces,'summary')
        self.assertEqual(cited_ids(body),set(ids[1:]))

    async def test_summary_schema_limits_each_part_to_its_supplied_sources(self):
        request=self.request.model_copy(update={'kind':'summary','prompt':'전체 요약'})
        frozen=await freeze_request(self.db,request);frozen.pop('summary_grounding',None);job=submit_job(self.db,self.sid,'ai',frozen)
        async def generated(config,messages,images,schema,**kw):
            ids=[e['source_id'] for e in json.loads(messages[-1]['content'])['evidence']]
            self.assertIn('question은 사용자의 요청',messages[0]['content'])
            self.assertIn('evidence의 text만',messages[0]['content'])
            self.assertIn('실제로 사용한 근거 ID',messages[0]['content'])
            self.assertEqual(schema['properties']['sections']['items']['properties']['evidence_ids']['items']['enum'],ids)
            return ProviderResult(text=json.dumps({'sections':[{'title':'정의','text':'프로그램','evidence_ids':ids}]}),model='test',usage={},elapsed_ms=1)
        with patch('lecture_study.outputs.generate',new=generated):await summarize_session(self.db,frozen,job['id'])

    async def test_quiz_schema_separates_choice_and_free_question_contracts(self):
        request=self.request.model_copy(update={'kind':'quiz','prompt':'프로세스 5문제'})
        frozen=await freeze_request(self.db,request);frozen.pop('summary_grounding',None);job=submit_job(self.db,self.sid,'ai',frozen)
        q={'kind':'free','prompt':'정의','options':[],'answer':'프로그램','rubric':'기준','explanation':'해설','evidence_ids':[self.ref.id],'concept_ids':[]}
        with patch('lecture_study.outputs.generate',new=AsyncMock(return_value=ProviderResult(text=json.dumps({'questions':[q]*5}),model='test',usage={},elapsed_ms=1))) as generate:
            await create_quiz(self.db,frozen,job['id'])
        questions=generate.call_args.args[3]['properties']['questions']
        self.assertEqual(questions['minItems'],5);self.assertEqual(questions['maxItems'],5)
        branches=questions['items']['anyOf']
        free=next(b for b in branches if b['properties']['kind']['enum']==['free'])
        choice=next(b for b in branches if b['properties']['kind']['enum']==['choice'])
        self.assertEqual(free['properties']['options']['maxItems'],0)
        self.assertEqual(choice['properties']['options']['minItems'],2)
        self.assertEqual(choice['properties']['answer']['enum'],list('ABCDEF'))

    async def test_default_quiz_budget_counts_constrained_schema_before_excerpting(self):
        from lecture_study.materials import save_note
        from lecture_study.models import Evidence
        from lecture_study.outputs import output_messages,check_budget,QUIZ_SCHEMA,QUIZ_INSTRUCTION
        from lecture_study.answers import evidence_schema
        save_note(self.db,self.sid,'프로세스의 내용을 설명합니다. '*100)
        request=self.request.model_copy(update={'kind':'quiz','prompt':'프로세스 5문제','provider':self.request.provider.model_copy(update={'context_limit':8192})})
        frozen=await freeze_request(self.db,request);evidence=[Evidence.model_validate(e) for e in frozen['evidence']]
        schema=evidence_schema(QUIZ_SCHEMA,evidence)
        for branch in schema['properties']['questions']['items']['anyOf']:branch['properties']['concept_ids']['maxItems']=0
        check_budget(request.provider,output_messages(request,evidence,QUIZ_INSTRUCTION,{'concepts':[]}),schema)
        self.assertTrue(frozen['excerpted'])

    async def test_quiz_answers_hidden_attempts_and_override_keep_original(self):
        request=self.request.model_copy(update={'kind':'quiz','prompt':'프로세스의 핵심 내용 5문제'})
        frozen=await freeze_request(self.db,request);frozen.pop('summary_grounding',None);job=submit_job(self.db,self.sid,'ai',frozen)
        questions=[{'kind':'choice','prompt':'프로세스 정의는?','options':['실행 중인 프로그램','파일'],'answer':'A','rubric':'정의 일치','explanation':'실행 중인 프로그램입니다.','evidence_ids':[self.ref.id],'concept_ids':[]} for _ in range(5)]
        result=ProviderResult(text=json.dumps({'questions':questions}),model='gpt-4.1-mini',usage={},elapsed_ms=1)
        with patch('lecture_study.outputs.generate',new=AsyncMock(return_value=result)) as generate:
            quiz=await create_quiz(self.db,frozen,job['id'],secret='test-key')
            public=public_artifact(self.db,quiz.id)
            self.assertNotIn('answer',public['body']['questions'][0]);self.assertNotIn('rubric',public['body']['questions'][0])
            qid=quiz.body['questions'][0]['id']
            first=await submit_attempt(self.db,quiz.id,qid,'B')
            self.assertEqual(first['grade'],'incorrect')
            second=await submit_attempt(self.db,quiz.id,qid,'A')
            self.assertNotEqual(first['id'],second['id']);self.assertEqual(second['grade'],'correct')
            changed=override_attempt(self.db,first['id'],'partial','검토 후 수정')
            self.assertTrue(changed['overridden']);self.assertEqual(changed['original_grade'],'incorrect')
            self.assertEqual(changed['grade'],'partial');self.assertEqual(len(changed['history']),1)
            self.assertEqual(public_artifact(self.db,quiz.id)['body']['questions'][0]['answer'],'A')
            get_artifact(self.db,quiz.id);self.assertEqual(generate.await_count,1)

    async def test_free_grading_uses_saved_rubric_and_rejects_out_of_scope_concepts(self):
        from lecture_study.retrieval import save_term
        concept=save_term(self.db,self.sid,'프로세스',[],'개인 정의',[self.ref])
        request=self.request.model_copy(update={'kind':'quiz','prompt':'프로세스 5문제'})
        frozen=await freeze_request(self.db,request);frozen.pop('summary_grounding',None);job=submit_job(self.db,self.sid,'ai',frozen)
        question={'kind':'free','prompt':'프로세스를 정의하라','options':[],'answer':'실행 중인 프로그램','rubric':'실행 중이라는 점과 프로그램을 포함','explanation':'원문 정의','evidence_ids':[self.ref.id],'concept_ids':['invented']}
        with patch('lecture_study.outputs.generate',new=AsyncMock(return_value=ProviderResult(text=json.dumps({'questions':[question]*5}),model='gpt-4.1-mini',usage={},elapsed_ms=1))):
            with self.assertRaisesRegex(ValueError,'개념'): await create_quiz(self.db,frozen,job['id'],secret='test-key')
        question['concept_ids']=[concept]
        with patch('lecture_study.outputs.generate',new=AsyncMock(return_value=ProviderResult(text=json.dumps({'questions':[question]*5}),model='gpt-4.1-mini',usage={},elapsed_ms=1))):
            quiz=await create_quiz(self.db,frozen,job['id'],secret='test-key')
        grade=ProviderResult(text=json.dumps({'grade':'correct','explanation':'정의에 부합','evidence_ids':[self.ref.id]}),model='gpt-4.1-mini',usage={'input_tokens':30},elapsed_ms=2)
        with patch('lecture_study.outputs.generate',new=AsyncMock(return_value=grade)) as generate:
            attempt=await submit_attempt(self.db,quiz.id,quiz.body['questions'][0]['id'],'실행 중인 프로그램',provider=request.provider,secret='test-key')
            self.assertIn(question['rubric'],generate.call_args.args[1][-1]['content']);self.assertEqual(attempt['grade'],'correct')

    async def test_failed_free_grading_preserves_answer_and_cancel_marks_attempt(self):
        request=self.request.model_copy(update={'kind':'quiz','prompt':'프로세스 5문제'})
        frozen=await freeze_request(self.db,request);frozen.pop('summary_grounding',None);job=submit_job(self.db,self.sid,'ai',frozen)
        q={'kind':'free','prompt':'정의','options':[],'answer':'실행 중인 프로그램','rubric':'실행과 프로그램','explanation':'근거 설명','evidence_ids':[self.ref.id],'concept_ids':[]}
        with patch('lecture_study.outputs.generate',new=AsyncMock(return_value=ProviderResult(text=json.dumps({'questions':[q]*5}),model='test',usage={},elapsed_ms=1))):
            quiz=await create_quiz(self.db,frozen,job['id'])
        with patch('lecture_study.outputs.generate',new=AsyncMock(side_effect=ValueError('모델 연결 끊김'))):
            attempt=await submit_attempt(self.db,quiz.id,quiz.body['questions'][0]['id'],'제출한 답안',provider=request.provider)
        self.assertEqual(attempt['status'],'failed');self.assertEqual(attempt['submitted_answer'],'제출한 답안')
        changed=override_attempt(self.db,attempt['id'],'partial','수동 검토');self.assertIsNone(changed['original_grade'])
        with patch('lecture_study.outputs.generate',new=AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError): await submit_attempt(self.db,quiz.id,quiz.body['questions'][1]['id'],'취소 중 답안',provider=request.provider)
        self.assertEqual(self.db.execute("SELECT status FROM attempts WHERE submitted_answer='취소 중 답안'").fetchone()[0],'cancelled')

    async def test_quiz_public_api_and_concept_hide_solutions_until_attempt(self):
        import httpx,tempfile
        from pathlib import Path
        from lecture_study.server import create_app
        from lecture_study.config import AppConfig
        from lecture_study.db import create_session
        from lecture_study.materials import save_note
        from lecture_study.retrieval import save_term
        with tempfile.TemporaryDirectory() as folder:
            app=create_app(AppConfig(Path(folder),Path(folder)/'runtime',port=8765));db=app.state.db
            sid=create_session(db,'lecture','시험',None,None).id;ref=save_note(db,sid,'프로세스는 실행 중인 프로그램입니다.')
            term=save_term(db,sid,'프로세스',[],'정의',[ref]);q={'kind':'choice','prompt':'정의?','options':['프로그램','파일'],'answer':'A','rubric':'정의','explanation':'정답 비밀 해설','evidence_ids':[ref.id],'concept_ids':[term]}
            app.state.ollama_url='http://127.0.0.1:11435'
            try:
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:8765') as client:
                    origin={'Origin':'http://127.0.0.1:8765'};login=await client.post('/api/bootstrap',json={'token':app.state.bootstrap_token},headers=origin);headers=origin|{'X-Session-Token':login.json()['csrf_token']}
                    with patch('lecture_study.outputs.generate',new=AsyncMock(return_value=ProviderResult(text=json.dumps({'questions':[q]*5}),model='test',usage={},elapsed_ms=1))) as generate:
                        submitted=await client.post('/api/ai/jobs',json={'session_id':sid,'kind':'quiz','prompt':'프로세스 5문제','scope':{'session_id':sid}},headers=headers);self.assertEqual(submitted.status_code,202,submitted.text)
                        jid=submitted.json()['id']
                        for _ in range(100):
                            job=(await client.get('/api/jobs/'+jid)).json()
                            if job['status']=='done': break
                            await asyncio.sleep(.001)
                        self.assertEqual(job['status'],'done',job);self.assertEqual(set(job['result']),{'id','kind'})
                        aid=job['result']['id']
                        for path in ('/api/artifacts/'+aid,'/api/sessions/'+sid+'/artifacts','/api/sessions/'+sid+'/terms/'+term):
                            response=await client.get(path);self.assertEqual(response.status_code,200);self.assertNotIn('정답 비밀 해설',response.text);self.assertNotIn('"answer":"A"',response.text)
                        quiz=(await client.get('/api/artifacts/'+aid)).json();qid=quiz['body']['questions'][0]['id']
                        rejected=await client.post('/api/quizzes/'+aid+'/attempts',json={'question_id':qid,'answer':'AB'},headers=headers);self.assertEqual(rejected.status_code,422)
                        submitted=await client.post('/api/quizzes/'+aid+'/attempts',json={'question_id':qid,'answer':'B'},headers=headers);self.assertEqual(submitted.json()['grade'],'incorrect')
                        review=(await client.get('/api/sessions/'+sid+'/review')).json();self.assertEqual(len(review),1)
                        saved=(await client.get('/api/artifacts/'+aid)).json();self.assertEqual(saved['body']['questions'][0]['answer'],'A');self.assertNotIn('answer',saved['body']['questions'][1]);self.assertEqual(generate.await_count,1)
            finally:
                for task in list(app.state.tasks): task.cancel()
                await asyncio.gather(*app.state.tasks,return_exceptions=True);db.close()

    async def test_summary_partition_is_frozen_when_retry_model_budget_changes(self):
        from lecture_study.materials import save_note
        save_note(self.db,self.sid,'프로세스 후반 내용입니다. '*200)
        request=self.request.model_copy(update={'kind':'summary','prompt':'전체 요약'})
        frozen=await freeze_request(self.db,request);frozen.pop('summary_grounding',None);job=submit_job(self.db,self.sid,'ai',frozen)
        original=json.dumps(frozen['summary_parts'],ensure_ascii=False)
        frozen['request']['provider']['context_limit']=20000
        with patch('lecture_study.outputs.generate',new=AsyncMock(side_effect=ValueError('의도한 중단'))):
            with self.assertRaisesRegex(ValueError,'의도한'): await summarize_session(self.db,frozen,job['id'])
        self.assertEqual(json.dumps(frozen['summary_parts'],ensure_ascii=False),original)

    async def test_default_quiz_scope_works_before_embeddings_and_choice_needs_no_key(self):
        request=self.request.model_copy(update={'kind':'quiz','prompt':'핵심 내용을 복습할 5문제를 만드세요.'})
        frozen=await freeze_request(self.db,request);self.assertIn(self.ref.id,{e['ref']['id'] for e in frozen['evidence']});job=submit_job(self.db,self.sid,'ai',frozen)
        q={'kind':'choice','prompt':'정의','options':['프로그램','파일'],'answer':'A','rubric':'정의','explanation':'해설','evidence_ids':[self.ref.id],'concept_ids':[]}
        with patch('lecture_study.outputs.generate',new=AsyncMock(return_value=ProviderResult(text=json.dumps({'questions':[q]*5}),model='test',digest='a'*64,usage={},elapsed_ms=1))):quiz=await create_quiz(self.db,frozen,job['id'])
        def unavailable(*a):raise ValueError('OS 키 저장소 잠김')
        locked=asyncio.Semaphore(0)
        attempt=await asyncio.wait_for(submit_attempt(self.db,quiz.id,quiz.body['questions'][0]['id'],'A',provider=request.provider,secret_loader=unavailable,generation_lock=locked),.1)
        self.assertEqual(attempt['grade'],'correct');self.assertEqual(get_artifact(self.db,quiz.id)['metadata']['digest'],'a'*64)

    async def test_free_key_read_failure_keeps_submitted_answer(self):
        request=self.request.model_copy(update={'kind':'quiz','prompt':'프로세스 5문제'});frozen=await freeze_request(self.db,request);frozen.pop('summary_grounding',None);job=submit_job(self.db,self.sid,'ai',frozen)
        q={'kind':'free','prompt':'정의','options':[],'answer':'프로그램','rubric':'기준','explanation':'해설','evidence_ids':[self.ref.id],'concept_ids':[]}
        with patch('lecture_study.outputs.generate',new=AsyncMock(return_value=ProviderResult(text=json.dumps({'questions':[q]*5}),model='test',usage={},elapsed_ms=1))):quiz=await create_quiz(self.db,frozen,job['id'])
        def locked(*args):raise ValueError('OS 자격증명 저장소 잠김')
        attempt=await submit_attempt(self.db,quiz.id,quiz.body['questions'][0]['id'],'사용자 답안',provider=request.provider,secret_loader=locked,generation_lock=asyncio.Semaphore(1))
        self.assertEqual(attempt['submitted_answer'],'사용자 답안');self.assertEqual(attempt['status'],'failed');self.assertIn('저장소',attempt['error'])
