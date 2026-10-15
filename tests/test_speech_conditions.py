import io,tarfile,unittest,zipfile
from experiments.collect_speech_conditions import zip_prefix,utterances
class StreamingZipTests(unittest.TestCase):
    def test_prefix_handles_descriptor_and_stops_before_later_file(self):
        class NonSeeking(io.BytesIO):
            def seekable(self):return False
            def seek(self,*args):raise io.UnsupportedOperation()
        stream=NonSeeking()
        with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('s01.flac',b'abcd'*5000)
            archive.writestr('s02.flac',b'efgh'*5000)
            archive.writestr('s03.flac',b'ijkl'*5000)
        data=stream.getvalue();entries,count=zip_prefix(io.BytesIO(data), 'flac',2)
        self.assertEqual(entries,[('s01.flac',b'abcd'*5000),('s02.flac',b'efgh'*5000)])
        self.assertLessEqual(count,len(data))
    def test_prefix_skips_unselected_adult_files_without_keeping_them(self):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED)as archive:
            archive.writestr('s01m16f1.flac',b'teen')
            archive.writestr('s11m25f1.flac',b'adult')
        entries,_=zip_prefix(io.BytesIO(stream.getvalue()),'flac',2,names={'s11m25f1.flac'})
        self.assertEqual(entries,[('s11m25f1.flac',b'adult')])

    def test_environment_channel_path_is_safe_and_transfer_is_bounded(self):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED)as archive:archive.writestr('OOFFICE/ch08.wav',b'noise')
        entries,_=zip_prefix(io.BytesIO(stream.getvalue()),'wav',1)
        self.assertEqual(entries,[('OOFFICE/ch08.wav',b'noise')])
        with self.assertRaises(ValueError):zip_prefix(io.BytesIO(stream.getvalue()),'wav',1,max_bytes=24)
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED)as archive:archive.writestr('../escape.wav',b'noise')
        with self.assertRaises(AssertionError):zip_prefix(io.BytesIO(stream.getvalue()),'wav',1)

    def test_corruption_and_truncation_are_rejected(self):
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w',compression=zipfile.ZIP_DEFLATED) as archive:archive.writestr('s01.flac',b'text')
        data=bytearray(buf.getvalue());data[14]^=1
        with self.assertRaises(AssertionError):zip_prefix(io.BytesIO(data),'flac',1)
        with self.assertRaises(ValueError):zip_prefix(io.BytesIO(bytes(data[:32])),'flac',1)

    def test_utterance_tier_keeps_filler_and_repetition(self):
        text=''.join('\n    item ['+str(i)+']:\n name = "'+('utt.ortho.' if i==7 else 'pWord.ortho.')+'"\n intervals [1]:\n xmin = 1\n xmax = 3\n text = "'+('어 친할 아 친할머니' if i==7 else 'wrong')+'"' for i in range(1,8))
        self.assertEqual(utterances(text),[{'start':1.0,'end':3.0,'reference':'어 친할 아 친할머니'}])

    def test_whisper_failure_is_not_scored_as_recognition(self):
        from experiments.compare_new_local_models import check_whisper_status
        check_whisper_status({'done':1,'failed':0})
        for state in ('failed','interrupted','cancelled','queued','running'):
            with self.subTest(state=state),self.assertRaises(ValueError):check_whisper_status({state:1})

    def test_whole_input_probe_keeps_the_final_utterance(self):
        from experiments.summarize_whole_transcript import messages_for
        rows=[(0,1,'첫 내용'),(2,3,'마지막 정정은 미확정')]
        messages=messages_for(rows)
        self.assertIn('s2|2-3|마지막 정정은 미확정',messages[-1]['content'])
        self.assertIn('제공되지 않은 후반 결말',messages[0]['content'])
        self.assertEqual(rows,[(0,1,'첫 내용'),(2,3,'마지막 정정은 미확정')])

    def test_padding_probe_replaces_existing_flag(self):
        import asyncio
        from unittest.mock import AsyncMock,patch
        from experiments import evaluate_mac_asr as probe
        called=AsyncMock(return_value=None)
        with patch.object(probe,'BASE_COMMAND',new=called):asyncio.run(probe.padded(['whisper','--vad','--vad-speech-pad-ms','30']))
        self.assertEqual(called.call_args.args[0],['whisper','--vad','--vad-speech-pad-ms','200'])

    def test_whole_input_probe_preserves_provider_failure(self):
        import asyncio,json,sqlite3,tempfile
        from pathlib import Path
        from unittest.mock import AsyncMock,patch
        from experiments import summarize_whole_transcript as probe
        class Engine:
            url=None
            async def start(self):return 'http://127.0.0.1:1'
            async def stop(self):pass
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary);(folder/'data').mkdir();(folder/'trace.json').write_text(json.dumps({'ready':True,'input':{'duration_seconds':3}}))
            with sqlite3.connect(folder/'data/app.sqlite3') as db:
                db.execute('CREATE TABLE transcripts(start_ms,end_ms,text,final)');db.execute("INSERT INTO transcripts VALUES(0,3000,'마지막 내용',1)")
            output=folder/'result.json'
            with patch.object(probe,'OwnedOllama',return_value=Engine()),patch.object(probe,'generate',new=AsyncMock(side_effect=ValueError('timeout'))):asyncio.run(probe.main(folder,output))
            saved=json.loads(output.read_text());self.assertFalse(saved['completed']);self.assertEqual(saved['error'],'timeout');self.assertEqual(saved['input_segments'],1)
