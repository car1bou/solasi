import asyncio
import json
import os
import sqlite3
import struct
import sys
import tempfile
import unittest
from pathlib import Path

from lecture_study.config import acquire_data_lock
from lecture_study.native_worker import MAX_HEADER, ProtocolError, read_frame


async def frame(reader):
    size = struct.unpack('>I', await reader.readexactly(4))[0]
    header = json.loads(await reader.readexactly(size))
    return header, await reader.readexactly(header['body_length'])


def encoded(ident, op, body=b'', **fields):
    header = json.dumps(dict(version=1, id=ident, op=op, body_length=len(body), **fields)).encode()
    return struct.pack('>I', len(header)) + header + body


class FramingTests(unittest.IsolatedAsyncioTestCase):
    async def test_fragmented_read_and_clean_eof(self):
        reader = asyncio.StreamReader()
        data = encoded('a', 'http', b'{}', method='POST', path='/api/courses')
        async def feed():
            for byte in data:
                reader.feed_data(bytes([byte]))
                await asyncio.sleep(0)
            reader.feed_eof()
        task = asyncio.create_task(feed())
        header, body = await read_frame(reader)
        self.assertEqual(header['id'], 'a')
        self.assertEqual(body, b'{}')
        self.assertIsNone(await read_frame(reader))
        await task

    async def test_oversize_header_and_truncated_body_rejected(self):
        for data in (struct.pack('>I', MAX_HEADER + 1), encoded('x', 'http', b'abc')[:-1]):
            reader = asyncio.StreamReader()
            reader.feed_data(data)
            reader.feed_eof()
            with self.assertRaises(ProtocolError):
                await read_frame(reader)

    async def test_invalid_header_fields_rejected_before_body(self):
        for changes in ({'version': True}, {'id': '../unsafe'}, {'op': 'exec'}, {'op': []}, {'body_length': -1}, {'body_length': True}, {'body_length': 10*1024*1024+1}):
            header = dict(version=1, id='x', op='http', body_length=0) | changes
            data = json.dumps(header).encode()
            reader = asyncio.StreamReader()
            reader.feed_data(struct.pack('>I', len(data)) + data)
            reader.feed_eof()
            with self.assertRaises(ProtocolError):
                await read_frame(reader)


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_draft_transfer_is_durable_through_pipe_restart(self):
        import base64
        status, body, _ = await self.http('GET', '/api/native/state')
        self.assertEqual(status,200)
        vault = json.loads(body)['vault_id']
        row = dict(key='["c","a","hash",1]',text='저장 중 한글 🙂',ink=[],revision=0,token='token',dirty=True)
        raw = json.dumps(row,ensure_ascii=False).encode()
        status, body, _ = await self.http('POST','/api/native/drafts/uploads',dict(size=len(raw),kind='write',journal_key=row['key']+'::writer'))
        ident = json.loads(body)['id']
        for offset in range(0,len(raw),11):
            status, _, _ = await self.http('PUT','/api/native/drafts/uploads/'+ident,dict(offset=offset,data=base64.b64encode(raw[offset:offset+11]).decode()))
            self.assertEqual(status,200)
        status, _, _ = await self.http('POST','/api/native/drafts/uploads/'+ident+'/commit')
        self.assertEqual(status,200)
        self.process.stdin.close()
        await asyncio.wait_for(self.process.wait(),8)
        await self.start()
        _, body, _ = await self.http('GET','/api/native/state')
        self.assertEqual(json.loads(body)['vault_id'],vault)
        from urllib.parse import urlencode
        status, body, _ = await self.http('GET','/api/native/drafts/read?'+urlencode({'key':row['key']}))
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body),[row])

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.counter = 0
        self.events = []
        self.process = None
        self.processes = []
        await self.start()

    async def start(self, fixture=False):
        command = [sys.executable, '-m', 'lecture_study.native_worker']
        if fixture:
            script = '''
import asyncio
from starlette.responses import StreamingResponse
from lecture_study import native_worker as worker
original = worker.create_app
def create(config):
    app = original(config)
    # Test-only routes are registered after create_app's optional frontend mount.
    app.router.routes = [route for route in app.router.routes if getattr(route, 'name', '') != 'frontend']
    @app.get('/api/test/stream')
    async def stream():
        async def parts():
            try:
                yield b'a'*300000
                await asyncio.sleep(60)
            finally:
                (config.data_dir/'stream-closed').write_text('closed')
        return StreamingResponse(parts())
    @app.get('/api/test/block')
    async def block():
        import time
        (config.data_dir/'thread-started').write_text('started')
        await asyncio.to_thread(time.sleep, 60)
        return {}
    @app.get('/api/test/conflict')
    async def conflict():
        from lecture_study.transcription import TranscriptConflict
        raise TranscriptConflict('changed')
    return app
worker.create_app=create
worker.ACK_SECONDS=.2
worker.SHUTDOWN_SECONDS=.2
worker.MAX_REQUESTS=2
worker.main()
'''
            command = [sys.executable, '-c', script]
        env = dict(os.environ)
        env.pop('SOLASI_OWNER_PID', None)
        self.process = await asyncio.create_subprocess_exec(*command, '--data-dir', str(self.directory), '--runtime-dir', str(self.directory/'runtime'), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)
        self.processes.append(self.process)
        header, body = await asyncio.wait_for(frame(self.process.stdout), 10)
        self.assertEqual(header['event'], 'ready')
        if os.name=='posix':
            self.assertEqual(header['process_group'],self.process.pid)
            self.assertEqual(os.getpgid(self.process.pid),self.process.pid)
        self.assertEqual(body, b'')

    async def asyncTearDown(self):
        for process in self.processes:
            if process.returncode is None:
                process.stdin.close()
            try:
                await asyncio.wait_for(process.communicate(), 8)
            except TimeoutError:
                process.kill()
                await process.communicate()

    async def send(self, op, body=b'', **fields):
        self.counter += 1
        ident = str(self.counter)
        self.process.stdin.write(encoded(ident, op, body, **fields))
        await self.process.stdin.drain()
        return ident

    async def receive(self, ident, ack=True):
        bodies = []
        status = None
        while True:
            header, body = await asyncio.wait_for(frame(self.process.stdout), 5)
            if header['id'] != ident:
                self.events.append((header, body))
                continue
            if header['event'] == 'body':
                bodies.append(body)
                if ack:
                    await self.send('ack', target=ident, sequence=header['sequence'])
            elif header['event'] == 'response_start':
                status = header['status']
            elif header['event'] in ('complete', 'error'):
                return status, b''.join(bodies), header

    async def http(self, method, path, data=None, headers=None):
        body = json.dumps(data).encode() if data is not None else b''
        ident = await self.send('http', body, method=method, path=path, headers=headers or {})
        return await self.receive(ident)

    async def test_crud_validation_auth_and_no_managed_server(self):
        status, body, _ = await self.http('POST', '/api/courses', {'title': '운영체제'})
        self.assertEqual(status, 201)
        course = json.loads(body)
        status, body, _ = await self.http('GET', '/api/courses')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)[0]['id'], course['id'])
        status, _, _ = await self.http('POST', '/api/courses', {'title': ' '})
        self.assertEqual(status, 422)
        for path in ('/api/bootstrap', '/api/client', 'http://elsewhere/api/courses', '/api/../app.sqlite3'):
            status, _, response = await self.http('GET', path)
            self.assertIsNone(status)
            self.assertEqual(response['event'], 'error')
        status, _, response = await self.http('GET', '/api/courses', headers={'cookie': 'stolen'})
        self.assertIsNone(status)
        self.assertEqual(response['event'], 'error')
        status, _, _ = await self.http('POST', '/api/local/connect', {'mode': 'managed'})
        self.assertEqual(status, 200)
        # Existing managed settings must not start any process when worker restarts.
        self.process.stdin.close()
        await asyncio.wait_for(self.process.wait(), 8)
        db = sqlite3.connect(self.directory/'app.sqlite3')
        db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', ('local_connection', '{"mode":"managed"}'))
        db.commit()
        db.close()
        await self.start()
        status, body, _ = await self.http('GET', '/api/local/status')
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(body)['connected'])

    async def test_concurrent_ids_conflict_and_stream_cancel(self):
        self.process.stdin.close()
        await asyncio.wait_for(self.process.wait(), 8)
        await self.start(fixture=True)
        first = await self.send('http', method='GET', path='/api/test/stream')
        header, _ = await asyncio.wait_for(frame(self.process.stdout), 5)
        self.assertEqual(header['event'], 'response_start')
        header, body = await asyncio.wait_for(frame(self.process.stdout), 5)
        self.assertEqual(header['id'], first)
        self.assertEqual(header['event'], 'body')
        self.assertLessEqual(len(body), 256*1024)
        # Stream is waiting for ACK; another request must still finish.
        status, _, _ = await self.http('GET', '/api/test/conflict')
        self.assertEqual(status, 409)
        cancel = await self.send('cancel', target=first)
        _, _, reply = await self.receive(cancel)
        self.assertEqual(reply['event'], 'complete')
        for _ in range(50):
            if (self.directory/'stream-closed').exists():
                break
            await asyncio.sleep(.02)
        self.assertEqual((self.directory/'stream-closed').read_text(), 'closed')
        status, _, _ = await self.http('GET', '/api/health')
        self.assertEqual(status, 200)

    async def test_durable_audio_ack_eof_cleanup_and_restart(self):
        status, body, _ = await self.http('POST', '/api/sessions', {'kind': 'meeting', 'title': '녹음'})
        self.assertEqual(status, 201)
        sid = json.loads(body)['id']
        status, body, _ = await self.http('POST', f'/api/sessions/{sid}/audio/start', {'sample_rate': 48000})
        self.assertEqual(status, 201)
        rid = json.loads(body)['recording_id']
        stream = await self.send('audio_open', session_id=sid, recording_id=rid, sample_rate=48000)
        _, _, ready = await self.receive(stream)
        self.assertEqual(ready['payload']['type'], 'ready')
        packet = struct.pack('<QQI', 0, 0, 12000) + b'\1\0'*12000
        request = await self.send('audio_packet', packet, stream_id=stream)
        _, _, ack = await self.receive(request)
        self.assertEqual(ack['payload']['type'], 'ack')
        self.assertEqual(ack['payload']['stored_frames'], 12000)
        duplicate = await self.send('audio_packet', packet, stream_id=stream)
        _, _, repeated = await self.receive(duplicate)
        self.assertEqual(repeated['payload']['stored_frames'], 12000)
        raw = self.directory/'audio'/rid/'raw.wav'
        self.assertEqual(raw.read_bytes()[44:], packet[20:])
        saved_wav = raw.read_bytes()
        # A second connection sees data committed before the ACK.
        db = sqlite3.connect(self.directory/'app.sqlite3')
        self.assertEqual(db.execute('SELECT stored_frames FROM recordings WHERE id=?', (rid,)).fetchone()[0], 12000)
        db.close()
        self.process.stdin.close()
        await asyncio.wait_for(self.process.wait(), 8)
        self.assertEqual(self.process.returncode, 0)
        lock = acquire_data_lock(self.directory)
        lock.close()
        db = sqlite3.connect(self.directory/'app.sqlite3')
        row = db.execute('SELECT status,stored_frames,stop_job_id FROM recordings WHERE id=?', (rid,)).fetchone()
        self.assertEqual(row[:2], ('interrupted', 12000))
        self.assertIsNotNone(row[2])
        db.close()
        await self.start()
        status, body, _ = await self.http('GET', f'/api/sessions/{sid}/recordings')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)[0]['stored_frames'], 12000)
        self.assertEqual(raw.read_bytes(), saved_wav)

    async def test_native_picker_selection_is_scoped_and_cancel_is_empty(self):
        _, body, _ = await self.http('POST', '/api/courses', {'title': '자료'})
        cid = json.loads(body)['id']
        path = f'/api/courses/{cid}/files/select'
        _, _, denied = await self.http('POST', path)
        self.assertEqual(denied['event'], 'error')
        ident = await self.send('http', method='POST', path=path, native_selected_files=[])
        status, body, _ = await self.receive(ident)
        self.assertEqual(status, 201)
        self.assertEqual(json.loads(body), [])
        originals = tempfile.TemporaryDirectory()
        self.addCleanup(originals.cleanup)
        source = Path(originals.name)/'lesson.txt'
        source.write_text('공부한 내용을 그대로 보존합니다.', encoding='utf-8')
        ident = await self.send('http', method='POST', path=path, native_selected_files=[str(source)])
        status, body, _ = await self.receive(ident)
        self.assertEqual(status, 201)
        asset = json.loads(body)[0]['asset']
        self.assertEqual(asset['filename'], 'lesson.txt')
        resource = f"/api/assets/{asset['id']}/original"
        status, raw, _ = await self.http('GET', resource, headers={'range':'bytes=0-5'})
        self.assertEqual(status, 206)
        self.assertEqual(raw, source.read_bytes()[:6])
        status, raw, _ = await self.http('HEAD',resource)
        self.assertEqual(status,200)
        self.assertEqual(raw,b'')
        self.assertEqual(source.read_text(), '공부한 내용을 그대로 보존합니다.')
        for endpoint, selected in (('/api/health', [str(source)]), (path, ['relative.txt']), (path, ['/tmp/a']*65)):
            ident = await self.send('http', method='POST', path=endpoint, native_selected_files=selected)
            status, _, reply = await self.receive(ident)
            self.assertIsNone(status)
            self.assertEqual(reply['event'], 'error')

    async def test_shutdown_deadline_covers_uncancellable_thread(self):
        self.process.stdin.close()
        await asyncio.wait_for(self.process.wait(), 8)
        await self.start(fixture=True)
        await self.send('http', method='GET', path='/api/test/block')
        for _ in range(100):
            if (self.directory/'thread-started').exists():
                break
            await asyncio.sleep(.01)
        self.assertTrue((self.directory/'thread-started').exists())
        self.process.stdin.close()
        await asyncio.wait_for(self.process.wait(), 4)
        self.assertEqual(self.process.returncode, 2)
        lock = acquire_data_lock(self.directory)
        lock.close()

    async def test_ack_timeout_recovers_capacity(self):
        self.process.stdin.close()
        await asyncio.wait_for(self.process.wait(), 8)
        await self.start(fixture=True)
        request = await self.send('http', method='GET', path='/api/test/stream')
        await asyncio.wait_for(frame(self.process.stdout), 5)
        await asyncio.wait_for(frame(self.process.stdout), 5)
        _, _, reply = await self.receive(request)
        self.assertEqual(reply['event'], 'error')
        self.assertEqual(reply['code'], 'timeout')
        self.assertTrue((self.directory/'stream-closed').exists())
        status, _, _ = await self.http('GET', '/api/health')
        self.assertEqual(status, 200)

    async def test_duplicate_active_id_ends_session_without_mutation(self):
        self.process.stdin.close()
        await asyncio.wait_for(self.process.wait(), 8)
        await self.start(fixture=True)
        request = await self.send('http', method='GET', path='/api/test/stream')
        await asyncio.wait_for(frame(self.process.stdout), 5)
        await asyncio.wait_for(frame(self.process.stdout), 5)
        self.process.stdin.write(encoded(request, 'http', b'{"title":"not created"}', method='POST', path='/api/courses'))
        await self.process.stdin.drain()
        await asyncio.wait_for(self.process.wait(), 8)
        self.assertEqual(self.process.returncode, 2)
        db = sqlite3.connect(self.directory/'app.sqlite3')
        self.assertEqual(db.execute('SELECT count(*) FROM courses').fetchone()[0], 0)
        db.close()
        lock = acquire_data_lock(self.directory)
        lock.close()

    async def test_pending_requests_are_bounded(self):
        self.process.stdin.close()
        await asyncio.wait_for(self.process.wait(), 8)
        await self.start(fixture=True)
        await self.send('http', method='GET', path='/api/test/stream')
        await self.send('http', method='GET', path='/api/test/stream')
        request = await self.send('http', method='GET', path='/api/health')
        _, _, response = await self.receive(request)
        self.assertEqual(response['event'], 'error')
        self.assertEqual(response['code'], 'busy')

    async def test_sigterm_releases_lock(self):
        self.process.terminate()
        await asyncio.wait_for(self.process.wait(), 8)
        self.assertEqual(self.process.returncode, 0)
        lock = acquire_data_lock(self.directory)
        lock.close()

    async def test_eof_cancels_pending_resource_ack(self):
        self.process.stdin.close()
        await asyncio.wait_for(self.process.wait(), 8)
        await self.start(fixture=True)
        await self.send('http', method='GET', path='/api/test/stream')
        await asyncio.wait_for(frame(self.process.stdout), 5)
        await asyncio.wait_for(frame(self.process.stdout), 5)
        self.process.stdin.close()
        await asyncio.wait_for(self.process.wait(), 8)
        self.assertEqual(self.process.returncode, 0)
        lock = acquire_data_lock(self.directory)
        lock.close()
        self.assertTrue((self.directory/'stream-closed').exists())
