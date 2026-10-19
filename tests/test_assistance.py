import json,unittest
from unittest.mock import AsyncMock,patch
from tests import test_answers
from lecture_study.models import AIRequest,Scope,ProviderResult
from lecture_study.answers import freeze_request,run_ai_request,get_artifact
from lecture_study.materials import save_note,list_materials
from lecture_study.jobs import submit_job
from lecture_study.audio import start_recording,append_pcm
from lecture_study.transcription import plan_chunks,accept_transcription,list_transcripts

class AssistanceTests(unittest.IsolatedAsyncioTestCase):
    setUp=test_answers.AnswerTests.setUp
    def speech(self):
        rid=start_recording(self.db,self.sid,48000);append_pcm(self.db,rid,0,0,48000,b'\0\1'*48000)
        chunk=plan_chunks(self.db,rid,True)[0]
        accept_transcription(self.db,rid,chunk['id'],chunk['revision'],True,[{'start_ms':0,'end_ms':1000,'text':'뮤텍스와 세마포어는 어떻게 다른가요? 공유 자원의 접근을 제어합니다.'}])
        return list_transcripts(self.db,self.sid)[0]['id']+':v1'
    def request_for(self,kind,**extra):
        return AIRequest(session_id=self.sid,kind=kind,prompt='확정 근거로 작성하세요',scope=Scope(session_id=self.sid,mode='current'),provider=self.request.provider,**extra)
    async def test_note_anchor_freeze_apply_and_stale_edit_guard(self):
        from lecture_study.assistance import apply_note
        tid=self.speech();note=save_note(self.db,self.sid,'뮤텍스/세마포어 차이')
        self.assertEqual(list_materials(self.db,self.sid)['note']['anchor_ms'],1000)
        frozen=await freeze_request(self.db,self.request_for('note',note_source_id=note.id))
        self.assertEqual({e['ref']['id'] for e in frozen['evidence']},{note.id,tid})
        job=submit_job(self.db,self.sid,'ai',frozen)
        body={'addition':'공유 자원의 접근을 제어하는 차이를 확인한다.','evidence_ids':[tid]}
        with patch('lecture_study.assistance.generate',new=AsyncMock(return_value=ProviderResult(text=json.dumps(body),model='test',usage={},elapsed_ms=1))):
            result=await run_ai_request(self.db,frozen,job['id'])
        self.assertEqual(list_materials(self.db,self.sid)['note']['source_id'],note.id)
        applied=apply_note(self.db,result.id,'사용자가 고친 보강 내용');self.assertEqual(apply_note(self.db,result.id,body['addition']),applied)
        saved=get_artifact(self.db,result.id)
        self.assertEqual(saved['body']['addition'],'사용자가 고친 보강 내용')
        self.assertEqual(saved['metadata']['original_addition'],body['addition'])
        from lecture_study.outputs import export_markdown
        self.assertIn('사용자가 고친 보강 내용',export_markdown(self.db,result.id))
        self.assertTrue(applied['text'].startswith('뮤텍스/세마포어 차이\n\n'))
        self.assertEqual(self.db.execute('SELECT text FROM notes WHERE version=?',(note.version,)).fetchone()[0],'뮤텍스/세마포어 차이')
        another=submit_job(self.db,self.sid,'ai',frozen)
        with patch('lecture_study.assistance.generate',new=AsyncMock(return_value=ProviderResult(text=json.dumps(body),model='test',usage={},elapsed_ms=1))):result=await run_ai_request(self.db,frozen,another['id'])
        with self.assertRaisesRegex(ValueError,'변경'):apply_note(self.db,result.id,'덮어쓰면 안 됨')
    async def test_candidates_only_final_transcripts_exact_quotes_and_empty_allowed(self):
        tid=self.speech();frozen=await freeze_request(self.db,self.request_for('candidates'))
        self.assertEqual([e['ref']['id'] for e in frozen['evidence']],[tid])
        job=submit_job(self.db,self.sid,'ai',frozen)
        body={'cards':[{'prompt':'뮤텍스와 세마포어의 차이는?','quote':'뮤텍스와 세마포어는 어떻게 다른가요?','source_id':tid}]}
        with patch('lecture_study.assistance.generate',new=AsyncMock(return_value=ProviderResult(text=json.dumps(body),model='test',usage={},elapsed_ms=1))):result=await run_ai_request(self.db,frozen,job['id'])
        self.assertEqual(len(result.body['cards']),1)
        with self.db:self.db.execute("UPDATE jobs SET status='done' WHERE id=?",(job['id'],))
        body['cards'][0]['quote']='전사에 없는 문장'
        job=submit_job(self.db,self.sid,'ai',frozen)
        with patch('lecture_study.assistance.generate',new=AsyncMock(return_value=ProviderResult(text=json.dumps(body),model='test',usage={},elapsed_ms=1))):
            with self.assertRaisesRegex(ValueError,'인용'):await run_ai_request(self.db,frozen,job['id'])
        with self.db:self.db.execute("UPDATE jobs SET status='failed' WHERE id=?",(job['id'],))
        body={'cards':[]};job=submit_job(self.db,self.sid,'ai',frozen)
        with patch('lecture_study.assistance.generate',new=AsyncMock(return_value=ProviderResult(text=json.dumps(body),model='test',usage={},elapsed_ms=1))):result=await run_ai_request(self.db,frozen,job['id'])
        self.assertEqual(result.body['cards'],[])
    async def test_note_without_anchor_and_foreign_scope_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'시점'):await freeze_request(self.db,self.request_for('note',note_source_id=self.ref.id))
        self.speech()
        request=self.request_for('candidates').model_copy(update={'scope':self.request_for('candidates').scope.model_copy(update={'mode':'course'})})
        with self.assertRaisesRegex(ValueError,'현재 기록'):await freeze_request(self.db,request)

    async def test_candidate_admission_reaches_generic_submit_and_retry(self):
        from lecture_study.jobs import active_candidate
        frozen={'request':self.request_for('candidates').model_dump()}
        old=submit_job(self.db,self.sid,'ai',frozen)
        with self.db:self.db.execute("UPDATE jobs SET status='failed' WHERE id=?",(old['id'],))
        new=submit_job(self.db,self.sid,'ai',frozen)
        self.assertEqual(active_candidate(self.db,self.sid)['id'],new['id'])
        with self.assertRaisesRegex(ValueError,'이미'):
            submit_job(self.db,self.sid,'ai',frozen)
        with self.assertRaisesRegex(ValueError,'이미'):
            submit_job(self.db,self.sid,'ai',frozen,old['id'])

    async def test_pinned_old_card_precedes_twenty_new_cards(self):
        from lecture_study.assistance import question_cards,update_card
        from lecture_study.answers import save_artifact
        from lecture_study.models import Evidence,SourceRef
        tid=self.speech();frozen=await freeze_request(self.db,self.request_for('candidates'))
        row=self.db.execute('SELECT ref,text_snapshot FROM sources WHERE id=?',(tid,)).fetchone()
        evidence=[Evidence(ref=SourceRef.model_validate_json(row['ref']),text=row['text_snapshot'],label='전사')]
        for n in range(22):
            job=submit_job(self.db,self.sid,'ai',frozen)
            save_artifact(self.db,job['id'],{'cards':[{'id':str(n),'prompt':'질문 '+str(n),'quote':'공유 자원','source_id':tid}]},evidence,{'kind':'candidates','provider':'ollama','model':'test','cutoff_ms':1000,'retrieval_mode':'keyword'})
            with self.db:self.db.execute("UPDATE jobs SET status='done' WHERE id=?",(job['id'],))
            if n==0:update_card(self.db,self.sid,'0',{'pinned':True})
        cards=question_cards(self.db,self.sid);self.assertEqual(len(cards),22);self.assertEqual(cards[0]['id'],'0')

    async def test_note_schema_excludes_original_memo_citation(self):
        tid=self.speech();note=save_note(self.db,self.sid,'원래 메모')
        frozen=await freeze_request(self.db,self.request_for('note',note_source_id=note.id));job=submit_job(self.db,self.sid,'ai',frozen)
        async def constrained(config,messages,images,schema,**kwargs):
            ids=schema['properties']['evidence_ids']['items']['enum']
            self.assertEqual(ids,[tid])
            return ProviderResult(text=json.dumps({'addition':'보강','evidence_ids':ids}),model='test',usage={},elapsed_ms=1)
        with patch('lecture_study.assistance.generate',new=constrained):await run_ai_request(self.db,frozen,job['id'])

    async def test_local_note_requires_nonempty_text_and_chronological_neighborhood(self):
        from lecture_study.assistance import scoped_evidence
        tid=self.speech();note=save_note(self.db,self.sid,'원래 메모')
        request=self.request_for('note',note_source_id=note.id).model_copy(update={'provider':self.request.provider.model_copy(update={'provider':'ollama','model':'test'})})
        frozen=await freeze_request(self.db,request);job=submit_job(self.db,self.sid,'ai',frozen)
        response=AsyncMock(return_value=ProviderResult(text=json.dumps({'addition':'보강','evidence_ids':[tid]}),model='test',usage={},elapsed_ms=1))
        with patch('lecture_study.assistance.generate',new=response):await run_ai_request(self.db,frozen,job['id'])
        schema=response.call_args.args[3];self.assertEqual(schema['properties']['addition']['minLength'],1)
        self.assertEqual(schema['properties']['evidence_ids']['minItems'],1)
        from lecture_study.models import Evidence,SourceRef
        speech=[Evidence(ref=SourceRef(id=str(n),kind='transcript',session_id=self.sid,start_ms=n*1000,end_ms=(n+1)*1000),text=str(n),label='원문')for n in range(6)]
        original=Evidence(ref=note,text='메모',label='메모')
        with patch('lecture_study.answers.snapshot_evidence',return_value=[original,*speech]):items=scoped_evidence(self.db,request,{'cutoff_ms':6000,'search':{},'note_anchor_ms':3500})
        self.assertEqual([e.ref.start_ms for e in items[1:]],list(range(0,6000,1000)))
