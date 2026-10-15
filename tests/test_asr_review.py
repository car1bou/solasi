import json,tempfile,unittest
from pathlib import Path
from unittest.mock import AsyncMock,patch
from lecture_study import audio,transcription as tr
from lecture_study.db import open_db,create_session
from lecture_study.models import SourceRef
from lecture_study.lifecycle import resolve_source,delete_audio
from lecture_study import asr_review as review

class ReviewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=open_db(self.root/'data');self.addCleanup(self.db.close)
        self.sid=create_session(self.db,'lecture','대화',None,None).id
        self.rid=audio.start_recording(self.db,self.sid,16000)
        audio.append_pcm(self.db,self.rid,0,0,16000,b'\0\1'*16000)
        self.chunk=tr.plan_chunks(self.db,self.rid,True)[0]
    def first(self,segments):
        tr.accept_transcription(self.db,self.rid,self.chunk['id'],1,True,segments)
        self.chunk=tr.range_row(self.db,self.chunk['id'])
    async def decode(self,job,text='새 전사'):
        with patch.object(tr,'transcribe_range',new=AsyncMock(return_value=[{'start_ms':0,'end_ms':1000,'text':text}]))as mock:
            result=await review.process_review(self.db,job,self.root/'runtime')
        with self.db:self.db.execute("UPDATE jobs SET status='done',result=? WHERE id=?",(json.dumps(result),job['id']))
        self.assertFalse(mock.call_args.kwargs['vad_enabled'])
        return result
    def test_conservative_signal_no_phrase_blacklist(self):
        self.first([{'start_ms':0,'end_ms':1000,'text':'감사합니다'}])
        self.assertIsNone(review.suspect_reason(self.db,self.chunk))
        self.db.execute('DELETE FROM transcripts')
        self.assertIn('빈',review.suspect_reason(self.db,self.chunk))
        long=dict(self.chunk,end_frame=16000*30)
        self.assertIsNone(review.suspect_reason(self.db,long))
    async def test_candidate_does_not_modify_first_and_apply_preserves_old_links(self):
        self.first([{'start_ms':0,'end_ms':500,'text':'첫 문장'},{'start_ms':500,'end_ms':1000,'text':'둘째 문장'}])
        old=tr.list_transcripts(self.db,self.sid);refs=[SourceRef.model_validate_json(self.db.execute('SELECT ref FROM sources WHERE id=?',(s['id']+':v1',)).fetchone()[0])for s in old]
        job=review.queue_review(self.db,self.chunk['id'],automatic=False)
        await self.decode(job)
        self.assertEqual(tr.list_transcripts(self.db,self.sid),old)
        applied=review.apply_review(self.db,job['id'],'확인한 새 전사')
        active=tr.list_transcripts(self.db,self.sid);self.assertEqual(len(active),1)
        self.assertEqual(active[0]['id'],old[0]['id']);self.assertEqual(active[0]['revision'],2)
        self.assertEqual(active[0]['original_text'],'첫 문장');self.assertEqual(active[0]['text'],'확인한 새 전사')
        self.assertEqual(self.db.execute('SELECT count(*) FROM transcripts').fetchone()[0],2)
        for ref in refs:
            source=resolve_source(self.db,ref);self.assertEqual(source['status'],'changed');self.assertIn(self.rid,source['open_url'])
        self.assertEqual(review.apply_review(self.db,job['id'],'확인한 새 전사'),applied)
        self.assertEqual(self.db.execute('SELECT count(DISTINCT source_id) FROM searchable_chunks').fetchone()[0],1)
    async def test_installed_qwen_is_frozen_as_one_candidate_without_changing_first_transcript(self):
        self.first([{'start_ms':0,'end_ms':1000,'text':'최초 전사'}]);before=tr.list_transcripts(self.db,self.sid)
        with patch('lecture_study.qwen_asr.available',return_value=True):job=review.queue_review(self.db,self.chunk['id'],automatic=False,runtime=self.root/'runtime',activity=[])
        self.assertEqual(job['request']['alternative'],'qwen3-asr-1.7b-4bit')
        with patch('lecture_study.qwen_asr.transcribe',new=AsyncMock(return_value={'text':'다른 후보','generation_tokens':5,'mlx_peak_bytes':10,'process_peak_rss_bytes':20})),patch.object(tr,'transcribe_range',new=AsyncMock(side_effect=AssertionError('second inference'))):
            result=await review.process_review(self.db,job,self.root/'runtime')
        self.assertEqual(result['text'],'다른 후보');self.assertIn('구간 전체',result['warning']);self.assertIn('음성 활동이 감지되지 않은',result['warning']);self.assertEqual(result['segments'],[{'start_ms':0,'end_ms':1000,'text':'다른 후보'}])
        self.assertEqual(tr.list_transcripts(self.db,self.sid),before)
    async def test_qwen_failure_never_runs_a_second_whisper_inference(self):
        self.first([])
        with patch('lecture_study.qwen_asr.available',return_value=True):job=review.queue_review(self.db,self.chunk['id'],automatic=True,runtime=self.root/'runtime')
        with patch('lecture_study.qwen_asr.transcribe',new=AsyncMock(side_effect=ValueError('모델 검증 실패'))),patch.object(tr,'transcribe_range',new=AsyncMock(side_effect=AssertionError('second inference'))):
            with self.assertRaisesRegex(ValueError,'검증'):await review.process_review(self.db,job,self.root/'runtime')
        self.assertIsNone(review.queue_review(self.db,self.chunk['id'],automatic=True,runtime=self.root/'runtime'))
    async def test_manual_change_makes_candidate_stale(self):
        self.first([{'start_ms':0,'end_ms':1000,'text':'기존'}]);job=review.queue_review(self.db,self.chunk['id'],automatic=False);await self.decode(job)
        tr.edit_segment(self.db,tr.list_transcripts(self.db,self.sid)[0]['id'],'사용자 수정')
        with self.assertRaisesRegex(ValueError,'변경'):review.apply_review(self.db,job['id'],'새 전사')
        self.assertEqual(tr.list_transcripts(self.db,self.sid)[0]['text'],'사용자 수정')
    async def test_empty_first_result_apply_and_once_automatic(self):
        self.first([]);job=review.queue_review(self.db,self.chunk['id'],automatic=True)
        self.assertIsNotNone(job);self.assertIsNone(review.queue_review(self.db,self.chunk['id'],automatic=True))
        await self.decode(job,'예');review.apply_review(self.db,job['id'],'예')
        row=tr.list_transcripts(self.db,self.sid)[0];self.assertEqual(row['original_text'],'');self.assertEqual(row['text'],'예')
        self.assertIsNone(review.queue_review(self.db,self.chunk['id'],automatic=True))
    async def test_deleted_audio_and_unknown_job_refused(self):
        self.first([]);job=review.queue_review(self.db,self.chunk['id'],automatic=True);await self.decode(job)
        delete_audio(self.db,self.sid)
        with self.assertRaisesRegex(ValueError,'원음'):review.apply_review(self.db,job['id'],'새 전사')
        with self.assertRaises(KeyError):review.apply_review(self.db,'missing','새 전사')
    async def test_retired_segment_hides_unpinned_question_candidate(self):
        from lecture_study.assistance import question_cards
        from lecture_study.jobs import submit_job
        from lecture_study.db import now
        self.first([{'start_ms':0,'end_ms':500,'text':'첫 문장'},{'start_ms':500,'end_ms':1000,'text':'둘째 문장'}])
        rows=tr.list_transcripts(self.db,self.sid);source=rows[1]['id']+':v1'
        card={'id':'c1','prompt':'질문','quote':'둘째 문장','source_id':source}
        stored=submit_job(self.db,self.sid,'ai',{'request':{'kind':'candidates'}})
        with self.db:self.db.execute('INSERT INTO artifacts(id,job_id,session_id,kind,body,evidence,metadata,created_at)VALUES(?,?,?,?,?,?,?,?)',('cards',stored['id'],self.sid,'candidates',json.dumps({'cards':[card]}),'[]','{}',now()))
        self.assertEqual(len(question_cards(self.db,self.sid)),1)
        job=review.queue_review(self.db,self.chunk['id'],automatic=False);await self.decode(job);review.apply_review(self.db,job['id'],'새 전사')
        self.assertEqual(question_cards(self.db,self.sid),[])
        with self.db:self.db.execute('INSERT INTO question_card_preferences VALUES(?,?,?)',(self.sid,'c1',json.dumps({'pinned':True})))
        self.assertEqual(question_cards(self.db,self.sid)[0]['source_id'],source)
    def test_empty_nonzero_ranges_offer_manual_review_without_auto_expansion(self):
        self.first([])
        with self.db:self.db.execute('UPDATE transcript_ranges SET model=? WHERE id=?',(tr.MODEL_NAME,self.chunk['id']))
        empty=review.empty_ranges(self.db,self.sid)
        self.assertEqual([r['id']for r in empty],[self.chunk['id']]);self.assertEqual(empty[0]['seek_seconds'],0)
        with self.db:self.db.execute('UPDATE transcript_ranges SET quiet=1 WHERE id=?',(self.chunk['id'],))
        self.assertEqual(review.empty_ranges(self.db,self.sid),[])
    def test_migration_retains_rows_and_active_view(self):
        self.first([{'start_ms':0,'end_ms':1000,'text':'기존'}]);before=tr.list_transcripts(self.db,self.sid)
        from tests.legacy import legacy_fixture
        legacy_fixture(self.db,14)
        upgraded=open_db(self.root/'data')
        try:
            self.assertEqual(upgraded.execute('PRAGMA user_version').fetchone()[0],17)
            self.assertEqual(tr.list_transcripts(upgraded,self.sid),before)
        finally:upgraded.close()

