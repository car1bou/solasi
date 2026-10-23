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

    def test_preprocessing_can_run_only_no_hint_condition(self):
        self.assertEqual(condition_sequence(False,['none']),('none',))
        self.assertEqual(condition_sequence(True,['none','distractor']),('distractor','none'))
        for invalid in ([],['none','none'],['unknown']):
            with self.assertRaises(ValueError):condition_sequence(False,invalid)

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
            handle.setparams((1,2,16000,0,'NONE','not compressed'));handle.writeframes(b'\x01\x00'*1600)
        manifest=root/'manifest.json';manifest.write_text(json.dumps({'clips':[{'id':'fixture','sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'path':str(source),'group':'fixture','category':'negative','reference':'','hint_terms':['이란'],'distractor_terms':['다익스트라'],'hint_provenance':'synthetic unit fixture, not human quality evidence'}]}))
        self.args=SimpleNamespace(engine='whisper',manifest=manifest,runtime=root,output=root/'result.json',reverse_order=False)
        self.enterContext(patch.dict(os.environ));self.enterContext(patch('experiments.compare_asr_hints.importlib.metadata.version',return_value='fixture'))

    def test_explicitly_incomplete_manifest_is_rejected_before_inference(self):
        import asyncio,json
        from unittest.mock import AsyncMock,patch
        from experiments.compare_asr_hints import main
        data=json.loads(self.args.manifest.read_text());data['completed']=False
        self.args.manifest.write_text(json.dumps(data))
        with patch('lecture_study.transcription.transcribe_range',new=AsyncMock(return_value=[]))as model:
            with self.assertRaisesRegex(ValueError,'Incomplete'):asyncio.run(main(self.args))
        model.assert_not_called();self.assertFalse(self.args.output.exists())

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

    def test_selected_no_hint_condition_is_not_inferred_three_times(self):
        import asyncio,json
        from unittest.mock import AsyncMock,patch
        from experiments.compare_asr_hints import main
        self.args.conditions=['none']
        with patch('lecture_study.transcription.transcribe_range',new=AsyncMock(return_value=[]))as model:asyncio.run(main(self.args))
        self.assertEqual(model.await_count,1)
        self.assertEqual(json.loads(self.args.output.read_text())['condition_order'],['none'])

    def test_denoising_to_digital_silence_uses_product_silence_guard(self):
        import asyncio,hashlib,json,wave
        from pathlib import Path
        from unittest.mock import AsyncMock,patch
        from experiments.compare_asr_hints import main
        manifest=json.loads(self.args.manifest.read_text());source=Path(manifest['clips'][0]['path'])
        with wave.open(str(source),'wb')as w:w.setparams((1,2,16000,0,'NONE','not compressed'));w.writeframes(b'\0\0'*1600)
        manifest['clips'][0]['sha256']=hashlib.sha256(source.read_bytes()).hexdigest();self.args.manifest.write_text(json.dumps(manifest))
        with patch('lecture_study.transcription.transcribe_range',new=AsyncMock(side_effect=AssertionError('digital silence must not infer')))as model:asyncio.run(main(self.args))
        model.assert_not_called()
        rows=json.loads(self.args.output.read_text())['rows'];self.assertTrue(all(r['recognized']==''and r['chunks'][0]['skipped_digital_silence']for r in rows))

    def test_whisper_boundary_padding_is_explicit_and_recorded(self):
        import asyncio,json
        from unittest.mock import AsyncMock,patch
        from experiments.compare_asr_hints import main
        self.args.conditions=['none'];self.args.whisper_padding_ms=2000
        with patch('lecture_study.transcription.transcribe_range',new=AsyncMock(return_value=[]))as model:asyncio.run(main(self.args))
        self.assertEqual(model.call_args.kwargs,{'padding_ms':2000})
        self.assertEqual(json.loads(self.args.output.read_text())['whisper_vad'],{'mode':'native','padding_ms':2000})

    def test_whisper_full_gate_retains_same_pcm_and_only_empty_activity_skips(self):
        import asyncio,json
        from pathlib import Path
        from unittest.mock import AsyncMock,patch
        from experiments.compare_asr_hints import main
        self.args.conditions=['none'];self.args.whisper_vad='gate-full'
        for name,activity in [('speech',[{'start_ms':80,'end_ms':100}]),('silent',[])]:
            self.args.output=Path(self.folder.name)/(name+'.json')
            with patch('lecture_study.transcription.speech_activity',new=AsyncMock(return_value=activity)),patch('lecture_study.transcription.transcribe_range',new=AsyncMock(return_value=[]))as model:asyncio.run(main(self.args))
            row=json.loads(self.args.output.read_text())['rows'][0];chunk=row['chunks'][0]
            self.assertEqual(chunk['vad_activity'],activity)
            if activity:
                self.assertEqual(model.call_args.kwargs,{'padding_ms':1000,'vad_enabled':False})
                self.assertEqual(chunk['start_frame'],0);self.assertEqual(chunk['end_frame'],1600)
                self.assertEqual(chunk['sha256'],row['sha256'])
            else:model.assert_not_called();self.assertTrue(chunk['skipped_no_speech'])

    def test_whisper_gate_unavailable_or_failed_is_not_silence(self):
        import asyncio,json
        from pathlib import Path
        from unittest.mock import AsyncMock,patch
        from experiments.compare_asr_hints import main
        self.args.conditions=['none'];self.args.whisper_vad='gate-full'
        for name,options in [('missing',{'return_value':None}),('error',{'side_effect':ValueError('activity failed')})]:
            self.args.output=Path(self.folder.name)/(name+'.json')
            with patch('lecture_study.transcription.speech_activity',new=AsyncMock(**options)),patch('lecture_study.transcription.transcribe_range',new=AsyncMock(return_value=[]))as model,self.assertRaises(RuntimeError):asyncio.run(main(self.args))
            model.assert_not_called();result=json.loads(self.args.output.read_text());self.assertFalse(result['completed']);self.assertEqual(result['rows'][0]['status'],'failed')

    def test_invalid_whisper_options_fail_before_inference(self):
        import asyncio
        from experiments.compare_asr_hints import main
        for name,value in [('whisper_padding_ms',-1),('whisper_padding_ms',True),('whisper_vad','unknown')]:
            setattr(self.args,name,value)
            with self.assertRaises(ValueError):asyncio.run(main(self.args))
            self.assertFalse(self.args.output.exists());delattr(self.args,name)
        self.args.engine='qwen';self.args.whisper_vad='gate-full'
        with self.assertRaisesRegex(ValueError,'Unused Whisper'):asyncio.run(main(self.args))
        self.assertFalse(self.args.output.exists())

    def test_qwen_vad_gate_skips_inference_only_for_validated_empty_activity(self):
        import asyncio,hashlib,json,sys
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import Mock,patch
        from experiments.compare_asr_hints import main,split_pcm
        root=Path(self.folder.name);clip=json.loads(self.args.manifest.read_text())['clips'][0]
        part=split_pcm(Path(clip['path']),root/'parts')[0]
        activity=root/'vad.json';body={'manifest_sha256':hashlib.sha256(self.args.manifest.read_bytes()).hexdigest(),'detector':{'test_fixture':True},'clips':{'fixture':[{k:v for k,v in part.items()if k!='path'}|{'activity':[],'seconds':0.1}]}}
        activity.write_text(json.dumps(body));self.args.engine='qwen';self.args.qwen_vad='gate';self.args.vad_activity=activity
        mx=SimpleNamespace(synchronize=Mock(),reset_peak_memory=Mock(),get_peak_memory=Mock(return_value=0))
        model=SimpleNamespace(generate=Mock(side_effect=AssertionError('no speech must not generate')))
        utils=SimpleNamespace(load_model=Mock(return_value=model),merge_hotwords=Mock(return_value=''))
        modules={'mlx':SimpleNamespace(core=mx),'mlx.core':mx,'mlx_audio':SimpleNamespace(),'mlx_audio.stt':SimpleNamespace(),'mlx_audio.stt.utils':utils}
        with patch.dict(sys.modules,modules),patch('lecture_study.qwen_asr.verify_files'):
            asyncio.run(main(self.args))
        result=json.loads(self.args.output.read_text());self.assertTrue(result['completed']);model.generate.assert_not_called()
        self.assertTrue(all(r['recognized']==''and r['chunks'][0]['skipped_no_speech']for r in result['rows']))
        self.args.output=root/'unavailable.json';body['clips']['fixture'][0]['activity']=None;activity.write_text(json.dumps(body))
        with patch.dict(sys.modules,modules),patch('lecture_study.qwen_asr.verify_files'),self.assertRaisesRegex(ValueError,'unavailable'):
            asyncio.run(main(self.args))
        self.assertFalse(json.loads(self.args.output.read_text())['completed'])
        self.args.output=root/'speech.json';body['clips']['fixture'][0]['activity']=[{'start_ms':0,'end_ms':100}];activity.write_text(json.dumps(body))
        model.generate.side_effect=None;model.generate.return_value=SimpleNamespace(text='실제 발화',prompt_tokens=1,generation_tokens=5)
        with patch.dict(sys.modules,modules),patch('lecture_study.qwen_asr.verify_files'):
            asyncio.run(main(self.args))
        result=json.loads(self.args.output.read_text());self.assertTrue(result['completed']);self.assertEqual(model.generate.call_count,3)
        self.assertTrue(all(r['recognized']=='실제 발화'and not r['chunks'][0]['skipped_no_speech']for r in result['rows']))
        self.args.output=root/'capped.json';model.generate.return_value.generation_tokens=1024
        with patch.dict(sys.modules,modules),patch('lecture_study.qwen_asr.verify_files'),self.assertRaisesRegex(RuntimeError,'Incomplete'):
            asyncio.run(main(self.args))
        result=json.loads(self.args.output.read_text());self.assertFalse(result['completed'])
        self.assertTrue(all(r['status']=='failed'and r['chunks'][0]['generation_tokens']==1024 for r in result['rows']))

class QwenVadPartsTests(unittest.TestCase):
    def test_gate_keeps_speech_pcm_and_marks_only_explicit_empty_activity(self):
        import tempfile
        from pathlib import Path
        from experiments.compare_asr_hints import qwen_vad_parts
        part={'path':'/not-read-for-gate.wav','start_frame':480000,'end_frame':960000,'sha256':'a'}
        speech={'sha256':'a','start_frame':480000,'end_frame':960000,'activity':[{'start_ms':500,'end_ms':1000}],'seconds':0.2}
        with tempfile.TemporaryDirectory()as folder:
            result=qwen_vad_parts([part],[speech],'gate',Path(folder))
            self.assertEqual(result[0]['path'],part['path']);self.assertEqual(result[0]['sha256'],'a');self.assertFalse(result[0]['skipped_no_speech'])
            silent=qwen_vad_parts([part],[dict(speech,activity=[])],'gate',Path(folder))
            self.assertTrue(silent[0]['skipped_no_speech'])
            for bad in [None,[{'start_ms':1000,'end_ms':500}],[{'start_ms':0,'end_ms':30001}]]:
                with self.assertRaises(ValueError):qwen_vad_parts([part],[dict(speech,activity=bad)],'gate',Path(folder))
            with self.assertRaises(ValueError):qwen_vad_parts([part],[dict(speech,sha256='changed')],'gate',Path(folder))
            with self.assertRaises(ValueError):qwen_vad_parts([part],[],'gate',Path(folder))

    def test_trim_preserves_internal_pauses_margin_and_original_frame_offsets(self):
        import tempfile,wave
        from pathlib import Path
        from experiments.compare_asr_hints import qwen_vad_parts,split_pcm
        with tempfile.TemporaryDirectory()as folder:
            root=Path(folder);source=root/'source.wav';payload=b'\x01\x00'*480000
            with wave.open(str(source),'wb')as w:w.setparams((1,2,16000,0,'NONE','not compressed'));w.writeframes(payload)
            part=split_pcm(source,root/'split')[0];part.update(start_frame=480000,end_frame=960000)
            activity={'sha256':part['sha256'],'start_frame':480000,'end_frame':960000,'activity':[{'start_ms':2000,'end_ms':3000},{'start_ms':24000,'end_ms':25000}],'seconds':0.1}
            result=qwen_vad_parts([part],[activity],'trim',root/'trim')[0]
            self.assertEqual((result['start_frame'],result['end_frame']),(496000,896000))
            self.assertEqual((result['original_start_frame'],result['original_end_frame']),(480000,960000))
            with wave.open(result['path'])as w:self.assertEqual(w.readframes(w.getnframes()),payload[32000:832000])
            activity['activity']=[{'start_ms':100,'end_ms':29999}]
            result=qwen_vad_parts([part],[activity],'trim',root/'edge')[0]
            self.assertEqual((result['start_frame'],result['end_frame']),(480000,960000))

    def test_rounded_vad_duration_clamps_to_exact_final_pcm_frame(self):
        import hashlib,tempfile,wave
        from pathlib import Path
        from experiments.compare_asr_hints import qwen_vad_parts
        with tempfile.TemporaryDirectory()as folder:
            root=Path(folder);source=root/'short.wav';payload=b'\x01\x00'*16010
            with wave.open(str(source),'wb')as w:w.setparams((1,2,16000,0,'NONE','not compressed'));w.writeframes(payload)
            part={'path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'start_frame':0,'end_frame':16010}
            activity=dict(part,activity=[{'start_ms':100,'end_ms':1001}],seconds=0.1)
            result=qwen_vad_parts([part],[activity],'trim',root/'trim')[0]
            self.assertEqual(result['end_frame'],16010)
            with wave.open(result['path'])as w:self.assertEqual(w.readframes(w.getnframes()),payload)
