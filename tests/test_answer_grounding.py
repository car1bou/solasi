import json,tempfile,unittest
from pathlib import Path
from unittest.mock import AsyncMock,patch
from lecture_study import answers as a
from lecture_study.answer_excerpts import selection_input
from lecture_study.db import open_db,create_session
from lecture_study.jobs import submit_job,get_job
from lecture_study.materials import save_note
from lecture_study.models import AIRequest,Scope,ProviderConfig,ProviderResult,Evidence,SourceRef,SearchResult

class AnswerGroundingTests(unittest.IsolatedAsyncioTestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.db=open_db(Path(self.temp.name));self.addCleanup(self.db.close)
  self.sid=create_session(self.db,'lecture','검증',None,None).id;self.ref=save_note(self.db,self.sid,'CDF F(x)=P(X≤x). a<b이면 F(a)≤F(b).')
  self.request=AIRequest(session_id=self.sid,kind='answer',prompt='CDF',scope=Scope(session_id=self.sid),provider=ProviderConfig(provider='local',model='qwen3.5:4b'))
 def reply(self,frozen):
  body={'answer':'F(x)=P(X≤x)','citations':[{'source_id':self.ref.id}],'uncertainty':''}
  if frozen.get('answer_format')=='excerpts-v1':
   _,_,units,_,_=selection_input(AIRequest.model_validate(frozen['request']),[Evidence.model_validate(e)for e in frozen['evidence']],frozen['answer_system']);body={'evidence_ids':[units[0].ref.id]}
  return ProviderResult(text=json.dumps(body),model='qwen3.5:4b',usage={},elapsed_ms=1)
 async def test_new_local_answer_pins_input_output_and_preserves_result_on_reexecution(self):
  frozen=await a.freeze_request(self.db,self.request);self.assertEqual(frozen['answer_policy'],'answer-grouped-evidence-v2');self.assertEqual(frozen['answer_format'],'excerpts-v1');self.assertEqual(frozen['answer_output_limit'],512)
  job=submit_job(self.db,self.sid,'ai',frozen);original=get_job(self.db,job['id'])['request'];system=frozen['answer_system']
  with patch.object(a,'LOCAL_ANSWER_SYSTEM','future policy'),patch.object(a,'generate',new=AsyncMock(return_value=self.reply(frozen)))as generate:
   first=await a.run_ai_request(self.db,frozen,job['id']);second=await a.run_ai_request(self.db,frozen,job['id'])
  self.assertEqual(first.id,second.id);self.assertEqual(generate.await_count,1);self.assertEqual(generate.call_args.args[1][0]['content'],system);self.assertEqual(generate.call_args.kwargs['output_limit'],512)
  saved=a.get_artifact(self.db,first.id);self.assertEqual(saved['body']['answer_format'],'excerpts-v1');self.assertEqual(saved['metadata']['answer_policy'],'answer-grouped-evidence-v2');self.assertEqual(saved['metadata']['question'],'CDF');self.assertEqual(saved['metadata']['answer_scope'],self.request.scope.model_dump());self.assertEqual(get_job(self.db,job['id'])['request'],original)
  from lecture_study.outputs import export_markdown
  exported=export_markdown(self.db,first.id);self.assertIn('## 관련 원문',exported);self.assertIn('F(x)=P(X≤x)',exported);self.assertIn(self.ref.id,exported)
 async def test_new_explanation_keeps_previous_system_and_never_uses_id_selection(self):
  frozen=await a.freeze_request(self.db,self.request.model_copy(update={'kind':'explain'}));self.assertEqual(frozen['answer_system'],a.SYSTEM);self.assertEqual(frozen['answer_policy'],'explanation-v1');self.assertNotIn('answer_format',frozen)
  job=submit_job(self.db,self.sid,'ai',frozen)
  with patch.object(a,'generate',new=AsyncMock(return_value=self.reply(frozen)))as generate:result=await a.run_ai_request(self.db,frozen,job['id'])
  self.assertEqual(generate.call_args.args[1][0]['content'],a.SYSTEM);self.assertNotIn('output_limit',generate.call_args.kwargs);self.assertEqual(a.get_artifact(self.db,result.id)['metadata']['answer_policy'],'explanation-v1')
  from lecture_study.outputs import export_markdown
  self.assertIn('## 추가 해설 · AI 생성',export_markdown(self.db,result.id))
 async def test_legacy_frozen_work_uses_previous_system_without_rewriting_request(self):
  frozen=await a.freeze_request(self.db,self.request)
  for key in ('answer_system','answer_policy','answer_format','answer_output_limit'):frozen.pop(key,None)
  job=submit_job(self.db,self.sid,'ai',frozen);original=get_job(self.db,job['id'])['request']
  with patch.object(a,'generate',new=AsyncMock(return_value=self.reply(frozen)))as generate:result=await a.run_ai_request(self.db,frozen,job['id'])
  self.assertEqual(generate.call_args.args[1][0]['content'],a.SYSTEM);self.assertNotIn('answer_policy',a.get_artifact(self.db,result.id)['metadata']);self.assertEqual(get_job(self.db,job['id'])['request'],original)
 async def test_old_snapshot_retains_legacy_while_new_snapshot_survives_future_policy_changes(self):
  captured=a.capture_request(self.db,self.request);legacy={k:v for k,v in captured.items()if not k.startswith('answer_')}
  old=await a.freeze_request(self.db,self.request,snapshot=legacy);self.assertNotIn('answer_system',old);self.assertNotIn('answer_policy',old)
  system=captured['answer_system']
  with patch.object(a,'LOCAL_ANSWER_SYSTEM','future policy'),patch.object(a,'LOCAL_ANSWER_POLICY','future-version'),patch.object(a,'LOCAL_ANSWER_OUTPUT_LIMIT',1024):frozen=await a.freeze_request(self.db,self.request,snapshot=captured)
  self.assertEqual(frozen['answer_system'],system);self.assertEqual(frozen['answer_policy'],'answer-grouped-evidence-v2');self.assertEqual(frozen['answer_output_limit'],512)
 async def test_api_legacy_ollama_and_summary_keep_their_existing_path(self):
  for provider in ('openai','gemini','claude','ollama'):
   frozen=await a.freeze_request(self.db,self.request.model_copy(update={'provider':ProviderConfig(provider=provider,model='api-model')}));self.assertNotIn('answer_system',frozen);self.assertNotIn('answer_format',frozen)
  with patch('lecture_study.token_budget.local_profile',return_value=None):summary=await a.freeze_request(self.db,self.request.model_copy(update={'kind':'summary'}))
  self.assertNotIn('answer_system',summary);self.assertEqual(summary['summary_format'],'excerpts-v1')
 async def test_freeze_and_run_count_the_actual_captured_system(self):
  with patch.object(a,'LOCAL_ANSWER_SYSTEM','large system '*1000):
   with self.assertRaisesRegex(ValueError,'예산'):await a.freeze_request(self.db,self.request)
  frozen=await a.freeze_request(self.db,self.request);frozen['answer_system']='large system '*1000;job=submit_job(self.db,self.sid,'ai',frozen)
  with patch.object(a,'generate',new=AsyncMock())as generate:
   with self.assertRaisesRegex(ValueError,'예산'):await a.run_ai_request(self.db,frozen,job['id'])
   generate.assert_not_called()
 async def test_long_source_is_budgeted_using_the_same_selection_input_at_execution(self):
  save_note(self.db,self.sid,'CDF 정의와 조건. '*600);frozen=await a.freeze_request(self.db,self.request);self.assertTrue(frozen['excerpted']);job=submit_job(self.db,self.sid,'ai',frozen)
  with patch.object(a,'generate',new=AsyncMock(return_value=self.reply(frozen)))as generate:await a.run_ai_request(self.db,frozen,job['id'])
  self.assertEqual(generate.call_args.args[1][0]['content'],frozen['answer_system']);self.assertEqual(generate.call_args.kwargs['output_limit'],512)

 async def test_grouping_preserves_late_sources_and_frozen_legacy_inputs(self):
  evidence=[Evidence(ref=SourceRef(id='pdf:'+str(n),kind='material',page=n+1),text=('필수 조건과 적용 범위입니다.\n'*24)+('후반 예외입니다.'if n==2 else ''),label='강의자료')for n in range(3)]
  snapshot=a.capture_request(self.db,self.request)
  with patch.object(a,'retrieve',new=AsyncMock(return_value=SearchResult(evidence=evidence,mode='keyword'))):
   new=await a.freeze_request(self.db,self.request,snapshot=snapshot)
   old=await a.freeze_request(self.db,self.request,snapshot=snapshot|{'answer_policy':'answer-excerpts-v1'})
  self.assertEqual([e['ref']['id']for e in new['evidence']],[e.ref.id for e in evidence]);self.assertFalse(new['excerpted']);self.assertTrue(old['excerpted'])
  for frozen in (old,new):
   entries=[Evidence.model_validate(e)for e in frozen['evidence']]
   _,_,units,_,_=selection_input(self.request,entries,frozen['answer_system'],grouped_materials=frozen['answer_policy']=='answer-grouped-evidence-v2')
   job=submit_job(self.db,self.sid,'ai',frozen);response=ProviderResult(text=json.dumps({'evidence_ids':[units[0].ref.id]}),model='qwen3.5:4b',usage={},elapsed_ms=1)
   with patch.object(a,'checked_evidence',return_value=(self.request,entries)),patch.object(a,'generate',new=AsyncMock(return_value=response))as generate:
    await a.run_ai_request(self.db,frozen,job['id'])
   actual=json.loads(generate.call_args.args[1][1]['content'])['evidence'];ids=[u['source_id']for e in actual for u in e.get('units',[e])]
   self.assertEqual(ids,[u.ref.id for u in units])
