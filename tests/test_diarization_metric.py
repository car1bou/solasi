import unittest
from experiments.evaluate_diarization import reference_turns,turn_der,noise_coverage

class TurnMetricTests(unittest.TestCase):
    def test_label_parser_excludes_unknown_but_includes_explicit_silence(self):
        rows=[{'start':n,'end':n+1,'reference':text}for n,text in enumerate(['<IVER>','안녕하세요','<SIL>','<VOCNOISE>','<UNKNOWN>','사람 <LAUGH>'])]
        ref,uem=reference_turns(rows,.5,5.5)
        self.assertEqual(ref,[(0,.5,'interviewer'),(.5,1.5,'respondent')]);self.assertEqual(uem,[(0,.5),(.5,1.5),(1.5,2.5)])
    def test_permutation_and_unlabeled_region(self):
        ref=[(0,1,'a'),(1,2,'b')];hyp=[(0,1,'7'),(1,2,'9'),(3,4,'7')]
        self.assertEqual(turn_der(ref,hyp,[(0,2)])['der'],0)
    def test_miss_false_alarm_and_identity_confusion(self):
        ref=[(0,1,'a'),(1,2,'b')]
        score=turn_der(ref,[(0,.5,'x'),(1,2,'x'),(2,3,'x')],[(0,3)])
        self.assertEqual(score['miss_seconds'],.5);self.assertEqual(score['false_alarm_seconds'],1);self.assertEqual(score['confusion_seconds'],.5);self.assertEqual(score['der'],1)
    def test_full_width_collar_and_hypothesis_overlap(self):
        ref=[(0,1,'a'),(1,2,'b')];hyp=[(0,1.2,'x'),(1.2,2,'y')]
        self.assertAlmostEqual(turn_der(ref,hyp,[(0,2)],.5)['der'],0)
        self.assertAlmostEqual(turn_der(ref,hyp,[(0,2)],0)['der'],.1)
        score=turn_der([(0,1,'a')],[(0,1,'x'),(0,1,'y')],[(0,1)])
        self.assertEqual(score['false_alarm_seconds'],1);self.assertEqual(score['confusion_seconds'],0)
    def test_mixture_activity_is_not_identity_accuracy(self):
        score=noise_coverage([(0,2,'a')],[(1,2,'background')])
        self.assertEqual(score['target_activity_coverage'],.5)
    def test_invalid_intervals_and_empty_scoring_rejected(self):
        with self.assertRaises(ValueError):turn_der([(1,0,'a')],[],[(0,1)])
        with self.assertRaises(ValueError):turn_der([(0,1,'a')],[],[(2,3)])
