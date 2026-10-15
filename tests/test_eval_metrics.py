import unittest
from tests.evaluate_human_audio import normalize,edit_distance,score

class MetricsTests(unittest.TestCase):
    def test_spacing_punctuation_and_unicode_normalization(self):
        self.assertEqual(normalize("가상 메모리, 15m!"),"가상메모리15m")
        self.assertEqual(normalize("ＡＢＣ"),"abc")
        self.assertEqual(score("가상 메모리","가상메모리.")["cer"],0)
    def test_insert_delete_replace_and_weighted_denominator(self):
        self.assertEqual(edit_distance("abc","axc"),1)
        self.assertEqual(edit_distance("abc","ab"),1)
        self.assertEqual(edit_distance("ab","abc"),1)
        self.assertEqual(score("가상메모리","가상메모리요"),{"edits":1,"reference_chars":5,"cer":.2})
    def test_character_error_components_sum_to_edit_distance(self):
        from tests.evaluate_human_audio import character_errors
        for ref,hyp,expected in [('abc','axc',(1,0,0)),('abc','ab',(0,1,0)),('ab','abc',(0,0,1)),('가 나','가나',(0,0,0))]:
            result=character_errors(ref,hyp)
            self.assertEqual((result['substitutions'],result['deletions'],result['insertions']),expected)
            self.assertEqual(sum(result.values()),score(ref,hyp)['edits'])
