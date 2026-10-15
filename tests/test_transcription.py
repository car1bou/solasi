import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock,patch
from lecture_study.db import open_db,create_session
from lecture_study import audio
from lecture_study import transcription as tr


class TranscriptionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=open_db(self.root/'data');self.addCleanup(self.db.close)
        self.sid=create_session(self.db,"lecture","전사",None,None).id
        self.rid=audio.start_recording(self.db,self.sid,48000)

    async def test_short_final_keeps_vad_margin_and_preview_options(self):
        for seq in range(10):audio.append_pcm(self.db,self.rid,seq,seq*48000,48000,bytes([255,31])*48000)
        tr.plan_chunks(self.db,self.rid)
        decoder=AsyncMock(return_value=[{"start_ms":0,"end_ms":1000,"text":"발화"}])
        with patch.object(tr,"transcribe_range",new=decoder):
            await tr.process_pending(self.db,self.rid,self.root/"runtime")
            self.assertEqual(decoder.call_args.kwargs,{"preview":True})
            tr.plan_chunks(self.db,self.rid,stopping=True)
            await tr.process_pending(self.db,self.rid,self.root/"runtime")
        self.assertEqual(decoder.call_args.kwargs,{"padding_ms":200})

    def test_preview_waits_ten_seconds_between_updates(self):
        for seq in range(20):
            audio.append_pcm(self.db,self.rid,seq,seq*48000,48000,bytes([255,31])*48000)
            chunks=tr.plan_chunks(self.db,self.rid)
            if seq<9:self.assertEqual(chunks,[])
            else:self.assertEqual(chunks[0]['end_frame'],(10 if seq<19 else 20)*48000)
        self.assertEqual(chunks[0]['revision'],2)
        self.assertFalse(chunks[0]['final'])

    def test_final_ignores_late_provisional_and_flushes_tail(self):
        audio.append_pcm(self.db,self.rid,0,0,48000,bytes([255,31])*48000)
        chunks=tr.plan_chunks(self.db,self.rid,stopping=True)
        self.assertEqual(len(chunks),1)
        self.assertEqual(chunks[0]["end_frame"]-chunks[0]["start_frame"],48000)
        segments=[{"start_ms":0,"end_ms":1000,"text":"짧은 발화"}]
        self.assertTrue(tr.accept_transcription(self.db,self.rid,chunks[0]["id"],1,True,segments))
        self.assertFalse(tr.accept_transcription(self.db,self.rid,chunks[0]["id"],99,False,segments))
        self.assertFalse(tr.accept_transcription(self.db,self.rid,chunks[0]["id"],1,True,segments))
        result=tr.list_transcripts(self.db,self.sid)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]["end_ms"]-result[0]["start_ms"],1000)
        edited=tr.edit_segment(self.db,result[0]["id"],"사용자 수정")
        self.assertEqual(edited["original_text"],"짧은 발화")
        self.assertEqual(edited["start_ms"],0)
        self.assertEqual(edited["revision"],2)

    def test_boundaries_quiet_and_gap_mapping(self):
        # 3.0 seconds of speech, then 0.8 seconds of silence.
        for seq in range(15):
            payload=bytes([255,31])*12000 if seq<12 else bytes(24000)
            audio.append_pcm(self.db,self.rid,seq,seq*12000,12000,payload)
            tr.plan_chunks(self.db,self.rid)
        audio.append_pcm(self.db,self.rid,15,180000,2400,bytes(4800))
        chunks=tr.plan_chunks(self.db,self.rid)
        final=[c for c in chunks if c["final"]]
        self.assertEqual(final[0]["end_frame"],182400)
        audio.append_pcm(self.db,self.rid,16,230400,12000,bytes([255,31])*12000)
        chunks=tr.plan_chunks(self.db,self.rid,stopping=True)
        tail=chunks[-1]
        self.assertEqual(tail["start_frame"],230400)
        self.assertEqual(tail["stored_start"],182400)
        self.assertTrue(tr.accept_transcription(self.db,self.rid,tail["id"],1,True,[{"start_ms":0,"end_ms":250,"text":"재개"}]))
        result=tr.list_transcripts(self.db,self.sid)[0]
        self.assertEqual((result["start_ms"],result["end_ms"]),(4800,5050))

    async def test_worker_failure_keeps_original_and_retry_is_idempotent(self):
        audio.append_pcm(self.db,self.rid,0,0,48000,bytes([255,31])*48000)
        tr.plan_chunks(self.db,self.rid,stopping=True)
        path=audio.recording_path(self.db,self.rid)
        with patch.object(tr,"transcribe_range",new=AsyncMock(side_effect=ValueError("엔진 실패"))):
            await tr.process_pending(self.db,self.rid,self.root/"runtime")
        self.assertTrue(path.is_file())
        self.assertEqual(tr.transcription_status(self.db,self.rid)["failed"],1)
        with patch.object(tr,"transcribe_range",new=AsyncMock(return_value=[{"start_ms":0,"end_ms":1000,"text":"완료"}])):
            await tr.process_pending(self.db,self.rid,self.root/"runtime",retry=True)
            await tr.process_pending(self.db,self.rid,self.root/"runtime",retry=True)
        self.assertEqual(len(tr.list_transcripts(self.db,self.sid)),1)

    def test_json_offsets_clamped_to_actual_audio(self):
        segments=tr.parse_segments({"transcription":[{"offsets":{"from":0,"to":1200},"text":"말"}]},1000,500)
        self.assertEqual((segments[0]["start_ms"],segments[0]["end_ms"]),(500,1500))
        with self.assertRaises(ValueError):
            tr.parse_segments({"transcription":[{"offsets":{"from":-1,"to":2},"text":"말"}]},1000,0)

    async def test_external_audio_is_referenced_and_changed_file_refused(self):
        audio.stop_recording(self.db,self.rid)
        import wave,math
        from array import array
        runtime=Path(__file__).resolve().parents[1]/".local-state/runtime"
        source=self.root/"source.wav"
        values=array("h",(round(9000*math.sin(2*math.pi*440*n/48000)) for n in range(48000)))
        with wave.open(str(source),"wb") as out:
            out.setnchannels(1);out.setsampwidth(2);out.setframerate(48000);out.writeframes(values.tobytes())
        rid=await tr.register_audio(self.db,self.sid,source,runtime)
        self.assertEqual(tr.get_recording(self.db,rid)["external_path"],str(source.resolve()))
        self.assertFalse((self.root/"data"/"audio"/rid/"raw.wav").exists())
        with patch.object(tr,"transcribe_range",new=AsyncMock(return_value=[{"start_ms":0,"end_ms":1000,"text":"파일 전사"}])):
            await tr.process_pending(self.db,rid,runtime)
        self.assertEqual(len([s for s in tr.list_transcripts(self.db,self.sid) if s["recording_id"]==rid]),1)
        source.write_bytes(source.read_bytes()+b"changed")
        chunk=tr.plan_chunks(self.db,rid)[0]
        with self.assertRaises(ValueError):
            await tr.external_clip(self.db,tr.get_recording(self.db,rid),chunk,self.root/"clip.wav",runtime)

    async def test_real_local_asr_offsets_and_no_temporary_original_copy(self):
        import wave
        runtime=Path(__file__).resolve().parents[1]/".local-state/runtime"
        source=runtime/"transcription-smoke-20261013/korean-yuna-16k-mono.wav"
        if not source.is_file(): self.skipTest("별도 준비한 합성 음성·런타임 없음")
        result=await tr.transcribe_range(source,500,"",runtime)
        self.assertTrue(result)
        with wave.open(str(source)) as audio:
            duration=round(audio.getnframes()*1000/audio.getframerate())
        self.assertTrue(all(500<=s["start_ms"]<s["end_ms"]<=500+duration for s in result))
        self.assertIn("프로세스는 실행 중인 프로그램", " ".join(s["text"] for s in result))

    def test_restart_marks_active_range_retryable_and_keeps_raw(self):
        from lecture_study.server import create_app
        from lecture_study.config import AppConfig
        audio.append_pcm(self.db,self.rid,0,0,48000,bytes([255,31])*48000)
        chunk=tr.plan_chunks(self.db,self.rid,stopping=True)[0]
        with self.db: self.db.execute("UPDATE transcript_ranges SET status='running' WHERE id=?",(chunk["id"],))
        app=create_app(AppConfig(self.root/"data",self.root/"runtime"))
        self.assertEqual(tr.range_row(app.state.db,chunk["id"])["status"],"interrupted")
        self.assertTrue(audio.recording_path(app.state.db,self.rid).is_file())
        app.state.db.close()

    def test_low_volume_signal_keeps_context_until_stop(self):
        # A fixed amplitude threshold must not repeatedly cut quiet speech.
        for seq in range(20):
            audio.append_pcm(self.db,self.rid,seq,seq*12000,12000,bytes([200,0])*12000)
            tr.plan_chunks(self.db,self.rid)
        chunks=tr.plan_chunks(self.db,self.rid)
        self.assertFalse(any(c["final"] for c in chunks))
        chunks=tr.plan_chunks(self.db,self.rid,stopping=True)
        self.assertEqual([(c["start_frame"],c["end_frame"]) for c in chunks],[(0,240000)])

    async def test_low_volume_signal_is_not_discarded_as_silence(self):
        audio.append_pcm(self.db,self.rid,0,0,48000,bytes([200,0])*48000)
        tr.plan_chunks(self.db,self.rid,stopping=True)
        with patch.object(tr,"transcribe_range",new=AsyncMock(return_value=[{"start_ms":0,"end_ms":1000,"text":"작은 음량 발화"}])):
            await tr.process_pending(self.db,self.rid,self.root/"runtime")
        self.assertEqual([s["text"] for s in tr.list_transcripts(self.db,self.sid)],["작은 음량 발화"])

    async def test_native_vad_rejects_near_silent_human_tail(self):
        runtime=Path(__file__).resolve().parents[1]/".local-state/runtime"
        source=runtime/"human-audio-20261013/fleurs-ko-test-0002-animals-place.wav"
        if not source.is_file(): self.skipTest("별도 공개 사람 음성 fixture 없음")
        clip=self.root/"tail.wav"
        await tr.command([runtime/"ffmpeg/bin/ffmpeg","-nostdin","-v","error","-y","-ss","7.1","-i",source,"-t","1.84","-ac","1","-ar","16000","-c:a","pcm_s16le",clip])
        self.assertEqual(await tr.transcribe_range(clip,7100,"",runtime,padding_ms=200),[])

    async def test_native_vad_keeps_leading_silence_on_source_clock(self):
        import wave
        runtime=Path(__file__).resolve().parents[1]/".local-state/runtime"
        source=runtime/"transcription-smoke-20261013/korean-yuna-16k-mono.wav"
        if not source.is_file(): self.skipTest("별도 전사 런타임 fixture 없음")
        clip=self.root/"leading.wav"
        with wave.open(str(source)) as original:
            payload=original.readframes(original.getnframes())
        with wave.open(str(clip),"wb") as out:
            out.setnchannels(1);out.setsampwidth(2);out.setframerate(16000);out.writeframes(bytes(32000)+payload)
        result=await tr.transcribe_range(clip,500,"",runtime)
        self.assertTrue(result)
        self.assertGreaterEqual(result[0]["start_ms"],1300)
        self.assertLessEqual(result[-1]["end_ms"],11819)


    async def test_file_import_is_blocked_during_live_and_probe_race(self):
        import wave,json
        source=self.root/'source.wav'
        with wave.open(str(source),'wb') as out:out.setnchannels(1);out.setsampwidth(2);out.setframerate(16000);out.writeframes(b'\0\1'*16000)
        runtime=self.root/'runtime';probe=runtime/'ffmpeg/bin/ffprobe';probe.parent.mkdir(parents=True);probe.write_bytes(b'fixture')
        with patch.object(tr,'command',new=AsyncMock()) as command:
            with self.assertRaisesRegex(ValueError,'녹음을 종료'):await tr.register_audio(self.db,self.sid,source,runtime)
            command.assert_not_called()
        audio.stop_recording(self.db,self.rid)
        async def race(*args):
            audio.start_recording(self.db,self.sid,48000)
            return json.dumps({'streams':[{'sample_rate':'16000','channels':1,'duration':'1'}]}).encode()
        with patch.object(tr,'command',new=race):
            with self.assertRaisesRegex(ValueError,'녹음을 종료'):await tr.register_audio(self.db,self.sid,source,runtime)
        self.assertEqual(self.db.execute("SELECT count(*) FROM recordings WHERE kind='file'").fetchone()[0],0)


