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

    def test_fixed_vocabulary_counts_occurrences_in_every_condition(self):
        from experiments.compare_asr_hints import occurrence_counts
        expected=occurrence_counts('WSL WSL 이야기','WSL 이야기 다익스트라',['WSL','다익스트라'])
        self.assertEqual(expected,[{'term':'WSL','reference':2,'output':1,'missing':1,'excess':0},{'term':'다익스트라','reference':0,'output':1,'missing':0,'excess':1}])

    def test_pcm_chunks_cover_short_tail_without_dropping_or_padding(self):
        import tempfile,wave
        from pathlib import Path
        from experiments.compare_asr_hints import split_pcm
        with tempfile.TemporaryDirectory()as folder:
            root=Path(folder);path=root/'input.wav';payload=b'\x01\x00'*(30*16000+7)
            with wave.open(str(path),'wb')as handle:
                handle.setparams((1,2,16000,0,'NONE','not compressed'));handle.writeframes(payload)
            parts=split_pcm(path,root/'parts')
            self.assertEqual([(p['start_frame'],p['end_frame'])for p in parts],[(0,480000),(480000,480007)])
            raw=[]
            for part in parts:
                with wave.open(part['path'])as handle:raw.append(handle.readframes(handle.getnframes()))
            self.assertEqual(b''.join(raw),payload)
            with wave.open(str(root/'stereo.wav'),'wb')as handle:
                handle.setparams((2,2,16000,0,'NONE','not compressed'));handle.writeframes(b'\x00'*4)
            with self.assertRaises(ValueError):split_pcm(root/'stereo.wav',root/'bad')
            with wave.open(str(root/'empty.wav'),'wb')as handle:
                handle.setparams((1,2,16000,0,'NONE','not compressed'))
            with self.assertRaises(ValueError):split_pcm(root/'empty.wav',root/'empty-parts')
            (root/'truncated.wav').write_bytes(path.read_bytes()[:-1])
            with self.assertRaises(ValueError):split_pcm(root/'truncated.wav',root/'truncated-parts')


class HintRunnerTests(unittest.TestCase):
    def setUp(self):
        import hashlib,json,os,tempfile,wave
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup);root=Path(self.folder.name)
        source=root/'silence.wav'
        with wave.open(str(source),'wb')as handle:
            handle.setparams((1,2,16000,0,'NONE','not compressed'));handle.writeframes(b'\x00\x00'*1600)
        manifest=root/'manifest.json';manifest.write_text(json.dumps({'clips':[{'id':'fixture','sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'path':str(source),'group':'fixture','category':'negative','reference':'','hint_terms':['이란'],'distractor_terms':['다익스트라'],'hint_provenance':'synthetic unit fixture, not human quality evidence'}]}))
        self.args=SimpleNamespace(engine='whisper',manifest=manifest,runtime=root,output=root/'result.json',reverse_order=False)
        self.enterContext(patch.dict(os.environ));self.enterContext(patch('experiments.compare_asr_hints.importlib.metadata.version',return_value='fixture'))

    def test_empty_reference_and_fixed_vocabulary_are_scored_in_all_conditions(self):
        import asyncio,json
        from unittest.mock import AsyncMock,patch
        from experiments.compare_asr_hints import main
        result=[{'start_ms':0,'end_ms':100,'text':'다익스트라'}]
        with patch('lecture_study.transcription.transcribe_range',new=AsyncMock(return_value=result))as model:asyncio.run(main(self.args))
        report=json.loads(self.args.output.read_text());self.assertTrue(report['completed']);self.assertEqual(len(report['rows']),3)
        for row in report['rows']:
            self.assertIsNone(row['cer']);self.assertEqual(row['reference_chars'],0);self.assertEqual(row['insertions'],5)
            self.assertEqual(row['absent_terms_in_output'],['다익스트라']);self.assertEqual([t['term']for t in row['term_occurrences']],['이란','다익스트라'])
        self.assertEqual([c.args[2]for c in model.call_args_list],['','이란','다익스트라'])
        self.assertEqual(len({r['chunks'][0]['sha256']for r in report['rows']}),1)

    def test_failed_conditions_are_saved_and_never_marked_complete(self):
        import asyncio,json
        from unittest.mock import AsyncMock,patch
        from experiments.compare_asr_hints import main
        with patch('lecture_study.transcription.transcribe_range',new=AsyncMock(side_effect=ValueError('fixture failure'))),self.assertRaises(RuntimeError):asyncio.run(main(self.args))
        report=json.loads(self.args.output.read_text());self.assertFalse(report['completed']);self.assertEqual(len(report['rows']),3)
        self.assertTrue(all(r['status']=='failed'and r['error']=='fixture failure'for r in report['rows']))
