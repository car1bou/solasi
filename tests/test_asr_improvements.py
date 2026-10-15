import asyncio,json,tempfile,unittest,wave
from pathlib import Path
from unittest.mock import AsyncMock,patch
from lecture_study import transcription as tr
from lecture_study.db import open_db,create_session,new_id,now
from lecture_study.retrieval import save_term
from lecture_study.outputs import save_participants

class HintTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=open_db(self.root/'data');self.addCleanup(self.db.close)

    def test_registered_course_terms_and_current_participants_only(self):
        course=new_id()
        with self.db:self.db.execute('INSERT INTO courses VALUES (?,?,?,?)',(course,'지리','',now()))
        previous=create_session(self.db,'lecture','이전',course,1).id
        current=create_session(self.db,'lecture','현재',course,2).id
        other=create_session(self.db,'lecture','다른 과목',None,None).id
        term=save_term(self.db,previous,'옛 표기',[],'',[])
        save_term(self.db,previous,'세풀베다',[],'',[],term)
        save_term(self.db,other,'다른 과목 이름',[],'',[])
        tr.save_asr_terms(self.db,current,['깁슨'])
        save_term(self.db,current,'제어'+chr(0)+'문자',[],'',[])
        self.assertEqual(tr.asr_prompt(self.db,current),'깁슨, 세풀베다')
        meeting=create_session(self.db,'meeting','회의',None,None).id
        another=create_session(self.db,'meeting','다른 회의',None,None).id
        save_participants(self.db,meeting,['김민수']);save_participants(self.db,another,['이서연'])
        self.assertEqual(tr.asr_prompt(self.db,meeting),'김민수')
        save_participants(self.db,meeting,[])
        self.assertEqual(tr.asr_prompt(self.db,meeting),'')

    def test_manual_hints_keep_priority_and_automatic_terms_do_not_split(self):
        sid=create_session(self.db,'lecture','전사',None,None).id
        manual='가'*63
        tr.save_asr_terms(self.db,sid,[manual])
        save_term(self.db,sid,'가나다라마',[],'',[])
        save_term(self.db,sid,'북해',[],'',[])
        prompt=tr.asr_prompt(self.db,sid)
        self.assertEqual(prompt,manual+', 북해')
        self.assertLessEqual(len(prompt.encode()),200)

class NativeOptionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_previews_use_greedy_without_temperature_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source.wav';calls=[]
            async def run(argv,*args):
                calls.append(list(map(str,argv)))
                if '-of' in argv:
                    Path(str(argv[argv.index('-of')+1])+'.json').write_text(json.dumps({'transcription':[{'offsets':{'from':0,'to':1000},'text':'말'}]}))
                else:
                    with wave.open(str(argv[-1]),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\1\0'*16000)
                return b''
            with patch.object(tr,'engine_paths',return_value=(root/'ffmpeg',root/'whisper',root/'model')),patch.object(tr,'verify_model'),patch.object(tr,'command',new=run):
                result=await tr.transcribe_range(source,0,'',root)
            self.assertEqual(result[0]['text'],'말')
            argv=calls[-1]
            self.assertNotIn('-bs',argv)
            self.assertEqual(argv[argv.index('--vad-speech-pad-ms')+1],'30')
            with patch.object(tr,'engine_paths',return_value=(root/'ffmpeg',root/'whisper',root/'model')),patch.object(tr,'verify_model'),patch.object(tr,'command',new=run):
                await tr.transcribe_range(source,0,'',root,preview=True,padding_ms=200)
            argv=calls[-1]
            self.assertEqual(argv[argv.index('-bs')+1],'1')
            self.assertEqual(argv[argv.index('-bo')+1],'1')
            self.assertIn('-nf',argv)
            self.assertEqual(argv[argv.index('--vad-speech-pad-ms')+1],'200')

class BoundaryTests(unittest.TestCase):
    def test_cut_prefers_quiet_gap_and_keeps_constant_low_volume(self):
        from array import array
        signal=array('h',[200])*480000
        self.assertEqual(tr.quiet_cut(signal,16000),480000)
        signal[27*16000:28*16000]=array('h',[1])*16000
        self.assertTrue(27*16000<tr.quiet_cut(signal,16000)<28*16000)
        self.assertEqual(tr.quiet_cut(signal[:16000],16000),16000)

    def test_live_adaptive_split_covers_every_frame_and_never_crosses_a_gap(self):
        from array import array
        from lecture_study import audio
        with tempfile.TemporaryDirectory() as temp:
            db=open_db(Path(temp));self.addCleanup(db.close)
            sid=create_session(db,'lecture','경계',None,None).id;rid=audio.start_recording(db,sid,16000)
            signal=array('h',[200])*560000;signal[27*16000:28*16000]=array('h',[1])*16000
            for seq in range(140):
                audio.append_pcm(db,rid,seq,seq*4000,4000,signal[seq*4000:(seq+1)*4000].tobytes());tr.plan_chunks(db,rid)
            chunks=tr.plan_chunks(db,rid,True)
            self.assertLess(chunks[0]['end_frame'],480000)
            self.assertEqual(chunks[0]['start_frame'],0);self.assertEqual(chunks[-1]['end_frame'],560000)
            self.assertTrue(all(a['end_frame']==b['start_frame'] and a['stored_end']==b['stored_start'] for a,b in zip(chunks,chunks[1:])))

class FileBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_file_boundaries_stream_pcm_and_preserve_external_original(self):
        from array import array
        from lecture_study import audio
        runtime=Path(__file__).resolve().parents[1]/'.local-state/runtime'
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);binaries=root/'runtime/ffmpeg/bin';binaries.mkdir(parents=True)
            for name in ('ffmpeg','ffprobe'):(binaries/name).symlink_to(runtime/'ffmpeg/bin'/name)
            runtime=root/'runtime'
            source=root/'long.wav';signal=array('h',[200])*560000
            signal[27*16000:28*16000]=array('h',[1])*16000
            with wave.open(str(source),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(signal.tobytes())
            original=tr.file_hash(source);db=open_db(root/'data');self.addCleanup(db.close)
            sid=create_session(db,'lecture','파일 경계',None,None).id
            rid=await tr.register_audio(db,sid,source,runtime)
            chunks=tr.plan_chunks(db,rid)
            self.assertLess(chunks[0]['end_frame'],480000)
            self.assertEqual(sum(c['end_frame']-c['start_frame'] for c in chunks),560000)
            self.assertEqual(tr.file_hash(source),original)
            self.assertFalse((root/'data/audio'/rid/'raw.wav').exists())

    async def test_cancelled_boundary_scan_stops_its_decoder(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        started=asyncio.Event()
        async def read(_):started.set();await asyncio.Event().wait()
        process=SimpleNamespace(stdout=SimpleNamespace(readexactly=read),returncode=None,wait=AsyncMock(return_value=0),communicate=AsyncMock(return_value=(b'',b'')),kill=Mock())
        process.terminate=Mock(side_effect=lambda:setattr(process,'returncode',0))
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);binary=root/'ffmpeg/bin/ffmpeg';binary.parent.mkdir(parents=True);binary.touch()
            with patch.object(asyncio,'create_subprocess_exec',new=AsyncMock(return_value=process)):
                task=asyncio.create_task(tr.file_boundaries(root/'audio.wav',480000,16000,root))
                await asyncio.wait_for(started.wait(),1);task.cancel()
                with self.assertRaises(asyncio.CancelledError):await task
            process.terminate.assert_called_once();process.communicate.assert_awaited_once();process.kill.assert_not_called()

    async def test_boundary_scan_timeout_is_reported_and_decoder_stopped(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        process=SimpleNamespace(stdout=SimpleNamespace(readexactly=AsyncMock(side_effect=TimeoutError)),returncode=None,wait=AsyncMock(return_value=0),communicate=AsyncMock(return_value=(b'',b'')),kill=Mock())
        process.terminate=Mock(side_effect=lambda:setattr(process,'returncode',0))
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);binary=root/'ffmpeg/bin/ffmpeg';binary.parent.mkdir(parents=True);binary.touch()
            with patch.object(asyncio,'create_subprocess_exec',new=AsyncMock(return_value=process)):
                with self.assertRaisesRegex(ValueError,'제한 시간'):await tr.file_boundaries(root/'audio.wav',480000,16000,root)
        process.terminate.assert_called_once();process.communicate.assert_awaited_once()

class ProcessCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_parent_cancel_waits_for_already_preempted_child_process(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        started=asyncio.Event();terminating=asyncio.Event();released=asyncio.Event();calls=0;holder=[]
        async def wait():
            await released.wait();process.returncode=0;return 0
        async def communicate():
            nonlocal calls
            calls+=1
            if calls==1:started.set();await asyncio.Event().wait()
            await wait();return b'',b''
        process=SimpleNamespace(returncode=None,communicate=communicate,wait=wait,terminate=Mock(side_effect=terminating.set),kill=Mock())
        async def worker():
            child=asyncio.create_task(tr.command(['fake-native']));holder.append(child);await child
        with patch.object(asyncio,'create_subprocess_exec',new=AsyncMock(return_value=process)):
            parent=asyncio.create_task(worker())
            try:
                await asyncio.wait_for(started.wait(),1);holder[0].cancel();await asyncio.wait_for(terminating.wait(),1)
                parent.cancel();await asyncio.sleep(0);await asyncio.sleep(0)
                self.assertFalse(parent.done(),'worker returned before native process was reaped')
                released.set()
                with self.assertRaises(asyncio.CancelledError):await parent
                self.assertEqual(process.returncode,0)
            finally:
                released.set();await asyncio.gather(parent,return_exceptions=True)

    async def test_cleanup_kills_after_graceful_timeout(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        started=asyncio.Event();calls=0
        async def communicate():
            nonlocal calls
            calls+=1
            if calls==1:started.set();await asyncio.Event().wait()
            if calls==2:raise TimeoutError
            return b'',b''
        process=SimpleNamespace(returncode=None,communicate=communicate,wait=AsyncMock(return_value=-9),terminate=Mock())
        process.kill=Mock(side_effect=lambda:setattr(process,'returncode',-9))
        with patch.object(asyncio,'create_subprocess_exec',new=AsyncMock(return_value=process)):
            task=asyncio.create_task(tr.command(['fake-native']));await asyncio.wait_for(started.wait(),1);task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
        process.kill.assert_called_once();self.assertEqual(calls,3)


class TokenScoreDiagnosticTests(unittest.TestCase):
    def test_score_sidecar_is_not_text_or_calibrated_confidence(self):
        from experiments.evaluate_sentence_asr import token_scores
        self.assertEqual(token_scores(b'word\t0.5\n[_SOT_]\t1.0\n\t0.1\n<|end|>\t1\n'),[.5])
        self.assertEqual(token_scores(b''),[])
        for value in (b'nan',b'1.1',b'-0.1',b'inf',b'bad'):
            with self.assertRaises(ValueError):token_scores(b'word\t'+value)
