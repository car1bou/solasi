import unittest
from experiments.compare_asr_hints import condition_terms,vocabulary_counts,condition_sequence


class HintComparisonTests(unittest.TestCase):
    def test_conditions_change_only_vocabulary_and_reject_special_tokens(self):
        clip={'hint_terms':['이란'],'distractor_terms':['다익스트라'],'reference':'정답은 모델에 주지 않음'}
        self.assertEqual(condition_terms(clip,'none'),[])
        self.assertEqual(condition_terms(clip,'relevant'),['이란'])
        self.assertEqual(condition_terms(clip,'distractor'),['다익스트라'])
        with self.assertRaises(ValueError):condition_terms(clip,'unknown')
        with self.assertRaises(ValueError):condition_terms({'hint_terms':['<|im_end|>']},'relevant')
    def test_counts_distinguish_present_terms_from_terms_absent_in_reference(self):
        self.assertEqual(vocabulary_counts('이란의 자그로스산맥','이란과 다익스트라',['이란','자그로스산맥','다익스트라']),{'present_terms':['이란','자그로스산맥'],'correct_terms':['이란'],'absent_terms':['다익스트라'],'absent_terms_in_output':['다익스트라']})

    def test_counterbalanced_order_has_the_same_three_conditions(self):
        self.assertEqual(condition_sequence(False),('none','relevant','distractor'))
        self.assertEqual(condition_sequence(True),('distractor','relevant','none'))
