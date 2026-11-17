import asyncio
import errno
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from lecture_study import windows_bridge as bridge
from lecture_study.config import AppConfig
from lecture_study import windows_app


class WindowsBoundaryTests(unittest.TestCase):
    def test_resource_paths_reject_external_origins_encoded_traversal_and_api_mutations(self):
        self.assertEqual(bridge.resource_path('https://solasi.invalid/api/assets/'+'a'*32+'/pages/1?document_sha256=x'), '/api/assets/'+'a'*32+'/pages/1?document_sha256=x')
        for url in ('https://solasi.invalid.evil/x', 'https://user@solasi.invalid/', 'https://solasi.invalid:443/', 'https://solasi.invalid/%2e%2e/secret', 'https://solasi.invalid/a%5cb', 'https://solasi.invalid/api/courses', 'file:///etc/passwd'):
            with self.subTest(url=url), self.assertRaises(ValueError):bridge.resource_path(url)

    def test_static_path_and_ranges_preserve_bytes_and_reject_symlink_escape(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root=Path(directory);(root/'index.html').write_bytes(b'abcdef')
            with bridge.static_response(root,'/','GET',{'range':'bytes=2-4'}) as response:
                self.assertEqual(response.status,206);self.assertEqual(response.body.read(),b'cde')
                self.assertEqual(dict(response.headers)['Content-Range'],'bytes 2-4/6')
            with bridge.static_response(root,'/','HEAD',{}) as response:self.assertEqual(response.body.read(),b'')
            with self.assertRaises(ValueError):bridge.byte_range('bytes=20-',6)
            with self.subTest('symlink escape'):
                (Path(outside)/'secret').write_text('secret',encoding='utf-8')
                try:(root/'leak').symlink_to(Path(outside)/'secret')
                except OSError as error:
                    if getattr(error,'winerror',None)==1314:self.skipTest('Windows symlink creation requires privilege (WinError 1314); static path and range checks still ran')
                    raise
                with self.assertRaises(ValueError):bridge.static_response(root,'/leak','GET',{})

    def test_exclusive_export_never_overwrites_and_preserves_partial_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'한글 자료.md';target.write_text('original',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'보존'):bridge.export_text(target,'new')
            self.assertEqual(target.read_text(encoding='utf-8'),'original')
            saved=Path(directory)/'new.md';bridge.export_text(saved,'새 내용');self.assertEqual(saved.read_text(encoding='utf-8'),'새 내용')

    def test_windows_export_without_hardlinks_preserves_existing_destination(self):
        import os
        rename=os.rename
        def windows_rename(source,destination):
            if Path(destination).exists():raise FileExistsError(destination)
            rename(source,destination)
        with tempfile.TemporaryDirectory() as directory,patch('sys.platform','win32'),patch.object(bridge.os,'link',side_effect=OSError(errno.ENOTSUP,'no hardlinks')),patch.object(bridge.os,'rename',side_effect=windows_rename):
            target=Path(directory)/'USB export.md';bridge.export_text(target,'saved on USB')
            self.assertEqual(target.read_text(encoding='utf-8'),'saved on USB')
            with self.assertRaisesRegex(ValueError,'보존'):bridge.export_text(target,'replacement')
            self.assertEqual(target.read_text(encoding='utf-8'),'saved on USB')

    def test_audio_links_require_vault_and_finite_unique_clip_bounds(self):
        vault='a'*32;record='b'*32;url=f'solasi://audio/{vault}/{record}?start_ms=1000&end_ms=2500'
        self.assertEqual(bridge.audio_link(url,vault),{'url':'/api/recordings/'+record+'/audio','start':1.0,'end':2.5})
        for invalid in (url.replace(vault,'c'*32),url+'&start_ms=0',url.replace('2500','NaN'),url.replace('1000','-1'),url+'#x',url.replace('audio/','audio.evil/')):
            with self.subTest(url=invalid),self.assertRaises(ValueError):bridge.audio_link(invalid,vault)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        bind=socket.socket.bind
        def application_bind(sock,address):
            # Windows asyncio builds its wakeup socketpair using this stdlib-only temporary listener.
            if sys._getframe(1).f_code is socket._fallback_socketpair.__code__:return bind(sock,address)
            raise AssertionError('native engine opened a network listener')
        listener=patch('socket.socket.bind',new=application_bind)
        listener.start();self.addCleanup(listener.stop)
        self.engine=bridge.Engine(AppConfig(self.root/'data',self.root/'runtime',embedded=True))
        self.engine.start();self.addCleanup(self.engine.close)

    def http(self,path,method='GET',value=None,**fields):
        return self.engine.submit(self.engine.http(path,method,json.dumps(value).encode() if value is not None else b'',**fields)).result(10)

    def test_asgi_and_sqlite_live_on_one_owned_thread_without_listener(self):
        with self.http('/api/courses','POST',{'title':'윈도 수업'}) as response:
            self.assertEqual(response.status,201)
        with self.http('/api/courses') as response:
            rows=json.load(response.body);self.assertEqual(rows[0]['title'],'윈도 수업')
        self.assertNotEqual(self.engine.thread.ident,threading.get_ident())

    def test_listener_guard_allows_only_stdlib_socketpair_infrastructure(self):
        with socket.socket() as application:
            with self.assertRaisesRegex(AssertionError,'network listener'):application.bind(('127.0.0.1',0))
        with self.subTest('Windows asyncio wakeup socketpair'):
            if sys.platform!='win32':self.skipTest('Windows asyncio uses this temporary TCP socketpair; macOS uses native socketpair')
            first,second=socket._fallback_socketpair()
            try:
                first.sendall(b'event loop wakeup');self.assertEqual(second.recv(64),b'event loop wakeup')
            finally:first.close();second.close()

    def test_validation_limits_and_native_picker_are_enforced(self):
        for path in ('https://evil/api/courses','/api/../private','/api/bootstrap'):
            with self.subTest(path=path),self.assertRaises(ValueError):self.http(path)
        with self.assertRaises(ValueError):self.engine.submit(self.engine.http('/api/courses','POST',b'x'*(bridge.MAX_BODY+1))).result(5)
        with self.assertRaises(ValueError):self.http('/api/courses/'+'a'*32+'/files/select','POST',{})

    def test_http_cancellation_closes_response_generator(self):
        async def setup():
            from starlette.responses import StreamingResponse
            self.engine.app.router.routes=[r for r in self.engine.app.router.routes if getattr(r,'name','')!='frontend']
            @self.engine.app.get('/api/test/stream')
            async def stream():
                async def parts():
                    try:
                        yield b'first';await asyncio.sleep(60)
                    finally:(self.root/'cancelled').write_text('yes')
                return StreamingResponse(parts())
        self.engine.submit(setup()).result(5)
        pending=self.engine.submit(self.engine.http('/api/test/stream',ident='cancelled'))
        async def cancel():
            while 'cancelled' not in self.engine.worker.requests:await asyncio.sleep(0)
            await asyncio.sleep(.02);self.engine.cancel('cancelled')
        self.engine.submit(cancel()).result(5)
        with self.assertRaises(BaseException):pending.result(5)
        self.assertTrue((self.root/'cancelled').exists())

    def test_native_file_selection_links_original_and_resource_ranges_work(self):
        import uuid
        with self.http('/api/courses','POST',{'title':'자료'}) as response:course=json.load(response.body)
        original=self.root/'한글 원본.txt';original.write_text('연결된 자료 원문',encoding='utf-8')
        commands=bridge.Commands(self.engine,lambda:True,lambda path:[str(original)],lambda _:None)
        reply=commands.command({'op':'http','id':str(uuid.uuid4()),'path':'/api/courses/'+course['id']+'/files/select','method':'POST'})
        self.assertEqual(reply['status'],201)
        with self.http('/api/courses/'+course['id']+'/materials') as response:rows=json.load(response.body)['assets']
        self.assertEqual(len(rows),1)
        asset=rows[0]['id'];url='https://solasi.invalid/api/assets/'+asset+'/original'
        self.assertEqual(self.engine.submit(self.engine.original(url)).result(5),original.resolve())
        with self.http('/api/assets/'+asset+'/original',headers={'range':'bytes=0-2'}) as response:
            self.assertEqual(response.status,206);self.assertEqual(response.body.read(),original.read_bytes()[:3])


class CommandTests(unittest.TestCase):
    def test_stale_seed_navigation_failure_does_not_disable_loaded_app_or_show_error(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            host=windows_app.Host(None,Path(directory));self.addCleanup(host.pool.shutdown)
            errors=[];host.show_error=errors.append;host.core=SimpleNamespace(Source='https://solasi.invalid/')
            host.navigation(None,SimpleNamespace(Uri='https://solasi.invalid/',NavigationId=2,IsUserInitiated=False))
            host.source_changed(None,None);host.ready=True
            host.loaded(None,SimpleNamespace(NavigationId=1,IsSuccess=False))
            host.pool.shutdown(wait=True)
            self.assertTrue(host.trusted);self.assertTrue(host.ready);self.assertEqual(errors,[])

    def test_current_root_navigation_failure_is_reported_but_old_root_completion_is_ignored(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            host=windows_app.Host(None,Path(directory));self.addCleanup(host.pool.shutdown)
            errors=[];host.show_error=errors.append;host.core=SimpleNamespace(Source='https://solasi.invalid/')
            for ident in (2,3):host.navigation(None,SimpleNamespace(Uri='https://solasi.invalid/',NavigationId=ident,IsUserInitiated=False))
            host.loaded(None,SimpleNamespace(NavigationId=2,IsSuccess=False))
            host.loaded(None,SimpleNamespace(NavigationId=3,IsSuccess=True));self.assertTrue(host.trusted)
            host.loaded(None,SimpleNamespace(NavigationId=3,IsSuccess=False))
            host.pool.shutdown(wait=True)
            self.assertFalse(host.trusted);self.assertFalse(host.ready);self.assertEqual(len(errors),1)

    def test_source_change_authenticates_startup_before_navigation_completed(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            host=windows_app.Host(None,Path(directory));self.addCleanup(host.pool.shutdown)
            host.core=SimpleNamespace(Source='https://solasi.invalid/')
            host.source_changed(None,None);self.assertTrue(host.trusted)
            host.core.Source='https://solasi.invalid.evil/'
            host.source_changed(None,None);self.assertFalse(host.trusted)

    def test_commands_require_trusted_context_and_native_selection_cannot_be_supplied_by_js(self):
        handler=bridge.Commands(None,lambda:False,lambda *_:None,lambda *_:None)
        with self.assertRaises(ValueError):handler.command({'op':'ui_ready'})
        handler.trusted=lambda:True
        with self.assertRaises(ValueError):handler.command({'op':'http','id':'x','path':'/api/courses','method':'GET','native_selected_files':['/secret']})

    def test_close_flushes_then_confirms_recording_and_cancellation_resumes(self):
        order=[]
        class Engine:
            captures={'active':object()}
            def close(self):order.append('saved')
        self.assertFalse(windows_app.finish_close(Engine(),lambda:order.append('flushed'),lambda:False,lambda:order.append('resumed')))
        self.assertEqual(order,['flushed','resumed']);order.clear()
        self.assertTrue(windows_app.finish_close(Engine(),lambda:order.append('flushed'),lambda:True,lambda:order.append('resumed')))
        self.assertEqual(order,['flushed','saved'])

    def test_close_does_not_stop_recording_when_draft_flush_fails(self):
        class Engine:
            captures={'active':object()}
            def close(self):raise AssertionError('must not close')
        def failure():raise ValueError('초안 저장 실패')
        with self.assertRaisesRegex(ValueError,'초안'):windows_app.finish_close(Engine(),failure,lambda:True,lambda:None)


if __name__=='__main__':unittest.main()
