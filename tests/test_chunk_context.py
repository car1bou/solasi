import unittest


class ChunkContextTests(unittest.TestCase):
    def test_context_is_clamped_to_same_continuous_run(self):
        from experiments.compare_chunk_context import context_bounds
        self.assertEqual(context_bounds(700,1000,600,1200,500),(600,1200))
        self.assertEqual(context_bounds(700,1000,600,1200,0),(700,1000))
        for args in [(500,1000,600,1200,1),(700,1300,600,1200,1),(700,1000,600,1200,-1),(True,1000,0,1200,1)]:
            with self.assertRaises(ValueError):context_bounds(*args)

    def test_midpoint_ownership_keeps_whole_text_and_actual_times(self):
        from experiments.compare_chunk_context import owned_segments
        segments=[{'start_ms':28000,'end_ms':32000,'text':'실제로 반복한 말 반복한 말'}]
        self.assertEqual(owned_segments(segments,0,30000,0,32000),[])
        self.assertEqual(owned_segments(segments,30000,60000,28000,60000),segments)
        self.assertEqual(segments[0]['start_ms'],28000)
        with self.assertRaises(ValueError):owned_segments(segments,30000,60000,29000,60000)
        for bad in [{'start_ms':0,'end_ms':32001,'text':'잘못된 시각'},{'start_ms':0,'end_ms':1,'text':''},{'start_ms':0,'end_ms':True,'text':'잘못된 값'}]:
            with self.assertRaises(ValueError):owned_segments([bad],0,30000,0,32000)

    def test_same_words_are_only_duplicate_candidates_when_time_overlaps(self):
        from experiments.compare_chunk_context import seam_warnings
        first={'start_ms':27000,'end_ms':31000,'text':'실제 반복 문장','core_index':0}
        second={'start_ms':30000,'end_ms':34000,'text':'실제 반복 문장','core_index':1}
        result=seam_warnings([first,second]);self.assertEqual(result['text_overlap_candidates'],[{'left':0,'right':1,'shared_chars':6,'overlap_ms':1000}])
        self.assertEqual(seam_warnings([first,dict(second,start_ms=32000)])['text_overlap_candidates'],[])
        self.assertEqual(seam_warnings([first,dict(second,core_index=0)])['text_overlap_candidates'],[])
        self.assertEqual([first['text'],second['text']],['실제 반복 문장']*2)

    def test_midpoint_does_not_hide_nonmonotonic_start_or_temporal_overlap(self):
        from experiments.compare_chunk_context import seam_warnings
        rows=[{'start_ms':29000,'end_ms':30000,'text':'앞 문장','core_index':0},{'start_ms':28000,'end_ms':34000,'text':'뒤 문장','core_index':1}]
        result=seam_warnings(rows)
        self.assertEqual(result['start_reversals'],1);self.assertEqual(result['cross_core_time_overlaps'],1)


class ChunkRunnerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import hashlib,json,tempfile,wave
        from pathlib import Path
        from types import SimpleNamespace
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup);self.root=Path(self.folder.name)
        self.source=self.root/'source.wav'
        with wave.open(str(self.source),'wb')as out:out.setparams((1,2,16000,0,'NONE','not compressed'));out.writeframes(b'\1\0'*48000)
        self.clip={'id':'fixture','group':'synthetic-unit','path':str(self.source),'sha256':hashlib.sha256(self.source.read_bytes()).hexdigest(),'frames':48000,'boundaries':[0,16000,32000,48000],'continuous':True,'reference_kind':'manual-complete','reference':'구간0 구간1 구간2'}
        self.args=SimpleNamespace(manifest=self.root/'manifest.json',runtime=self.root,output=self.root/'out.json',overlap_ms=[0,1000])
        self.args.manifest.write_text(json.dumps({'completed':True,'clips':[self.clip]}))
        from unittest.mock import patch
        self.enterContext(patch('lecture_study.transcription.engine_paths',return_value=('ffmpeg','whisper','model')));self.enterContext(patch('lecture_study.transcription.verify_model'))

    async def test_overlap_changes_only_decode_bounds_and_keeps_owned_timestamps(self):
        import json,wave
        from unittest.mock import patch
        from experiments.compare_chunk_context import main,digest
        calls=[]
        async def recognize(path,start,*args,**kwargs):
            with wave.open(str(path))as w:end=start+round(w.getnframes()/16)
            calls.append((start,end,kwargs))
            return [{'start_ms':t,'end_ms':min(t+1000,end),'text':'구간'+str(t//1000)}for t in range(start,end,1000)]
        with patch('lecture_study.transcription.transcribe_range',side_effect=recognize):await main(self.args)
        result=json.loads(self.args.output.read_text());self.assertTrue(result['completed']);self.assertEqual(len(result['rows']),2)
        for row in result['rows']:
            self.assertEqual(row['edits'],0);self.assertEqual([(s['start_ms'],s['end_ms'])for s in row['segments']],[(0,1000),(1000,2000),(2000,3000)])
        self.assertEqual([(a,b)for a,b,_ in calls],[(0,1000),(1000,2000),(2000,3000),(0,2000),(0,3000),(1000,3000)])
        self.assertTrue(all(options['padding_ms']==1000 and options['timings']=={}for _,_,options in calls));self.assertEqual(digest(self.source),self.clip['sha256'])

    async def test_disabled_vad_reaches_native_command_without_loading_vad(self):
        import json
        from pathlib import Path
        from unittest.mock import patch
        from experiments.compare_chunk_context import main
        self.args.overlap_ms=[0];self.args.vad_enabled=False;calls=[]
        async def native(argv,**options):
            calls.append(argv)
            self.assertNotIn('--vad',argv);self.assertNotIn('-vm',argv)
            for option in ('--vad-speech-pad-ms','--vad-min-speech-duration-ms'):self.assertNotIn(option,argv)
            Path(str(argv[argv.index('-of')+1])+'.json').write_text(json.dumps({'transcription':[{'offsets':{'from':0,'to':1000},'text':'구간'+str(len(calls)-1)}]}))
            return b''
        with patch('lecture_study.transcription.command',side_effect=native),patch('lecture_study.transcription.verify_model',side_effect=AssertionError('VAD must not be required')):
            await main(self.args)
        result=json.loads(self.args.output.read_text());self.assertTrue(result['completed']);self.assertFalse(result['vad_enabled']);self.assertEqual(len(calls),3)
        self.assertEqual(result['rows'][0]['edits'],0);self.assertFalse(result['rows'][0]['vad_enabled'])

    async def test_digital_zero_skip_is_explicit_and_equal_in_both_conditions(self):
        import json,wave
        from unittest.mock import AsyncMock,patch
        from experiments.compare_chunk_context import main,digest
        with wave.open(str(self.source),'wb')as w:w.setparams((1,2,16000,0,'NONE','not compressed'));w.writeframes(bytes(96000))
        self.clip.update(sha256=digest(self.source),reference_kind='silence',reference='');self.args.manifest.write_text(json.dumps({'completed':True,'clips':[self.clip]}));self.args.overlap_ms=[0]
        for enabled in (True,False):
            self.args.vad_enabled=enabled;self.args.output=self.root/(str(enabled)+'.json')
            with patch('lecture_study.transcription.transcribe_range',new=AsyncMock(side_effect=AssertionError('digital zero must skip equally'))):await main(self.args)
            row=json.loads(self.args.output.read_text())['rows'][0];self.assertEqual(row['output_chars'],0)
            self.assertTrue(all(c['skipped_digital_silence']for c in row['chunks']))

    async def test_invalid_vad_condition_is_rejected_before_output_creation(self):
        from experiments.compare_chunk_context import main
        self.args.vad_enabled='false'
        with self.assertRaises(ValueError):await main(self.args)
        self.assertFalse(self.args.output.exists())

    async def test_partial_reference_is_not_scored_as_complete(self):
        import json
        from unittest.mock import AsyncMock,patch
        from experiments.compare_chunk_context import main
        self.clip['reference_kind']='partial-conversation';self.args.manifest.write_text(json.dumps({'completed':True,'clips':[self.clip]}))
        with patch('lecture_study.transcription.transcribe_range',new=AsyncMock(return_value=[])):await main(self.args)
        self.assertTrue(all(r['cer']is None and r['edits']is None for r in json.loads(self.args.output.read_text())['rows']))

    async def test_failed_decode_is_saved_with_partial_chunks_and_never_completed(self):
        import json
        from unittest.mock import AsyncMock,patch
        from experiments.compare_chunk_context import main
        self.args.overlap_ms=[0]
        with patch('lecture_study.transcription.transcribe_range',new=AsyncMock(side_effect=[[],ValueError('fixture failure')])),self.assertRaises(RuntimeError):await main(self.args)
        result=json.loads(self.args.output.read_text());self.assertFalse(result['completed']);self.assertEqual(len(result['rows'][0]['chunks']),1);self.assertEqual(result['rows'][0]['status'],'failed')

    async def test_discontinuous_or_incomplete_manifest_rejected_before_decode(self):
        import json
        from unittest.mock import AsyncMock,patch
        from experiments.compare_chunk_context import main
        for complete,continuous in [(False,True),(True,False)]:
            self.clip['continuous']=continuous;self.args.manifest.write_text(json.dumps({'completed':complete,'clips':[self.clip]}))
            with patch('lecture_study.transcription.transcribe_range',new=AsyncMock())as model,self.assertRaises(ValueError):await main(self.args)
            model.assert_not_called();self.assertFalse(self.args.output.exists())

    async def test_changed_source_keeps_failed_row_and_decoded_chunks(self):
        import json
        from unittest.mock import patch
        from experiments.compare_chunk_context import main
        self.args.overlap_ms=[0]
        async def mutate(*args,**kwargs):
            with self.source.open('ab')as f:f.write(b'\0')
            return []
        with patch('lecture_study.transcription.transcribe_range',side_effect=mutate),self.assertRaises(RuntimeError):await main(self.args)
        result=json.loads(self.args.output.read_text());self.assertFalse(result['completed']);self.assertEqual(result['rows'][0]['status'],'failed');self.assertEqual(len(result['rows'][0]['chunks']),3)
