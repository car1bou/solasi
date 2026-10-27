import unittest
from lecture_study.models import AIRequest,ProviderConfig,Scope,Evidence,SourceRef
from lecture_study.answer_excerpts import selection_input,selected_answer,INSTRUCTION

class AnswerExcerptTests(unittest.TestCase):
 def setUp(self):
  self.request=AIRequest(session_id='lecture',kind='answer',prompt='CDF와 지민의 걱정, 후반 일정',scope=Scope(session_id='lecture'),provider=ProviderConfig(provider='local'))
  self.evidence=[Evidence(ref=SourceRef(id='ink:1',kind='ink_note',session_id='lecture',page=1),text='누적분포함수 CDF: F(x) = P(X ≤ x). a < b이면 F(a) ≤ F(b).',label='확인한 손글씨'),Evidence(ref=SourceRef(id='transcript:1',kind='transcript',session_id='lecture',start_ms=1000,end_ms=5000),text='지민은 외동이다. 부모님이 돌아가신다면 혼자 남을까 걱정한다. 실제로 돌아가셨다는 뜻이 아니다. 후반 결론: 복습은 금요일이며 제출 기한은 미정이다.',label='원음')]
  self.messages,self.schema,self.units,self.aliases,self.restore=selection_input(self.request,self.evidence,INSTRUCTION)
 def build(self,body):return selected_answer(body,self.evidence,self.units,self.aliases,self.restore)
 def test_model_selects_ids_and_app_preserves_exact_math_and_context(self):
  ids=[self.units[0].ref.id,next(u.ref.id for u in self.units if '돌아가신다면' in u.text)]
  body=self.build({'evidence_ids':ids})
  self.assertEqual(body['answer_format'],'excerpts-v1')
  for text in ('F(x) = P(X ≤ x)','a < b이면 F(a) ≤ F(b)','지민은 외동이다.','부모님이 돌아가신다면','실제로 돌아가셨다는 뜻이 아니다.','복습은 금요일','제출 기한은 미정'):
   self.assertIn(text,body['answer'])
  for section in body['sections']:
   for quote in section['quotes']:
    original=next(e for e in self.evidence if e.ref.id==quote['evidence_ids'][0])
    self.assertIn(quote['text'],original.text)
  self.assertIn({'source_id':'transcript:1','page':None,'start_ms':1000,'end_ms':5000},body['citations'])
  self.assertNotIn('단조',body['answer'])
 def test_no_selection_does_not_claim_requested_fact_is_absent(self):
  body=self.build({'evidence_ids':[]})
  self.assertEqual(body['sections'],[]);self.assertEqual(body['citations'],[]);self.assertEqual(body['uncertainty'],'')
  self.assertEqual(body['answer'],'선택된 원문이 없습니다.')
 def test_untrusted_selection_rejects_invented_duplicate_and_generated_text(self):
  ident=self.units[0].ref.id
  for body in ({'evidence_ids':['invented']},{'evidence_ids':[ident,ident]},{'evidence_ids':[],'answer':'지민이 작성자다'},{'evidence_ids':'s0'},{'evidence_ids':list(range(9))},[]):
   with self.subTest(body=body),self.assertRaises(ValueError):self.build(body)
 def test_schema_ids_and_system_are_the_actual_inputs(self):
  self.assertEqual(self.messages[0],{'role':'system','content':INSTRUCTION})
  self.assertEqual(self.schema['properties']['evidence_ids']['items']['enum'],[u.ref.id for u in self.units])
  self.assertEqual(self.schema['properties']['evidence_ids']['minItems'],0)
  self.assertIn('CDF',self.messages[1]['content'])
 def test_partial_input_retains_review_flag_instead_of_inventing_ending(self):
  self.evidence=self.evidence[:1];self.evidence[0].text='조건이 성립한다면 결론을'
  self.messages,self.schema,self.units,self.aliases,self.restore=selection_input(self.request,self.evidence,INSTRUCTION)
  body=self.build({'evidence_ids':[self.units[0].ref.id]})
  self.assertEqual(body['answer'],'조건이 성립한다면 결론을');self.assertTrue(body['sections'][0]['review_required'])