class ReviewApiTests(unittest.IsolatedAsyncioTestCase):
    from tests.test_transcription_api import TranscriptApiTests as _Base
    asyncSetUp=_Base.asyncSetUp
    asyncTearDown=_Base.asyncTearDown
    async def test_manual_candidate_apply_and_cancel_queued(self):
        import asyncio
        with patch.object(tr,'transcribe_range',new=AsyncMock(return_value=[{'start_ms':0,'end_ms':1000,'text':'최초'}])):
            await self.client.post('/api/recordings/'+self.rid+'/stop',json={},headers=self.headers)
            await asyncio.gather(*self.app.state.tasks)
        data=(await self.client.get('/api/sessions/'+self.sid+'/events')).json();chunk=data['transcripts'][0]['chunk_id']
        await self.app.state.generation_lock.acquire()
        try:
            job=(await self.client.post('/api/transcript-ranges/'+chunk+'/review',headers=self.headers)).json()
            await asyncio.gather(*self.app.state.tasks)
            self.assertEqual((await self.client.get('/api/jobs/'+job['id'])).json()['status'],'queued')
            cancelled=await self.client.post('/api/jobs/'+job['id']+'/cancel',headers=self.headers)
            self.assertEqual(cancelled.json()['status'],'cancelled')
        finally:self.app.state.generation_lock.release()
        with patch.object(tr,'transcribe_range',new=AsyncMock(return_value=[{'start_ms':0,'end_ms':1000,'text':'候補'}])):
            await self.client.post('/api/jobs/'+job['id']+'/retry',headers=self.headers)
            await asyncio.gather(*self.app.state.tasks)
        response=await self.client.post('/api/jobs/'+job['id']+'/apply-transcript',json={'text':'확인한 후보'},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        data=(await self.client.get('/api/sessions/'+self.sid+'/events')).json()
        self.assertEqual(data['transcripts'][0]['text'],'확인한 후보');self.assertTrue(data['asr_reviews'][0]['result']['applied'])
    async def test_auto_review_waits_for_active_generation_first_asr_finishes(self):
        import asyncio
        await self.app.state.generation_lock.acquire();decoder=AsyncMock(return_value=[])
        try:
            with patch.object(tr,'transcribe_range',new=decoder):
                stopped=await self.client.post('/api/recordings/'+self.rid+'/stop',json={},headers=self.headers)
                await asyncio.gather(*self.app.state.tasks)
                job=(await self.client.get('/api/jobs/'+stopped.json()['id'])).json()
                data=(await self.client.get('/api/sessions/'+self.sid+'/events')).json()
                self.assertEqual(job['status'],'done');self.assertEqual(data['asr_reviews'][0]['status'],'queued');self.assertEqual(decoder.await_count,1)
        finally:self.app.state.generation_lock.release()
        review_id=data['asr_reviews'][0]['id']
        deleted=await self.client.request('DELETE','/api/sessions/'+self.sid+'/audio',json={'confirmed':True},headers=self.headers)
        self.assertEqual(deleted.status_code,200,deleted.text)
        self.assertEqual((await self.client.get('/api/jobs/'+review_id)).json()['status'],'cancelled')
    async def test_new_final_preempts_manual_review(self):
        import asyncio
        started=asyncio.Event();cancelled=asyncio.Event()
        async def decoder(*args,vad_enabled=True,**kwargs):
            if not vad_enabled:
                started.set()
                try:await asyncio.Event().wait()
                finally:cancelled.set()
            return [{'start_ms':0,'end_ms':1000,'text':'최초 전사'}]
        with patch.object(tr,'transcribe_range',new=decoder):
            await self.client.post('/api/recordings/'+self.rid+'/stop',json={},headers=self.headers)
            await asyncio.gather(*self.app.state.tasks)
            row=tr.list_transcripts(self.app.state.db,self.sid)[0]
            job=(await self.client.post('/api/transcript-ranges/'+row['chunk_id']+'/review',headers=self.headers)).json()
            await asyncio.wait_for(started.wait(),1)
            rid=audio.start_recording(self.app.state.db,self.sid,48000)
            audio.append_pcm(self.app.state.db,rid,0,0,48000,b'\0\1'*48000)
            stopped=await self.client.post('/api/recordings/'+rid+'/stop',json={},headers=self.headers)
            await asyncio.wait_for(cancelled.wait(),1);await asyncio.gather(*self.app.state.tasks)
            self.assertEqual((await self.client.get('/api/jobs/'+job['id'])).json()['status'],'cancelled')
            self.assertEqual((await self.client.get('/api/jobs/'+stopped.json()['id'])).json()['status'],'done')
            self.assertEqual([s['text']for s in tr.list_transcripts(self.app.state.db,self.sid)],['최초 전사','최초 전사'])
    async def test_connecting_file_preempts_review_in_common_scheduler(self):
        import asyncio
        started=asyncio.Event();cancelled=asyncio.Event()
        async def decoder(*args,vad_enabled=True,**kwargs):
            if not vad_enabled:
                started.set()
                try:await asyncio.Event().wait()
                finally:cancelled.set()
            return [{'start_ms':0,'end_ms':1000,'text':'최초'}]
        async def registered(*args):
            rid=audio.start_recording(self.app.state.db,self.sid,48000)
            audio.append_pcm(self.app.state.db,rid,0,0,48000,b'\0\1'*48000);audio.stop_recording(self.app.state.db,rid);tr.plan_chunks(self.app.state.db,rid,True)
            return rid
        with patch.object(tr,'transcribe_range',new=decoder):
            await self.client.post('/api/recordings/'+self.rid+'/stop',json={},headers=self.headers);await asyncio.gather(*self.app.state.tasks)
            row=tr.list_transcripts(self.app.state.db,self.sid)[0]
            job=(await self.client.post('/api/transcript-ranges/'+row['chunk_id']+'/review',headers=self.headers)).json();await asyncio.wait_for(started.wait(),1)
            with patch('lecture_study.server.select_files',new=AsyncMock(return_value=[Path('fixture.wav')])),patch('lecture_study.server.register_audio',new=registered):
                response=await self.client.post('/api/sessions/'+self.sid+'/recordings',headers=self.headers)
            self.assertEqual(response.status_code,201,response.text);await asyncio.wait_for(cancelled.wait(),1);await asyncio.gather(*self.app.state.tasks)
            self.assertEqual((await self.client.get('/api/jobs/'+job['id'])).json()['status'],'cancelled')
            self.assertEqual((await self.client.get('/api/jobs/'+response.json()[0]['id'])).json()['status'],'done')
    async def test_cancelling_embedding_wakes_waiting_review(self):
        import asyncio
        from lecture_study.jobs import launch_job,submit_job
        with patch.object(tr,'transcribe_range',new=AsyncMock(return_value=[{'start_ms':0,'end_ms':1000,'text':'최초'}])):
            await self.client.post('/api/recordings/'+self.rid+'/stop',json={},headers=self.headers);await asyncio.gather(*self.app.state.tasks)
        row=tr.list_transcripts(self.app.state.db,self.sid)[0];started=asyncio.Event()
        async def embedding():
            async with self.app.state.embedding_lock:started.set();await asyncio.Event().wait()
        index=submit_job(self.app.state.db,self.sid,'index',{});launch_job(self.app,index,embedding);await started.wait()
        candidate=(await self.client.post('/api/transcript-ranges/'+row['chunk_id']+'/review',headers=self.headers)).json()
        await asyncio.wait_for(self.app.state.transcription_task,1)
        self.assertEqual((await self.client.get('/api/jobs/'+candidate['id'])).json()['status'],'queued')
        with patch.object(tr,'transcribe_range',new=AsyncMock(return_value=[{'start_ms':0,'end_ms':1000,'text':'대안'}])):
            await self.client.post('/api/jobs/'+index['id']+'/cancel',headers=self.headers)
            await asyncio.gather(*self.app.state.tasks)
        self.assertEqual((await self.client.get('/api/jobs/'+candidate['id'])).json()['status'],'done')
    async def test_shutdown_does_not_launch_queued_review(self):
        import asyncio
        from lecture_study.jobs import launch_job,submit_job
        with patch.object(tr,'transcribe_range',new=AsyncMock(return_value=[{'start_ms':0,'end_ms':1000,'text':'최초'}])):
            await self.client.post('/api/recordings/'+self.rid+'/stop',json={},headers=self.headers);await asyncio.gather(*self.app.state.tasks)
        row=tr.list_transcripts(self.app.state.db,self.sid)[0];started=asyncio.Event()
        async def embedding():started.set();await asyncio.Event().wait()
        job=submit_job(self.app.state.db,self.sid,'index',{});launch_job(self.app,job,embedding);await started.wait()
        await self.client.post('/api/transcript-ranges/'+row['chunk_id']+'/review',headers=self.headers);await asyncio.wait_for(self.app.state.transcription_task,1)
        with patch.object(tr,'transcribe_range',new=AsyncMock())as decoder:
            async with self.app.router.lifespan_context(self.app):pass
            await asyncio.sleep(0)
            decoder.assert_not_called();self.assertFalse(self.app.state.tasks)
    async def test_direct_embedding_context_defers_review_and_wakes_on_release(self):
        import asyncio
        with patch.object(tr,'transcribe_range',new=AsyncMock(return_value=[{'start_ms':0,'end_ms':1000,'text':'최초'}])):
            await self.client.post('/api/recordings/'+self.rid+'/stop',json={},headers=self.headers);await asyncio.gather(*self.app.state.tasks)
        row=tr.list_transcripts(self.app.state.db,self.sid)[0];self.app.state.ollama_url='http://127.0.0.1:11435';started=asyncio.Event();release=asyncio.Event()
        async def retrieve(*args,**kwargs):started.set();await release.wait();return {'evidence':[],'mode':'keyword','warning':''}
        with patch('lecture_study.server.retrieve',new=retrieve):
            search=asyncio.create_task(self.client.post('/api/sessions/'+self.sid+'/search',json={'query':'원문','scope':{'session_id':self.sid}},headers=self.headers));await started.wait()
            try:
                with patch.object(tr,'transcribe_range',new=AsyncMock(return_value=[{'start_ms':0,'end_ms':1000,'text':'후보'}])):
                    job=(await self.client.post('/api/transcript-ranges/'+row['chunk_id']+'/review',headers=self.headers)).json();await asyncio.wait_for(self.app.state.transcription_task,1)
                    self.assertEqual((await self.client.get('/api/jobs/'+job['id'])).json()['status'],'queued')
                    release.set();self.assertEqual((await search).status_code,200);await asyncio.gather(*self.app.state.tasks)
                    self.assertEqual((await self.client.get('/api/jobs/'+job['id'])).json()['status'],'done')
            finally:release.set();await asyncio.gather(search,return_exceptions=True)

    async def test_optional_review_file_error_does_not_stop_first_transcription_queue(self):
        import asyncio
        audio.stop_recording(self.app.state.db,self.rid);tr.plan_chunks(self.app.state.db,self.rid,True)
        rid=audio.start_recording(self.app.state.db,self.sid,48000)
        audio.append_pcm(self.app.state.db,rid,0,0,48000,b'\0\1'*48000);audio.stop_recording(self.app.state.db,rid);tr.plan_chunks(self.app.state.db,rid,True)
        with patch.object(tr,'transcribe_range',new=AsyncMock(return_value=[{'start_ms':0,'end_ms':1000,'text':'최초'}]))as decoder,patch('lecture_study.server.queue_review',side_effect=ValueError('원본 파일이 변경됨')):
            await self.client.post('/api/recordings/'+self.rid+'/stop',json={},headers=self.headers)
            await asyncio.gather(*self.app.state.tasks)
        self.assertEqual(decoder.await_count,2)
        self.assertEqual(len(tr.list_transcripts(self.app.state.db,self.sid)),2)

class ActivityReviewTests(unittest.TestCase):
    def test_partial_and_long_empty_speech_are_candidates_but_boundary_jitter_is_not(self):
        activity=[{'start_ms':0,'end_ms':5000}]
        self.assertTrue(review.uncovered_activity(activity,[{'start_ms':3000,'end_ms':5000}],0))
        self.assertTrue(review.uncovered_activity(activity,[],0))
        self.assertFalse(review.uncovered_activity(activity,[{'start_ms':200,'end_ms':4800}],0))
        self.assertFalse(review.uncovered_activity([],[],0))
    def test_overlap_is_counted_once_and_global_recording_offset_is_removed(self):
        activity=[{'start_ms':0,'end_ms':5000}]
        self.assertFalse(review.uncovered_activity(activity,[{'start_ms':10000,'end_ms':13000},{'start_ms':12000,'end_ms':15000}],10000))
        self.assertTrue(review.uncovered_activity(activity,[{'start_ms':11000,'end_ms':12000},{'start_ms':13000,'end_ms':14000}],10000))

class ActivityQueueTests(unittest.IsolatedAsyncioTestCase):
    setUp=ReviewTests.setUp
    first=ReviewTests.first
    async def test_long_empty_activity_can_queue_once_without_modifying_originals(self):
        for seq in range(1,30):audio.append_pcm(self.db,self.rid,seq,seq*16000,16000,b'\0\1'*16000)
        self.chunk=tr.plan_chunks(self.db,self.rid,True)[-1]
        self.assertTrue(tr.accept_transcription(self.db,self.rid,self.chunk['id'],self.chunk['revision'],True,[]));self.chunk=tr.range_row(self.db,self.chunk['id'])
        activity=[{'start_ms':0,'end_ms':2000}]
        job=review.queue_review(self.db,self.chunk['id'],automatic=True,activity=activity)
        self.assertIsNotNone(job);self.assertIn('누락',job['request']['reason']);self.assertEqual(job['request']['voice_activity_ranges'],activity);self.assertEqual(tr.list_transcripts(self.db,self.sid),[])
        self.assertIsNone(review.queue_review(self.db,self.chunk['id'],automatic=True,activity=activity))
    async def test_manual_edit_does_not_trigger_an_automatic_reinterpretation(self):
        self.first([{'start_ms':500,'end_ms':1000,'text':'최초'}]);row=tr.list_transcripts(self.db,self.sid)[0];tr.edit_segment(self.db,row['id'],'사용자 확인')
        self.assertIsNone(review.queue_review(self.db,self.chunk['id'],automatic=True,activity=[{'start_ms':0,'end_ms':1000}]))

class ShortRepeatReviewTests(unittest.IsolatedAsyncioTestCase):
    setUp=ReviewTests.setUp
    first=ReviewTests.first
    async def test_short_repetitions_are_candidates_and_never_deleted(self):
        from lecture_study.asr_review import suspect_reason
        self.first([{'start_ms':0,'end_ms':1000,'text':'첫째 '*8}]);chunk=self.chunk
        reason=suspect_reason(self.db,chunk)
        self.assertIn('반복',reason);self.assertIn('웃음',reason)
        self.assertEqual(tr.list_transcripts(self.db,self.sid)[0]['text'],'첫째 '*7+'첫째')
    async def test_a_short_real_repetition_alone_is_not_flagged(self):
        from lecture_study.asr_review import suspect_reason
        self.first([{'start_ms':0,'end_ms':1000,'text':'네 네 알겠습니다.'}]);chunk=self.chunk
        self.assertIsNone(suspect_reason(self.db,chunk))