class ModelTests(unittest.TestCase):
    def test_engine_requires_turbo_and_checks_pinned_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime=Path(temp)
            for name in ('ffmpeg/bin/ffmpeg','build/whisper/bin/whisper-cli','models/ggml-base.bin'):
                path=runtime/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixture')
            with self.assertRaisesRegex(ValueError,'large-v3-turbo'):
                tr.engine_paths(runtime)
            model=runtime/'models/ggml-large-v3-turbo.bin';model.write_bytes(b'fixture')
            with self.assertRaisesRegex(ValueError,'검증 실패'): tr.engine_paths(runtime)
            with patch.object(tr,'verify_model') as verify:
                paths=tr.engine_paths(runtime)
            self.assertEqual(paths[2],model)
            verify.assert_called_once_with(model,tr.MODEL_SHA)

    def test_upgrade_preserves_old_model_and_prompt(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);old=open_db(root)
            sid=create_session(old,'lecture','기존 전사',None,None).id
            rid=audio.start_recording(old,sid,48000)
            audio.append_pcm(old,rid,0,0,48000,bytes([255,31])*48000)
            chunk=tr.plan_chunks(old,rid,True)[0]
            with old:
                old.execute("UPDATE transcript_ranges SET prompt='이전 명칭',status='done' WHERE id=?",(chunk['id'],))
                if 'model' in {r['name'] for r in old.execute('PRAGMA table_info(transcript_ranges)')}:
                    old.execute('ALTER TABLE transcript_ranges DROP COLUMN model')
                old.execute('PRAGMA user_version=6')
            old.close()
            upgraded=open_db(root)
            try:
                row=tr.range_row(upgraded,chunk['id'])
                self.assertEqual(row['model'],'base')
                self.assertEqual(row['prompt'],'이전 명칭')
                self.assertEqual(row['status'],'done')
                self.assertEqual(upgraded.execute('PRAGMA user_version').fetchone()[0],16)
            finally: upgraded.close()

