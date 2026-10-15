import unittest
from array import array
class ConversationConditionTests(unittest.TestCase):
    def test_selection_keeps_short_turns_and_excludes_untranscribed_speech(self):
        from experiments.collect_conversation_conditions import choose_reference_clips
        rows=[{'start':0,'end':.2,'reference':'예'},{'start':.2,'end':1,'reference':'<IVER>'}]
        rows += [{'start':n+1,'end':n+2.2,'reference':'그러니깐 뭐 '+str(n)} for n in range(6)]
        selected=choose_reference_clips(rows,0,9)
        self.assertEqual(len(selected),5);self.assertIn(rows[0],selected)
        self.assertFalse(any('<'in r['reference']for r in selected))
        self.assertEqual(selected,choose_reference_clips(rows,0,9))
    def test_real_noise_mix_preserves_frame_count_and_reports_clipping(self):
        from experiments.collect_conversation_conditions import mix_pcm
        signal=array('h',[32760,0,-32760,0]);noise=array('h',[20,-20,-20,-20])
        result,clipped=mix_pcm(signal,noise,1,0)
        self.assertEqual(result.tolist(),[32767,-20,-32768,-20]);self.assertEqual(clipped,2)
        self.assertEqual(len(result),len(signal));self.assertEqual(signal.tolist(),[32760,0,-32760,0])

class EvaluationScriptTests(unittest.IsolatedAsyncioTestCase):
    async def test_output_records_components_and_keeps_continuous_cer_undefined(self):
        import json,tempfile,wave
        from pathlib import Path
        from unittest.mock import patch,AsyncMock
        from experiments import evaluate_conversation_conditions as evaluation
        from lecture_study.transcription import file_hash
        with tempfile.TemporaryDirectory()as temp:
            root=Path(temp);source=root/'clip.wav'
            for path,seconds in [(source,1),(root/'OOFFICE-ch08.wav',36),(root/'PCAFETER-ch08.wav',36)]:
                with wave.open(str(path),'wb')as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(bytes(32000*seconds))
            clip={'path':str(source),'sha256':file_hash(source),'group':'clean-adult','reference':'예','duration_seconds':1}
            window=clip|{'whole_conversation_cer_valid':False}
            (root/'manifest.json').write_text(json.dumps({'ready':True,'clips':[clip],'conversations':[window],'datasets':{}}));output=root/'result.json'
            with patch.object(evaluation,'FOLDER',root),patch.object(evaluation.tr,'transcribe_range',new=AsyncMock(return_value=[{'start_ms':0,'end_ms':500,'text':'예'}]))as decoded:
                await evaluation.main('100',output,False,True,padding_ms=1000)
            self.assertEqual(decoded.call_args.kwargs['padding_ms'],1000)
            result=json.loads(output.read_text());self.assertEqual(result['speech_pad_ms'],1000);self.assertTrue(result['ready']);self.assertEqual(result['aggregate']['clean-adult']['cer'],0);self.assertEqual(result['clips'][0]['insertions'],0);self.assertNotIn('cer',result['conversations'][0]);self.assertEqual(len(result['controls']),4)
