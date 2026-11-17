import asyncio
import base64
from concurrent.futures import CancelledError, ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid


class MobileBridgeTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.find_spec('lecture_study.mobile_bridge')
        self.assertIsNotNone(spec, 'The embedded mobile bridge has not been implemented')
        from lecture_study import mobile_bridge
        self.module = mobile_bridge
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bridge = mobile_bridge.start(self.root/'vault', self.root/'runtime')
        self.addCleanup(lambda: self.bridge.close())

    def message(self, path, method='GET', value=None, **fields):
        return json.dumps(dict(op='http', id=uuid.uuid4().hex, path=path, method=method,
                              body=json.dumps(value) if value is not None else '', **fields))

    def request(self, path, method='GET', value=None, **fields):
        return json.loads(self.bridge.command(self.message(path, method, value, **fields)))

    def course(self):
        reply = self.request('/api/courses', 'POST', {'title': '모바일 수업'})
        self.assertEqual(reply['status'], 201)
        return json.loads(reply['text'])

    def test_real_sqlite_create_close_reopen_without_listener_or_subprocess(self):
        self.bridge.close()
        with patch.object(socket.socket, 'bind', side_effect=AssertionError('listener forbidden')), \
             patch.object(subprocess, 'Popen', side_effect=AssertionError('subprocess forbidden')), \
             patch.object(asyncio, 'create_subprocess_exec', side_effect=AssertionError('subprocess forbidden')):
            self.bridge = self.module.start(self.root/'vault', self.root/'runtime')
            row = self.course()
            self.bridge.close()
            self.bridge = self.module.start(self.root/'vault', self.root/'runtime')
            rows = json.loads(self.request('/api/courses')['text'])
            self.assertEqual([(r['id'], r['title']) for r in rows], [(row['id'], '모바일 수업')])
            self.assertNotEqual(self.bridge.engine.thread.ident, threading.get_ident())
            self.bridge.close()
        with self.assertRaises(ValueError): self.request('/api/courses')

    def test_boundary_denies_origin_traversal_credentials_headers_and_native_operations(self):
        for path in ('https://evil/api/courses', '//evil/api/courses', '/api/%2e%2e/private',
                     '/api/%252e%252e/private', '/api/x%5cy', '/api/bootstrap', '/api/client', '/api/courses#x'):
            with self.subTest(path=path), self.assertRaises(ValueError): self.request(path)
        for headers in ({'origin': 'https://evil'}, {'cookie':'secret'}, {'range':'bytes=0-1\r\nx:y'},
                        {'x-session-token':'secret'}, {'accept':'\x00'}):
            with self.subTest(headers=headers), self.assertRaises(ValueError): self.request('/api/courses', headers=headers)
        for message in ({'op':'audio_start'}, {'op':'resource'}, {'op':'select'},
                        {'op':'ui_ready','native_selected_files':[]}, {'op':'ui_ready','path':'/secret'}):
            with self.subTest(message=message), self.assertRaises(ValueError):self.bridge.command(json.dumps(message))
        with self.assertRaises(ValueError): self.request('/api/courses', native_selected_files=['/secret'])
        for raw in ('[]', '{', '{"op":"ui_ready","op":"http"}', 'NaN'):
            with self.subTest(raw=raw), self.assertRaises(ValueError): self.bridge.command(raw)
        self.assertEqual(json.loads(self.bridge.command('{"op":"ui_ready"}'))['ready'], True)

    def test_picker_only_native_entrypoint_cancel_and_pending_conversion(self):
        row = self.course()
        raw = self.message('/api/courses/'+row['id']+'/files/select', 'POST')
        with self.assertRaises(ValueError):self.bridge.command(raw)
        self.assertEqual(json.loads(self.bridge.select(raw, []))['status'], 201)
        with self.assertRaises(ValueError):self.bridge.select(self.message('/api/courses'), [])
        for paths in (['relative'], ['/x\x00y'], ['/x']*65):
            with self.subTest(paths=paths), self.assertRaises(ValueError): self.bridge.select(raw, paths)
        original=self.root/'한글 파일.txt';original.write_text('safe original',encoding='utf-8')
        reply=json.loads(self.bridge.select(raw,[str(original)]))
        self.assertEqual(reply['status'],501)
        self.assertEqual(original.read_text(), 'safe original')
        self.assertEqual(json.loads(self.request('/api/courses/'+row['id']+'/materials')['text'])['assets'],[])

    def test_desktop_engines_and_external_credentials_are_explicitly_unavailable(self):
        with patch.object(subprocess, 'Popen', side_effect=AssertionError('subprocess forbidden')), \
             patch.object(asyncio,'create_subprocess_exec',side_effect=AssertionError('subprocess forbidden')):
            reply=self.request('/api/local/status')
            self.assertFalse(json.loads(reply['text'])['connected'])
            for path in ('/api/local/connect','/api/ai/jobs','/api/runtime/prepare','/api/credentials/openai'):
                with self.subTest(path=path):self.assertEqual(self.request(path,'POST',{})['status'],501)
            self.assertEqual(self.request('/api/assets/'+'a'*32+'/document')['status'],501)
            status=json.loads(self.request('/api/runtime/status')['text'])
            self.assertTrue(status[0]['ready'])
            self.assertFalse(any(row['ready'] for row in status[1:]))

    def test_resources_allowlist_ranges_release_limit_and_close_cleanup(self):
        from lecture_study.audio import start_recording, append_pcm, stop_recording
        row=self.course()
        session=json.loads(self.request('/api/sessions','POST',{'kind':'lecture','title':'녹음','course_id':row['id']})['text'])
        async def record():
            db=self.bridge.engine.app.state.db
            rid=start_recording(db,session['id'],16000,'after_stop')
            append_pcm(db,rid,0,0,100,b'\x01\x00'*100)
            stop_recording(db,rid)
            return rid
        rid=self.bridge.engine.submit(record()).result(10)
        url='https://solasi.invalid/api/recordings/'+rid+'/audio'
        def resource(**fields):return json.loads(self.bridge.resource(json.dumps(dict(url=url,method='GET',**fields))))
        first=resource(headers={'range':'bytes=0-3'})
        self.assertEqual(first['status'],206)
        self.assertEqual(Path(first['path']).read_bytes(),b'RIFF')
        self.assertEqual(dict(first['headers'])['content-range'].split('/')[0],'bytes 0-3')
        token=first['token'];self.bridge.release_resource(token)
        self.assertFalse(Path(first['path']).exists())
        self.bridge.release_resource(token)
        with patch.object(self.module,'MAX_RESOURCE_BYTES',4),self.assertRaises(ValueError):resource()
        self.assertEqual(list(self.bridge.response_dir.iterdir()),[])
        for invalid in ('bytes=0-1,3-4','bytes=-0','bytes=NaN-','bytes=2-1'):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):resource(headers={'range':invalid})
        for invalid in ('https://evil/api/recordings/'+rid+'/audio','https://solasi.invalid/api/courses',
                        'https://solasi.invalid/api/%252e%252e/private','file:///etc/passwd'):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):self.bridge.resource(json.dumps({'url':invalid}))
        tokens=[resource() for _ in range(self.module.MAX_RESOURCES)]
        with self.assertRaises(ValueError):resource()
        self.bridge.close()
        self.assertTrue(all(not Path(item['path']).exists() for item in tokens))

    def test_native_pcm_requires_saved_ack_before_next_packet(self):
        from lecture_study import audio
        course=self.course()
        session=json.loads(self.request('/api/sessions','POST',{'kind':'lecture','title':'PCM','course_id':course['id']})['text'])
        stream=json.loads(self.bridge.audio_open(json.dumps({'session_id':session['id'],'sample_rate':16000,'transcription_mode':'after_stop'})))['stream_id']
        packet=json.dumps({'stream_id':stream,'seq':0,'first_frame':0,'frame_count':10,'pcm_base64':base64.b64encode(b'\x03\x00'*10).decode()})
        entered=threading.Event();release=threading.Event();write=audio.write_pcm
        def delayed_write(*args):
            entered.set();release.wait(3);return write(*args)
        with patch.object(audio,'write_pcm',side_effect=delayed_write),ThreadPoolExecutor(1) as pool:
            first=pool.submit(self.bridge.audio_packet,packet)
            self.assertTrue(entered.wait(5))
            timer=threading.Timer(.2,release.set);timer.start()
            try:
                with self.assertRaises(ValueError):self.bridge.audio_packet(packet)
            finally:release.set();timer.join()
            self.assertEqual(json.loads(first.result(5))['stored_frames'],10)

    def test_native_pcm_ack_is_durable_validated_and_close_preserves_interruption(self):
        self.enterContext(patch.object(subprocess,'Popen',side_effect=AssertionError('subprocess forbidden')))
        self.enterContext(patch.object(asyncio,'create_subprocess_exec',side_effect=AssertionError('subprocess forbidden')))
        course=self.course()
        session=json.loads(self.request('/api/sessions','POST',{'kind':'lecture','title':'PCM','course_id':course['id']})['text'])
        opened=json.loads(self.bridge.audio_open(json.dumps({'session_id':session['id'],'sample_rate':16000,'transcription_mode':'after_stop'})))
        self.assertFalse(opened['transcription_available'])
        stream=opened['stream_id']
        with self.assertRaises(ValueError):self.bridge.audio_open(json.dumps({'session_id':session['id'],'sample_rate':16000,'transcription_mode':'after_stop'}))
        packet={'stream_id':stream,'seq':0,'first_frame':0,'frame_count':100,'pcm_base64':base64.b64encode(b'\x03\x00'*100).decode()}
        ack=json.loads(self.bridge.audio_packet(json.dumps(packet)))
        self.assertEqual(ack,{'type':'ack','seq':0,'frame_count':100,'stored_frames':100,'source_frames':100})
        self.assertEqual(json.loads(self.bridge.audio_packet(json.dumps(packet))),ack)
        for changed in ({'pcm_base64':'bad$'}, {'frame_count':101}, {'pcm_base64':base64.b64encode(b'\x04\x00'*100).decode()}, {'seq':True}, {'pcm_base64':base64.b64encode(b'x'*(256*1024+2)).decode()}):
            with self.subTest(changed=list(changed)),self.assertRaises(ValueError):self.bridge.audio_packet(json.dumps(packet|changed))
        from lecture_study.audio import recording_path
        async def pcm_path():return recording_path(self.bridge.engine.app.state.db,opened['recording_id'])
        path=self.bridge.engine.submit(pcm_path()).result(5)
        self.assertEqual(path.read_bytes()[44:],b'\x03\x00'*100)
        closed=json.loads(self.bridge.audio_close(json.dumps({'stream_id':stream,'end_frame':120,'interrupted':True,'reason':'테스트 인터럽트'})))
        self.assertEqual(closed['status'],'interrupted')
        self.assertEqual(closed['source_frames'],120)
        self.assertFalse(closed['transcription_available'])
        next_open=json.loads(self.bridge.audio_open(json.dumps({'session_id':session['id'],'sample_rate':16000,'transcription_mode':'realtime'})))
        self.bridge.close()
        self.bridge=self.module.start(self.root/'vault',self.root/'runtime')
        rows=json.loads(self.request('/api/sessions/'+session['id']+'/recordings')['text'])
        self.assertTrue(all(r['status']=='interrupted' for r in rows))
        self.assertEqual({r['id'] for r in rows},{opened['recording_id'],next_open['recording_id']})

    def test_cancellation_duplicate_request_and_response_cleanup(self):
        from starlette.responses import StreamingResponse
        entered=threading.Event();finished=threading.Event()
        async def install():
            @self.bridge.engine.app.get('/api/test/stream')
            async def stream():
                async def chunks():
                    try:
                        entered.set();yield b'first';await asyncio.sleep(60)
                    finally:finished.set()
                return StreamingResponse(chunks())
            routes=self.bridge.engine.app.router.routes
            routes.insert(0,routes.pop())
        self.bridge.engine.submit(install()).result(5)
        raw=self.message('/api/test/stream');ident=json.loads(raw)['id']
        with ThreadPoolExecutor(1) as pool:
            pending=pool.submit(self.bridge.command,raw)
            self.assertTrue(entered.wait(5))
            with self.assertRaises(ValueError):self.bridge.command(raw)
            self.assertEqual(json.loads(self.bridge.command(json.dumps({'op':'cancel','target':ident}))),{'cancelled':True})
            with self.assertRaises(CancelledError):pending.result(5)
        self.assertTrue(finished.wait(5))
        self.assertEqual(list(self.bridge.response_dir.iterdir()),[])


if __name__ == '__main__':unittest.main()
