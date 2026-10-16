import asyncio,json,tempfile,unittest
from pathlib import Path
from unittest.mock import AsyncMock,patch
import httpx
from lecture_study.server import create_app
from lecture_study.config import AppConfig
from lecture_study.db import create_session,open_db
from lecture_study.audio import append_pcm,get_recording,start_recording,stop_recording
from lecture_study.transcription import plan_chunks,accept_transcription

class RecordingModeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.app=create_app(AppConfig(Path(self.temp.name),Path(self.temp.name)/'runtime',port=8765));self.db=self.app.state.db
        self.sid=create_session(self.db,'lecture','종료 후 처리',None,None).id
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url='http://127.0.0.1:8765')
        self.headers={'Origin':'http://127.0.0.1:8765'}
        r=await self.client.post('/api/bootstrap',json={'token':self.app.state.bootstrap_token},headers=self.headers);self.headers['X-Session-Token']=r.json()['csrf_token']
        async def processed(db,chunk,runtime):
            duration=round((chunk['end_frame']-chunk['start_frame'])*1000/16000)
            accept_transcription(db,chunk['recording_id'],chunk['id'],chunk['revision'],bool(chunk['final']),[{'start_ms':0,'end_ms':duration,'text':'확정 전사입니다.'}])
        self.native=AsyncMock(side_effect=processed);self.patch=patch('lecture_study.server.process_chunk',new=self.native);self.patch.start();self.addCleanup(self.patch.stop)
        self.review=patch('lecture_study.server.queue_review',return_value=None);self.review.start();self.addCleanup(self.review.stop)
    async def asyncTearDown(self):
        self.app.state.closing=True
        for task in list(self.app.state.tasks):task.cancel()
        await asyncio.gather(*self.app.state.tasks,return_exceptions=True)
        await self.client.aclose();self.db.close()
    async def start(self,**options):
        r=await self.client.post('/api/sessions/'+self.sid+'/audio/start',json={'sample_rate':16000,**options},headers=self.headers);self.assertEqual(r.status_code,201,r.text);return r.json()['recording_id']
    def pcm(self,rid,seconds=3):
        for seq in range(seconds):append_pcm(self.db,rid,seq,seq*16000,16000,b'\1\0'*16000)
    async def stop(self,rid,**options):
        r=await self.client.post('/api/recordings/'+rid+'/stop',json=options,headers=self.headers);self.assertEqual(r.status_code,200,r.text);return r.json()
    async def settled(self):
        for _ in range(40):await asyncio.sleep(.005)
    async def test_api_default_stores_raw_without_asr_then_starts_on_stop(self):
        rid=await self.start();row=get_recording(self.db,rid);self.assertEqual(row['transcription_mode'],'after_stop');self.assertFalse(row['transcription_released'])
        self.pcm(rid,35);self.assertEqual(plan_chunks(self.db,rid),[]);self.app.state.kick_transcription();await self.settled();self.assertEqual(self.native.await_count,0)
        job=await self.stop(rid);await self.settled();self.assertTrue(get_recording(self.db,rid)['transcription_released']);self.assertGreater(self.native.await_count,0)
        self.assertEqual(self.db.execute('SELECT status FROM jobs WHERE id=?',(job['id'],)).fetchone()[0],'done')
    async def test_explicit_realtime_keeps_live_planning(self):
        rid=await self.start(transcription_mode='realtime');self.pcm(rid,35);self.assertTrue(plan_chunks(self.db,rid));self.app.state.kick_transcription();await self.settled();self.assertGreater(self.native.await_count,0)
    async def test_recovery_segments_wait_together_and_duplicate_stop_never_revokes_release(self):
        first=await self.start();self.pcm(first);job=await self.stop(first,interrupted=True,defer_transcription=True)
        self.app.state.kick_transcription();await self.settled();self.assertEqual(self.native.await_count,0)
        self.assertEqual(self.db.execute('SELECT status FROM jobs WHERE id=?',(job['id'],)).fetchone()[0],'queued')
        second=await self.start(resume_from=first);self.assertEqual(get_recording(self.db,first)['capture_id'],get_recording(self.db,second)['capture_id']);self.pcm(second)
        await self.stop(second);await self.settled();self.assertEqual(self.native.await_count,2)
        await self.stop(first,interrupted=True,defer_transcription=True)
        self.assertTrue(get_recording(self.db,first)['transcription_released']);self.assertTrue(get_recording(self.db,second)['transcription_released'])
    async def test_resume_cannot_change_mode_or_take_another_session(self):
        rid=await self.start();await self.stop(rid,interrupted=True,defer_transcription=True)
        bad=await self.client.post('/api/sessions/'+self.sid+'/audio/start',json={'sample_rate':16000,'resume_from':rid,'transcription_mode':'realtime'},headers=self.headers);self.assertEqual(bad.status_code,422)
        other=create_session(self.db,'lecture','다른 수업',None,None).id
        bad=await self.client.post('/api/sessions/'+other+'/audio/start',json={'sample_rate':16000,'resume_from':rid},headers=self.headers);self.assertEqual(bad.status_code,422)
    async def test_planning_failure_cannot_be_reported_as_done(self):
        rid=await self.start();self.pcm(rid)
        with patch('lecture_study.server.plan_chunks',side_effect=ValueError('원음 계획 실패')):job=await self.stop(rid)
        self.app.state.kick_transcription();await self.settled();self.assertEqual(self.db.execute('SELECT status FROM jobs WHERE id=?',(job['id'],)).fetchone()[0],'failed')
    async def test_invalid_mode_is_rejected(self):
        r=await self.client.post('/api/sessions/'+self.sid+'/audio/start',json={'sample_rate':16000,'transcription_mode':'fast'},headers=self.headers);self.assertEqual(r.status_code,422)

    async def test_device_rate_change_keeps_recovery_group(self):
        rid=await self.start();await self.stop(rid,interrupted=True,defer_transcription=True)
        r=await self.client.post('/api/sessions/'+self.sid+'/audio/start',json={'sample_rate':48000,'resume_from':rid},headers=self.headers)
        self.assertEqual(r.status_code,201,r.text);self.assertEqual(get_recording(self.db,r.json()['recording_id'])['capture_id'],rid)

    async def test_orphan_disconnect_grace_releases_but_active_recovery_holds(self):
        from lecture_study import server
        with patch.object(server,'AUDIO_RELEASE_SECONDS',.03):
            rid=await self.start();self.pcm(rid);await self.stop(rid,interrupted=True,defer_transcription=True)
            await self.settled();self.assertTrue(get_recording(self.db,rid)['transcription_released']);self.assertEqual(self.native.await_count,1)
            rid=await self.start();self.pcm(rid);await self.stop(rid,interrupted=True,defer_transcription=True)
            second=await self.start(resume_from=rid);await self.settled()
            self.assertFalse(get_recording(self.db,rid)['transcription_released']);self.assertEqual(self.native.await_count,1)
            await self.stop(second);await self.settled();self.assertTrue(get_recording(self.db,rid)['transcription_released'])

    async def test_late_recovery_preserves_released_audio_and_holds_new_segment(self):
        from lecture_study import server
        with patch.object(server,'AUDIO_RELEASE_SECONDS',.03):
            first=await self.start();self.pcm(first);job=await self.stop(first,interrupted=True,defer_transcription=True)
            await self.settled()
            self.assertTrue(get_recording(self.db,first)['transcription_released'])
            original=[dict(r)for r in self.db.execute('SELECT * FROM transcripts WHERE recording_id=?',(first,))]
            self.assertTrue(original)
            second=await self.start(resume_from=first)
            self.assertEqual(get_recording(self.db,second)['capture_id'],first)
            self.assertFalse(get_recording(self.db,second)['transcription_released'])
            self.assertGreaterEqual(get_recording(self.db,second)['offset_ms'],3000)
            self.pcm(second);self.assertEqual(plan_chunks(self.db,second),[])
            await self.stop(second);await self.settled()
            self.assertEqual([dict(r)for r in self.db.execute('SELECT * FROM transcripts WHERE recording_id=?',(first,))],original)
            self.assertEqual(get_recording(self.db,first)['stop_job_id'],job['id'])
            self.assertEqual(self.native.await_count,2)

    async def test_normally_finished_recording_cannot_be_automatically_resumed(self):
        first=await self.start();self.pcm(first);await self.stop(first);await self.settled()
        response=await self.client.post('/api/sessions/'+self.sid+'/audio/start',json={'sample_rate':16000,'resume_from':first},headers=self.headers)
        self.assertEqual(response.status_code,422)

    async def test_startup_releases_held_recording_without_replacing_original_job(self):
        folder=Path(self.temp.name)/'restart';db=open_db(folder);sid=create_session(db,'lecture','재시작',None,None).id
        rid=start_recording(db,sid,16000,'after_stop');append_pcm(db,rid,0,0,16000,b'\1\0'*16000)
        job=stop_recording(db,rid,interrupted=True);db.close()
        app=create_app(AppConfig(folder,Path(self.temp.name)/'runtime2',port=8766))
        async with app.router.lifespan_context(app):
            await self.settled();row=get_recording(app.state.db,rid);self.assertEqual(row['stop_job_id'],job['id']);self.assertTrue(row['transcription_released'])
            self.assertEqual(app.state.db.execute('SELECT status FROM jobs WHERE id=?',(job['id'],)).fetchone()[0],'done')

    async def test_v15_migration_preserves_rows_and_legacy_live_behavior(self):
        from tests.legacy import legacy_fixture
        folder=Path(self.temp.name)/'migration';db=open_db(folder);sid=create_session(db,'lecture','기존 녹음',None,None).id
        db.execute("INSERT INTO recordings(id,session_id,sample_rate,status,started_at) VALUES (?, ?,16000,'stopped','2026-10-14T00:00:00+00:00')",('a'*32,sid));db.commit()
        legacy_fixture(db,15);original=dict(db.execute('SELECT * FROM recordings').fetchone());db.close();db=open_db(folder)
        row=dict(db.execute('SELECT * FROM recordings').fetchone());self.assertEqual({k:row[k]for k in original},original);self.assertEqual(row['transcription_mode'],'realtime');self.assertEqual(row['transcription_released'],1);self.assertEqual(row['capture_id'],'a'*32);self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],17);db.close()

    async def test_cancelled_held_job_is_not_started_by_grace_release(self):
        from lecture_study import server
        with patch.object(server,'AUDIO_RELEASE_SECONDS',.03):
            rid=await self.start();self.pcm(rid);job=await self.stop(rid,interrupted=True,defer_transcription=True)
            response=await self.client.post('/api/jobs/'+job['id']+'/cancel',json={},headers=self.headers);self.assertEqual(response.status_code,200)
            await self.settled();self.assertEqual(self.native.await_count,0);self.assertTrue(get_recording(self.db,rid)['transcription_released'])
            self.assertEqual(self.db.execute('SELECT status FROM jobs WHERE id=?',(job['id'],)).fetchone()[0],'cancelled')

    async def test_missing_raw_on_startup_does_not_block_other_records(self):
        from lecture_study.audio import recording_path
        folder=Path(self.temp.name)/'missing';db=open_db(folder);sid=create_session(db,'lecture','손상 원음',None,None).id
        rid=start_recording(db,sid,16000,'after_stop');recording_path(db,rid).unlink();db.close()
        app=create_app(AppConfig(folder,Path(self.temp.name)/'runtime3',port=8767))
        async with app.router.lifespan_context(app):
            row=get_recording(app.state.db,rid);self.assertEqual(row['status'],'interrupted');self.assertTrue(row['error']);self.assertEqual(app.state.db.execute('SELECT title FROM sessions WHERE id=?',(sid,)).fetchone()[0],'손상 원음')

    async def test_actual_socket_disconnect_defers_then_releases_received_audio(self):
        import struct
        from tests.test_audio_socket import SocketTests
        from lecture_study import server
        self.rid=await self.start()
        init={'recording_id':self.rid,'sample_rate':16000,'channels':1,'format':'pcm_s16le','csrf_token':self.app.state.csrf}
        packet=struct.pack('<QQI',0,0,16000)+b'\1\0'*16000
        with patch.object(server,'AUDIO_RELEASE_SECONDS',.03):
            await SocketTests.socket(self,init,[packet]);self.assertFalse(get_recording(self.db,self.rid)['transcription_released']);self.assertEqual(self.native.await_count,0)
            await self.settled();self.assertEqual(self.native.await_count,1);self.assertEqual(get_recording(self.db,self.rid)['status'],'interrupted')
