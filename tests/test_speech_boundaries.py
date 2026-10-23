import unittest
from array import array


class SpeechBoundaryTests(unittest.TestCase):
    def plan(self, seconds, activity, gap=200):
        from experiments.compare_speech_boundaries import boundaries
        return boundaries(array('h', [1000])*(seconds*16000), activity, gap)

    def test_uses_latest_internal_pause_midpoint_without_dropping_audio(self):
        activity=[{'start_ms':0,'end_ms':24000},{'start_ms':24400,'end_ms':27500},{'start_ms':27900,'end_ms':61000}]
        bounds,choices=self.plan(61,activity)
        self.assertEqual(bounds,[0,443200,923200,976000])
        self.assertEqual(choices[0]['reason'],'vad-gap')
        self.assertEqual(sum(b-a for a,b in zip(bounds,bounds[1:])),976000)
        self.assertTrue(all(0<b-a<=480000 for a,b in zip(bounds,bounds[1:])))

    def test_gap_threshold_keeps_short_pause_out_of_conservative_condition(self):
        activity=[{'start_ms':0,'end_ms':27000},{'start_ms':27300,'end_ms':61000}]
        self.assertEqual(self.plan(61,activity,200)[0],[0,434400,914400,976000])
        self.assertEqual(self.plan(61,activity,400)[0],[0,480000,960000,976000])

    def test_leading_trailing_or_outside_window_silence_is_not_a_pause_candidate(self):
        self.assertEqual(self.plan(61,[{'start_ms':1000,'end_ms':20000},{'start_ms':21000,'end_ms':22000}])[0],[0,480000,960000,976000])

    def test_unavailable_empty_and_continuous_activity_fall_back_to_energy(self):
        from experiments.compare_speech_boundaries import boundaries
        samples=array('h',[1000])*976000;samples[416000:422400]=array('h',[0])*6400
        for activity in [None,[],[{'start_ms':0,'end_ms':61000}]]:
            bounds,choices=boundaries(samples,activity,200)
            self.assertEqual(bounds,[0,420800,900800,976000])
            self.assertEqual(choices[0]['reason'],'energy-fallback')

    def test_short_tail_is_kept_whole_and_baseline_ignores_vad(self):
        self.assertEqual(self.plan(20,[{'start_ms':0,'end_ms':10000},{'start_ms':11000,'end_ms':20000}])[0],[0,320000])
        activity=[{'start_ms':0,'end_ms':27000},{'start_ms':28000,'end_ms':61000}]
        self.assertEqual(self.plan(61,activity,0)[0],[0,480000,960000,976000])

    def test_invalid_activity_and_conditions_are_rejected(self):
        for activity in [[{'start_ms':-1,'end_ms':2}],[{'start_ms':0,'end_ms':62000}],[{'start_ms':10,'end_ms':20},{'start_ms':19,'end_ms':40}],[{'start_ms':False,'end_ms':100}]]:
            with self.assertRaises(ValueError):self.plan(61,activity)
        for gap in [-1,True,300]:
            with self.assertRaises(ValueError):self.plan(61,[],gap)


class SpeechBoundaryPreparationTests(unittest.IsolatedAsyncioTestCase):
    async def test_vad_failure_preserves_source_and_freezes_three_fallback_plans(self):
        import hashlib,json,tempfile,wave
        from pathlib import Path
        from unittest.mock import AsyncMock,patch
        from experiments.compare_speech_boundaries import prepare
        with tempfile.TemporaryDirectory()as folder:
            root=Path(folder);source=root/'source.wav'
            with wave.open(str(source),'wb')as w:w.setparams((1,2,16000,0,'NONE','not compressed'));w.writeframes(b'\1\0'*496000)
            before=hashlib.sha256(source.read_bytes()).hexdigest();manifest=root/'input.json'
            clip={'id':'fixture','path':str(source),'sha256':before,'frames':496000,'boundaries':[0,480000,496000],'continuous':True,'group':'unit','reference_kind':'partial-conversation','reference':''}
            manifest.write_text(json.dumps({'completed':True,'clips':[clip]}));output=root/'out'
            with patch('lecture_study.transcription.speech_activity',new=AsyncMock(side_effect=ValueError('VAD failed'))):
                result=await prepare(manifest,root,output)
            self.assertEqual(len(result['clips']),1);self.assertEqual(result['clips'][0]['activity_status'],'failed')
            for gap in [0,200,400]:
                plan=json.loads((output/f'manifest-{gap}.json').read_text())
                self.assertTrue(plan['completed']);self.assertEqual(plan['clips'][0]['boundaries'],[0,480000,496000])
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),before)
            with self.assertRaises(ValueError):await prepare(manifest,root,output)