class TimestampGapTests(unittest.TestCase):
    def test_multiple_capture_gaps_keep_transcript_and_playback_clocks_separate(self):
        from lecture_study.lifecycle import playback_position
        with tempfile.TemporaryDirectory()as temp:
            db=open_db(Path(temp))
            try:
                for rate in (44100,48000):
                    sid=create_session(db,'lecture','시간축',None,None).id;rid=audio.start_recording(db,sid,rate)
                    for seq,first in enumerate((0,rate*3//2,rate*11//4)):
                        audio.append_pcm(db,rid,seq,first,rate,bytes([255,31])*rate)
                    audio.stop_recording(db,rid);chunks=tr.plan_chunks(db,rid,True)
                    self.assertEqual(len(chunks),3)
                    for chunk in chunks:self.assertTrue(tr.accept_transcription(db,rid,chunk['id'],chunk['revision'],True,[{'start_ms':100,'end_ms':500,'text':'원음 연결'}]))
                    rows=tr.list_transcripts(db,sid)
                    self.assertEqual([(r['start_ms'],r['end_ms'])for r in rows],[(100,500),(1600,2000),(2850,3250)])
                    self.assertEqual([playback_position(db,rid,r['start_ms'])for r in rows],[.1,1.1,2.1])
                    for gap in (1250,2600):
                        with self.assertRaisesRegex(ValueError,'누락'):playback_position(db,rid,gap)
            finally:db.close()

class OfflinePaddingTests(unittest.IsolatedAsyncioTestCase):
    setUp=TranscriptionTests.setUp
    async def test_after_stop_final_retains_quiet_leading_context(self):
        audio.stop_recording(self.db,self.rid)
        rid=audio.start_recording(self.db,self.sid,48000,'after_stop')
        audio.append_pcm(self.db,rid,0,0,48000,bytes([255,31])*48000);audio.stop_recording(self.db,rid)
        with self.db:self.db.execute('UPDATE recordings SET transcription_released=1 WHERE id=?',(rid,))
        tr.plan_chunks(self.db,rid,True)
        decoder=AsyncMock(return_value=[{'start_ms':0,'end_ms':1000,'text':'약한 첫 발화'}])
        with patch.object(tr,'transcribe_range',new=decoder):await tr.process_pending(self.db,rid,self.root/'runtime')
        self.assertEqual(decoder.call_args.kwargs,{'padding_ms':1000});self.assertEqual(tr.transcription_status(self.db,rid)['done'],1)

class ActivityParserTests(unittest.TestCase):
    def test_native_centiseconds_and_final_vad_window_are_bounded(self):
        body=b'Detected 1 speech segments:\nSpeech segment 0: start = 10.00, end = 214.00\n'
        self.assertEqual(tr.parse_activity(body,2118),[{'start_ms':100,'end_ms':2118}])
        for bad in [b'Detected 2 speech segments:\n',b'Detected 1 speech segments:\nSpeech segment 0: start = 0.00, end = 999.00\n']:
            with self.assertRaises(ValueError):tr.parse_activity(bad,2118)
        self.assertEqual(tr.parse_activity(b'Detected 0 speech segments:\n',2118),[])

class OptionalActivityTests(unittest.IsolatedAsyncioTestCase):
    setUp=TranscriptionTests.setUp
    async def test_failed_optional_scan_keeps_completed_first_transcript(self):
        audio.append_pcm(self.db,self.rid,0,0,48000,bytes([255,31])*48000);tr.plan_chunks(self.db,self.rid,True)
        with patch.object(tr,'transcribe_range',new=AsyncMock(return_value=[{'start_ms':0,'end_ms':1000,'text':'최초 전사'}])),patch.object(tr,'speech_activity',new=AsyncMock(side_effect=ValueError('진단 불가'))):
            await tr.process_pending(self.db,self.rid,self.root/'runtime')
        self.assertEqual(tr.transcription_status(self.db,self.rid)['done'],1);self.assertEqual(tr.list_transcripts(self.db,self.sid)[0]['text'],'최초 전사')
    async def test_48khz_activity_input_is_normalized_before_native_detection(self):
        runtime=self.root/'runtime';utility=runtime/'build/whisper/bin/whisper-vad-speech-segments';utility.parent.mkdir(parents=True);utility.touch()
        original=self.root/'source.wav'
        with __import__('wave').open(str(original),'wb')as handle:handle.setnchannels(1);handle.setsampwidth(2);handle.setframerate(48000);handle.writeframes(b'\0\1'*48000)
        async def command(argv,**kwargs):
            if argv[0]=='ffmpeg':
                with __import__('wave').open(str(argv[-1]),'wb')as handle:handle.setnchannels(1);handle.setsampwidth(2);handle.setframerate(16000);handle.writeframes(b'\0\1'*16000)
                return b''
            with __import__('wave').open(str(argv[argv.index('-f')+1]))as handle:self.assertEqual(handle.getframerate(),16000)
            return b'Detected 1 speech segments:\nSpeech segment 0: start = 0.00, end = 100.00\n'
        with patch.object(tr,'engine_paths',return_value=('ffmpeg','whisper','model')),patch.object(tr,'verify_model'),patch.object(tr,'command',new=AsyncMock(side_effect=command))as native:
            self.assertEqual(await tr.speech_activity(original,runtime),[{'start_ms':0,'end_ms':1000}])
        self.assertEqual(native.await_count,2)

    async def test_float32_wav_is_normalized_instead_of_rejected_by_python_wave(self):
        import struct
        runtime=self.root/'runtime';utility=runtime/'build/whisper/bin/whisper-vad-speech-segments';utility.parent.mkdir(parents=True);utility.touch()
        original=self.root/'float.wav';pcm=struct.pack('<f',.1)*16000;fmt=struct.pack('<HHIIHH',3,1,16000,64000,4,32)
        original.write_bytes(b'RIFF'+struct.pack('<I',36+len(pcm))+b'WAVEfmt '+struct.pack('<I',16)+fmt+b'data'+struct.pack('<I',len(pcm))+pcm)
        async def command(argv,**kwargs):
            if argv[0]=='ffmpeg':
                with __import__('wave').open(str(argv[-1]),'wb')as handle:handle.setnchannels(1);handle.setsampwidth(2);handle.setframerate(16000);handle.writeframes(b'\0\1'*16000)
                return b''
            return b'Detected 0 speech segments:\n'
        with patch.object(tr,'engine_paths',return_value=('ffmpeg','whisper','model')),patch.object(tr,'verify_model'),patch.object(tr,'command',new=AsyncMock(side_effect=command))as native:self.assertEqual(await tr.speech_activity(original,runtime),[])
        self.assertEqual(native.await_count,2)

    async def test_unexpected_optional_failure_cannot_mark_saved_transcription_failed(self):
        audio.append_pcm(self.db,self.rid,0,0,48000,bytes([255,31])*48000);tr.plan_chunks(self.db,self.rid,True)
        with patch.object(tr,'transcribe_range',new=AsyncMock(return_value=[{'start_ms':0,'end_ms':1000,'text':'먼저 보존'}])),patch.object(tr,'speech_activity',new=AsyncMock(side_effect=KeyError('receipt changed'))):await tr.process_pending(self.db,self.rid,self.root/'runtime')
        self.assertEqual(tr.transcription_status(self.db,self.rid)['done'],1);self.assertEqual(tr.list_transcripts(self.db,self.sid)[0]['text'],'먼저 보존')
