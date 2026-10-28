import unittest,json
from lecture_study.models import AIRequest,Scope,ProviderConfig,Evidence,SourceRef
from lecture_study.answer_excerpts import selection_input,selected_answer,INSTRUCTION

class AnswerGroupingTests(unittest.TestCase):
 def setUp(self):
  self.req=AIRequest(session_id='s',kind='answer',prompt='정의와 조건',scope=Scope(session_id='s'),provider=ProviderConfig(provider='local'))
 def test_grouping_changes_only_wire_metadata_and_question_position(self):
  evidence=[Evidence(ref=SourceRef(id='pdf'+str(n),kind='material',page=n+1),text='정의입니다.\n1NF 조건입니다.\n뒤쪽 예외입니다.\n'*5,label='강의자료')for n in range(2)]
  old=selection_input(self.req,evidence,INSTRUCTION);new=selection_input(self.req,evidence,INSTRUCTION,grouped_materials=True)
  self.assertEqual(old[1:],new[1:]);a=json.loads(old[0][1]['content']);b=json.loads(new[0][1]['content']);flat=[]
  for group in b['evidence']:
   meta={k:v for k,v in group.items()if k!='units'};flat.extend(meta|unit for unit in group['units'])
  self.assertEqual(flat,a['evidence']);self.assertEqual(b['question'],a['question']);self.assertEqual(list(b)[-1],'question');self.assertLess(len(new[0][1]['content'].encode()),len(old[0][1]['content'].encode()))
 def test_correct_selection_does_not_expand_unrelated_displayed_context(self):
  evidence=[Evidence(ref=SourceRef(id='pdf',kind='material',page=1),text='표본평균은 관측값의 합을 개수로 나눈 값이다.\n'+'\n'.join('과제 공지 '+str(i)+'입니다.'for i in range(59)),label='자료')]
  old=selection_input(self.req,evidence,INSTRUCTION);new=selection_input(self.req,evidence,INSTRUCTION,grouped_materials=True);body={'evidence_ids':[old[2][0].ref.id]}
  self.assertEqual(selected_answer(body,evidence,*old[2:]),selected_answer(body,evidence,*new[2:]))
 def test_transcript_and_handwriting_only_inputs_remain_identical(self):
  for kind in ('transcript','ink_note','note'):
   evidence=[Evidence(ref=SourceRef(id='src',kind=kind,session_id='s',start_ms=0,end_ms=10000),text='지민은 외동이다. 부모님이 돌아가신다면 혼자 남을까 걱정한다. 실제 사건은 아니다.',label='원문')]
   self.assertEqual(selection_input(self.req,evidence,INSTRUCTION),selection_input(self.req,evidence,INSTRUCTION,grouped_materials=True))

 def test_adjacent_material_ranges_remove_display_duplication_not_real_repetition(self):
  evidence=[Evidence(ref=SourceRef(id='pdf',kind='material',page=1),text='정의입니다.\n•\n실제 반복입니다.\n조건을 유지합니다.\n•\n실제 반복입니다.\n후반 결론입니다.',label='자료')]
  _,_,units,aliases,restore=selection_input(self.req,evidence,INSTRUCTION,grouped_materials=True)
  body={'evidence_ids':[units[0].ref.id,units[3].ref.id]}
  old=selected_answer(body,evidence,units,aliases,restore)
  new=selected_answer(body,evidence,units,aliases,restore,merge_material_ranges=True)
  self.assertGreater(old['answer'].count('정의입니다.'),1);self.assertEqual(new['answer'].count('정의입니다.'),1)
  self.assertEqual(new['answer'].count('실제 반복입니다.'),2);self.assertIn('조건을 유지합니다.',new['answer']);self.assertIn('후반 결론입니다.',new['answer'])
  self.assertEqual({(q['evidence_ids'][0],q['text'])for s in old['sections']for q in s['quotes']},{(q['evidence_ids'][0],q['text'])for s in new['sections']for q in s['quotes']})
