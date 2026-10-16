import asyncio,os,signal,unittest
from unittest.mock import AsyncMock,patch
from lecture_study.process_owner import native_owner,watch_owner

class ProcessOwnerTests(unittest.IsolatedAsyncioTestCase):
    def test_native_ownership_is_explicit_and_validated(self):
        with patch.dict(os.environ,{},clear=True):self.assertIsNone(native_owner())
        with patch.dict(os.environ,{'SOLASI_OWNER_PID':'123'}):self.assertEqual(native_owner(),123)
        for value in ('','-1','0','1','12.5','not-a-pid'):
            with self.subTest(value=value),patch.dict(os.environ,{'SOLASI_OWNER_PID':value}):
                with self.assertRaises(ValueError):native_owner()

    async def test_owner_change_requests_one_graceful_server_shutdown(self):
        with patch('lecture_study.process_owner.os.getppid',side_effect=[123,1]),patch('lecture_study.process_owner.os.getpid',return_value=456),patch('lecture_study.process_owner.os.kill')as kill,patch('lecture_study.process_owner.asyncio.sleep',new=AsyncMock())as sleep:
            await watch_owner(123)
        sleep.assert_awaited_once_with(1)
        kill.assert_called_once_with(456,signal.SIGTERM)

    async def test_live_owner_and_cancel_do_not_signal_the_server(self):
        waiting=asyncio.Event()
        async def sleep(_):waiting.set();await asyncio.Event().wait()
        with patch('lecture_study.process_owner.os.getppid',return_value=123),patch('lecture_study.process_owner.os.kill')as kill,patch('lecture_study.process_owner.asyncio.sleep',new=sleep):
            task=asyncio.create_task(watch_owner(123));await waiting.wait();kill.assert_not_called();task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
            kill.assert_not_called()

    async def test_app_lifespan_starts_and_reaps_only_an_explicit_owner(self):
        import tempfile
        from pathlib import Path
        from lecture_study import server
        from lecture_study.config import AppConfig
        with tempfile.TemporaryDirectory()as folder:
            started,finished=asyncio.Event(),asyncio.Event()
            async def watch(owner):
                self.assertEqual(owner,123);started.set()
                try:await asyncio.Event().wait()
                finally:finished.set()
            with patch.object(server,'native_owner',return_value=123),patch.object(server,'watch_owner',new=watch):
                app=server.create_app(AppConfig(Path(folder),Path(folder)/'runtime'))
                async with app.router.lifespan_context(app):await started.wait()
                self.assertTrue(finished.is_set())
            with patch.object(server,'native_owner',return_value=None),patch.object(server,'watch_owner',new=AsyncMock())as watcher:
                app=server.create_app(AppConfig(Path(folder),Path(folder)/'runtime'))
                async with app.router.lifespan_context(app):pass
                watcher.assert_not_called()
