import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from lecture_study import audio, transcription as tr
from lecture_study.config import AppConfig
from lecture_study.db import create_session
from lecture_study.server import create_app


class TranscriptScriptTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(AppConfig(Path(self.temp.name), Path(self.temp.name)/'runtime', port=8765))
        self.db = self.app.state.db
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://127.0.0.1:8765')
        origin = {'Origin': 'http://127.0.0.1:8765'}
        login = await self.client.post('/api/bootstrap', json={'token': self.app.state.bootstrap_token}, headers=origin)
        self.headers = {**origin, 'X-Session-Token': login.json()['csrf_token']}
        self.sid = create_session(self.db, 'lecture', '대본 <제목>', None, None).id
        self.rid = audio.start_recording(self.db, self.sid, 8000)
        audio.append_pcm(self.db, self.rid, 0, 0, 8000, bytes([255, 31])*8000)
        audio.append_pcm(self.db, self.rid, 1, 24000, 8000, bytes([255, 31])*8000)
        for i, chunk in enumerate(tr.plan_chunks(self.db, self.rid, stopping=True)):
            tr.accept_transcription(self.db, self.rid, chunk['id'], chunk['revision'], True,
                [{'start_ms': 0, 'end_ms': 1000, 'text': ['첫 문장.', '<script>alert(1)</script> [링크](https://evil.example)'][i]}])
        audio.stop_recording(self.db, self.rid)
        self.rid2 = audio.start_recording(self.db, self.sid, 8000)
        audio.append_pcm(self.db, self.rid2, 0, 0, 8000, bytes([255, 31])*8000)
        chunk = tr.plan_chunks(self.db, self.rid2, stopping=True)[0]
        tr.accept_transcription(self.db, self.rid2, chunk['id'], chunk['revision'], True,
            [{'start_ms': 0, 'end_ms': 1000, 'text': '다른 녹음.'}])
        audio.stop_recording(self.db, self.rid2)
        self.rows = tr.list_transcripts(self.db, self.sid)
        self.route = '/api/sessions/'+self.sid+'/transcripts'

    async def asyncTearDown(self):
        for task in list(self.app.state.tasks):
            task.cancel()
        await asyncio.gather(*self.app.state.tasks, return_exceptions=True)
        await self.client.aclose()
        self.db.close()
        self.app.state.instance_lock.close()
        self.temp.cleanup()

    def edits(self, rows=None):
        return [{'id': row['id'], 'expected_revision': row['revision'], 'text': '수정 '+str(i)}
                for i, row in enumerate(rows or self.rows)]

    async def test_batch_keeps_boundaries_originals_and_old_citations_across_recordings(self):
        saved = await self.client.patch(self.route, json={'segments': self.edits()}, headers=self.headers)
        self.assertEqual(saved.status_code, 200, saved.text)
        for old, current in zip(self.rows, saved.json()['segments']):
            for key in ('id', 'start_ms', 'end_ms', 'original_text', 'chunk_id', 'recording_id'):
                self.assertEqual(current[key], old[key])
            self.assertEqual(current['revision'], 2)
            source = (await self.client.get('/api/sources/'+old['id']+':v1')).json()
            self.assertEqual(source['text_snapshot'], old['text'])
            self.assertEqual(source['status'], 'changed')
        gap = (await self.client.get('/api/sources/'+self.rows[1]['id']+':v2')).json()
        second = (await self.client.get('/api/sources/'+self.rows[2]['id']+':v2')).json()
        self.assertEqual((gap['seek_seconds'], gap['end_seconds']), (1, 2))
        self.assertEqual((second['seek_seconds'], second['end_seconds']), (0, 1))
        self.assertNotEqual(gap['open_url'], second['open_url'])

    async def test_stale_second_segment_rejects_entire_batch(self):
        tr.edit_segment(self.db, self.rows[1]['id'], '다른 편집')
        before = tr.list_transcripts(self.db, self.sid)
        saved = await self.client.patch(self.route, json={'segments': self.edits()}, headers=self.headers)
        self.assertEqual(saved.status_code, 409, saved.text)
        self.assertEqual(tr.list_transcripts(self.db, self.sid), before)
        self.assertIsNone(self.db.execute('SELECT 1 FROM sources WHERE id=?', (self.rows[0]['id']+':v2',)).fetchone())

    async def test_duplicates_scope_provisional_superseded_and_bad_bounds_are_atomic(self):
        edits = self.edits()
        cases = [edits+[edits[0]]]
        for body in cases:
            result = await self.client.patch(self.route, json={'segments': body}, headers=self.headers)
            self.assertEqual(result.status_code, 422, result.text)
        other = create_session(self.db, 'lecture', '다른 회차', None, None).id
        result = await self.client.patch('/api/sessions/'+other+'/transcripts', json={'segments': edits}, headers=self.headers)
        self.assertEqual(result.status_code, 422, result.text)
        for column, value in [('final', 0), ('superseded_by', self.rows[0]['id']), ('start_ms', -1)]:
            old = self.rows[1][column]
            with self.db:
                self.db.execute('UPDATE transcripts SET '+column+'=? WHERE id=?', (value, self.rows[1]['id']))
            result = await self.client.patch(self.route, json={'segments': edits}, headers=self.headers)
            self.assertEqual(result.status_code, 422, (column, result.text))
            with self.db:
                self.db.execute('UPDATE transcripts SET '+column+'=? WHERE id=?', (old, self.rows[1]['id']))
            self.assertEqual(tr.list_transcripts(self.db, self.sid), self.rows)

    async def test_empty_oversized_and_noninteger_revisions_are_rejected(self):
        good = self.edits([self.rows[0]])[0]
        for values in ([], [good]*201, [{**good, 'text': ' '}], [{**good, 'text': 'a'*10001}],
                       [{**good, 'expected_revision': True}], [{**good, 'expected_revision': 1.0}],
                       [{**good, 'expected_revision': 0}], [{**good, 'text': '수정', 'start_ms': 0}]):
            result = await self.client.patch(self.route, json={'segments': values}, headers=self.headers)
            self.assertEqual(result.status_code, 422, result.text)
        self.assertEqual(tr.list_transcripts(self.db, self.sid), self.rows)

    async def test_index_failure_rolls_back_all_text_and_sources(self):
        calls = 0
        real = tr.index_source
        def index(db, ref, text):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ValueError('색인 실패')
            return real(db, ref, text)
        with patch.object(tr, 'index_source', side_effect=index):
            result = await self.client.patch(self.route, json={'segments': self.edits()}, headers=self.headers)
        self.assertEqual(result.status_code, 422, result.text)
        self.assertEqual(tr.list_transcripts(self.db, self.sid), self.rows)
        self.assertEqual(self.db.execute('SELECT count(*) FROM sources').fetchone()[0], 3)

    async def test_single_edit_revision_guard_is_optional_but_enforced_when_supplied(self):
        route = '/api/transcripts/'+self.rows[0]['id']
        saved = await self.client.patch(route, json={'text': '기존 호출'}, headers=self.headers)
        self.assertEqual(saved.status_code, 200, saved.text)
        stale = await self.client.patch(route, json={'text': '낡은 호출', 'expected_revision': 1}, headers=self.headers)
        self.assertEqual(stale.status_code, 409, stale.text)
        guarded = await self.client.patch(route, json={'text': '확인한 호출', 'expected_revision': 2}, headers=self.headers)
        self.assertEqual(guarded.json()['revision'], 3)

    async def test_exports_include_active_confirmed_text_and_safe_resolved_audio_links(self):
        txt = await self.client.get(self.route+'/export?format=txt')
        self.assertEqual(txt.status_code, 200, txt.text)
        self.assertIn('attachment;', txt.headers['content-disposition'])
        self.assertIn('text/plain', txt.headers['content-type'])
        self.assertIn('첫 문장.', txt.text)
        md = await self.client.get(self.route+'/export?format=md')
        self.assertEqual(md.status_code, 200, md.text)
        self.assertIn('text/markdown', md.headers['content-type'])
        self.assertIn(self.rows[1]['id']+':v1', md.text)
        self.assertIn('http://127.0.0.1:8765/api/recordings/'+self.rid+'/audio#t=1,2', md.text)
        self.assertIn('http://127.0.0.1:8765/api/recordings/'+self.rid2+'/audio#t=0,1', md.text)
        self.assertIn('앱 실행', md.text)
        self.assertIn('인증', md.text)
        self.assertNotIn('<script>', md.text)
        self.assertNotIn('[링크](https://evil.example)', md.text)
        with self.db:
            self.db.execute('UPDATE transcripts SET final=0 WHERE id=?', (self.rows[0]['id'],))
            self.db.execute('UPDATE transcripts SET superseded_by=? WHERE id=?', (self.rows[0]['id'], self.rows[1]['id']))
        txt = await self.client.get(self.route+'/export?format=txt')
        self.assertNotIn('첫 문장.', txt.text)
        self.assertNotIn('alert(1)', txt.text)
        self.assertIn('다른 녹음.', txt.text)

    async def test_missing_audio_and_invalid_export_format_are_honest(self):
        with self.db:
            self.db.execute("UPDATE recordings SET status='audio_deleted' WHERE session_id=?", (self.sid,))
        md = await self.client.get(self.route+'/export?format=md')
        self.assertEqual(md.status_code, 200, md.text)
        self.assertIn('원음 없음', md.text)
        self.assertNotIn('/audio#t=', md.text)
        self.assertEqual((await self.client.get(self.route+'/export?format=html')).status_code, 422)
