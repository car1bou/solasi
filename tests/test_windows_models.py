import asyncio
import hashlib
import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from lecture_study.models import ProviderConfig


class WindowsModelsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def fixture(self):
        from lecture_study import windows_models as windows
        payloads = {'model.gguf': b'GGUF'+struct.pack('<I', 3)+b'model',
                    'mmproj.gguf': b'GGUF'+struct.pack('<I', 3)+b'vision',
                    'tokenizer.json': b'{}', 'LICENSE': b'fixture license'}
        files = {name: {'url': 'https://huggingface.co/fixture/resolve/'+'a'*40+'/'+name,
                        'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                 for name, data in payloads.items()}
        self.enterContext(patch.object(windows, 'WINDOWS_FILES', files))
        manager = windows.WindowsModels(self.root/'runtime', self.root/'cache')
        return windows, manager, files, payloads

    def engine_fixture(self,manager,*,dispatch=True):
        from lecture_study.direct_models import EMBEDDING_ENGINE
        from lecture_study.windows_models import ENGINE_ID
        root=manager.engine_dir;(root/'lib').mkdir(parents=True)
        names=['ModelWorker.exe','EmbeddingWorker.exe']+(['WindowsCpu.exe','ModelWorker-avx2.exe','EmbeddingWorker-avx2.exe']if dispatch else[])
        for name in names:(root/name).write_bytes(name.encode())
        record={'engine':EMBEDDING_ENGINE,'generation_engine':ENGINE_ID,
                'revision':'620d2225cc436ab0b001e3200e590e3b286ef9ab','architecture':'x64',
                'files':{name:{'bytes':(root/name).stat().st_size,'sha256':hashlib.sha256((root/name).read_bytes()).hexdigest()}for name in names}}
        if dispatch:record['cpu_dispatch']='avx2-fma-f16c-v1'
        (root/'receipt.json').write_text(json.dumps(record),encoding='utf-8')
        return root,record

    async def test_generation_and_embedding_select_only_verified_cpu_compatible_variants(self):
        from types import SimpleNamespace
        _,manager,_,_=self.fixture();root,_=self.engine_fixture(manager)
        for compatible in (True,False):
            with self.subTest(avx2=compatible),patch('subprocess.run',return_value=SimpleNamespace(stdout=json.dumps({'version':1,'avx2_compatible':compatible}).encode()))as probe:
                suffix='-avx2'if compatible else''
                self.assertEqual(manager._generation_command(),[str(root/('ModelWorker'+suffix+'.exe')),str(root/'lib')])
                self.assertEqual(manager._embedding_command(Path('model.gguf')),[str(root/('EmbeddingWorker'+suffix+'.exe')),'model.gguf',str(root/'lib')])
                self.assertEqual(probe.call_args.args[0],[str(root/'WindowsCpu.exe')])
                self.assertTrue(probe.call_args.kwargs['check'])

    async def test_legacy_model_engine_receipt_keeps_baseline_without_cpu_probe(self):
        _,manager,_,_=self.fixture();root,_=self.engine_fixture(manager,dispatch=False)
        # Frozen ASR/OCR engines have their own receipts below the shared engines directory.
        sibling=root/'asr/bin/ffmpeg.exe';sibling.parent.mkdir(parents=True);sibling.write_bytes(b'separate engine')
        with patch('subprocess.run')as probe:
            self.assertEqual(manager._generation_command()[0],str(root/'ModelWorker.exe'))
            self.assertEqual(manager._embedding_command(Path('model.gguf'))[0],str(root/'EmbeddingWorker.exe'))
            probe.assert_not_called()

    async def test_incomplete_unknown_or_tampered_model_variants_never_execute_probe(self):
        _,manager,_,_=self.fixture();root,record=self.engine_fixture(manager)
        with patch('subprocess.run')as probe:
            for invalid in (record|{'cpu_dispatch':'unknown'},record|{'files':{name:item for name,item in record['files'].items()if name!='EmbeddingWorker-avx2.exe'}}):
                (root/'receipt.json').write_text(json.dumps(invalid),encoding='utf-8')
                with self.assertRaises(ValueError):manager._generation_command()
            (root/'receipt.json').write_text(json.dumps(record),encoding='utf-8')
            (root/'EmbeddingWorker-avx2.exe').write_bytes(b'x'*(root/'EmbeddingWorker-avx2.exe').stat().st_size)
            with self.assertRaises(ValueError):manager._generation_command()
            probe.assert_not_called()

    async def test_unlisted_worker_and_invalid_probe_output_do_not_allow_execution(self):
        from types import SimpleNamespace
        _,manager,_,_=self.fixture();root,_=self.engine_fixture(manager)
        with patch('subprocess.run',return_value=SimpleNamespace(stdout=b'{"version":1,"avx2_compatible":"true"}')):
            with self.assertRaises(ValueError):manager._generation_command()
        (root/'unlisted.dll').write_bytes(b'unknown')
        with patch('subprocess.run')as probe:
            with self.assertRaises(ValueError):manager._embedding_command(Path('model.gguf'))
            probe.assert_not_called()

    async def download(self, manager, payloads):
        def respond(request):
            self.assertEqual(request.url.host, 'huggingface.co')
            return httpx.Response(200, content=payloads[request.url.path.rsplit('/', 1)[-1]])
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            await manager.pull('qwen3.5:4b', 'llamacpp', client=client)

    async def test_download_publishes_only_complete_verified_generation_bundle(self):
        windows, manager, files, payloads = self.fixture()
        self.assertEqual((await manager.available())['models'], [])
        await self.download(manager, payloads)
        self.assertEqual(manager.progress['status'], 'done')
        asset = await manager.asset('qwen3.5:4b')
        self.assertEqual(asset['format'], 'gguf')
        self.assertEqual({row['kind'] for row in asset['files']}, {'model', 'projector', 'json', 'license'})
        before = {row['path']: row['path'].read_bytes() for row in asset['files']}
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, content=b'wrong'))) as client:
            await manager.pull('qwen3.5:4b', 'llamacpp', client=client)
        self.assertEqual({path: path.read_bytes() for path in before}, before)
        self.assertEqual((await manager.asset('qwen3.5:4b'))['digest'], asset['digest'])
        model = next(row['path'] for row in asset['files'] if row['kind'] == 'model')
        model.write_bytes(b'x'*model.stat().st_size)
        with self.assertRaises(ValueError): await manager.asset('qwen3.5:4b')
        with self.assertRaises(ValueError): await manager.asset('qwen3.5:../4b')

    async def test_projector_is_required_and_symlinks_cannot_escape_bundle(self):
        windows, manager, files, payloads = self.fixture()
        await self.download(manager, payloads)
        asset = await manager.asset('qwen3.5:4b')
        projector = next(row['path'] for row in asset['files'] if row['kind'] == 'projector')
        projector.unlink()
        with self.assertRaises(ValueError): await manager.asset('qwen3.5:4b')
        outside = self.root/'outside.gguf'; outside.write_bytes(payloads['mmproj.gguf'])
        with self.subTest('symlink boundary'):
            try: projector.symlink_to(outside)
            except OSError as error:
                if getattr(error, 'winerror', None) != 1314: raise
                self.skipTest('Windows symlink privilege unavailable; missing-projector check passed')
            with self.assertRaises(ValueError): await manager.asset('qwen3.5:4b')

    async def test_readiness_requires_matching_engine_receipt_and_binds_tokenizer_identity(self):
        windows, manager, files, payloads = self.fixture()
        await self.download(manager, payloads)
        self.assertFalse((await manager.available())['models'][0]['usable'])
        from lecture_study.direct_models import EMBEDDING_ENGINE
        engine = manager.engine_dir; (engine/'lib').mkdir(parents=True)
        worker = engine/'ModelWorker.exe'
        worker.write_text('''import json,struct,sys
body=json.dumps({'ok':True,'result':{'engine':sys.argv[1]}}).encode()
sys.stdout.buffer.write(struct.pack('>I',len(body))+body)
''')
        (engine/'EmbeddingWorker.exe').write_bytes(b'fixture')
        record = {'engine':EMBEDDING_ENGINE, 'generation_engine':windows.ENGINE_ID,
                  'revision':'620d2225cc436ab0b001e3200e590e3b286ef9ab', 'architecture':'x64',
                  'files':{path.name:{'bytes':path.stat().st_size, 'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
                           for path in engine.glob('*.exe')}}
        (engine/'receipt.json').write_text(json.dumps(record))
        manager._generation_command = lambda: [sys.executable, str(worker), windows.ENGINE_ID]
        status = await manager.status('qwen3.5:4b')
        self.assertEqual(status['digest'], windows.tokenizer_profile(manager.runtime)['model_digest'])
        self.assertTrue(status['vision'])
        self.assertTrue((await manager.available())['models'][0]['usable'])
        record['generation_engine'] = 'old-engine'; (engine/'receipt.json').write_text(json.dumps(record))
        self.assertFalse((await manager.available())['models'][0]['usable'])
    async def test_generation_uses_framed_owned_worker_and_gguf_view(self):
        windows, manager, files, payloads = self.fixture()
        await self.download(manager, payloads)
        worker = self.root/'worker.py'
        worker.write_text('''import json,struct,sys
size=struct.unpack('>I',sys.stdin.buffer.read(4))[0]
request=json.loads(sys.stdin.buffer.read(size))
assert request['output_limit']==123 and request['context_limit']==8192
from pathlib import Path
assert (Path(request['view'])/'mmproj.gguf').is_file()
assert request['schema']=={'type':'object'}
body=json.dumps({'ok':True,'result':{'text':'{}','finish_reason':'stop','usage':{'eval_count':1}}}).encode()
sys.stdout.buffer.write(struct.pack('>I',len(body))+body)
''')
        manager._generation_command = lambda: [sys.executable, str(worker)]
        manager.status = AsyncMock(return_value={'digest':'d'*64, 'context_limit':8192})
        config = ProviderConfig(provider='local', model='qwen3.5:4b')
        response = await manager.generate(config, [{'role':'user','content':'한국어'}], [], {'type':'object'}, output_limit=123)
        self.assertEqual(response['text'], '{}')
        self.assertEqual(manager.processes, set())
        with self.assertRaises(ValueError):
            await manager.generate(config, [{'role':'tool','content':'invalid'}], [], None, output_limit=1)
        with self.assertRaises(ValueError):
            await manager.generate(config, [{'role':'user','content':'한국어'}], [], None, output_limit=0)

    async def test_windows_tokenizer_profile_binds_gguf_identity_and_rejects_change(self):
        windows, manager, files, payloads = self.fixture()
        await self.download(manager, payloads)
        profile = windows.tokenizer_profile(manager.runtime)
        self.assertEqual(profile['model'], 'qwen3.5:4b')
        self.assertEqual(profile['sha256'], files['tokenizer.json']['sha256'])
        self.assertNotEqual(profile['model_digest'], windows.model_identity('qwen3.5:4b', 'a'*64))
        from lecture_study.token_budget import local_profile
        with patch('lecture_study.token_budget.sys.platform', 'win32'):
            selected = local_profile(ProviderConfig(provider='local', model='qwen3.5:4b'), manager.runtime)
        self.assertEqual(selected, profile)
        Path(profile['path']).write_text('bad')
        self.assertIsNone(windows.tokenizer_profile(manager.runtime))

    async def test_long_summary_uses_effective_context_and_preserves_all_source_text(self):
        from lecture_study.answers import freeze_request
        from lecture_study.db import open_db, create_session
        from lecture_study.materials import save_note
        from lecture_study.models import AIRequest, Scope
        db = open_db(self.root/'vault'); self.addCleanup(db.close)
        sid = create_session(db, 'lecture', '긴 강의', None, None).id
        save_note(db, sid, '전반 원문입니다.\n'+('개념 설명을 빠짐없이 보존합니다. '*2000)+'\n마지막 정정 원문입니다.')
        config = ProviderConfig(provider='local', model='qwen3.5:4b', context_limit=32768)
        request = AIRequest(session_id=sid, kind='summary', prompt='전체 요약', scope=Scope(session_id=sid), provider=config)
        with patch('lecture_study.token_budget.sys.platform', 'win32'):
            frozen = await freeze_request(db, request)
        self.assertEqual(frozen['request']['provider']['context_limit'], 8192)
        self.assertEqual(request.provider.context_limit, 32768)
        self.assertGreater(len(frozen['summary_parts']), 1)
        for evidence in frozen['evidence']:
            chunks = [item['text'] for part in frozen['summary_parts'] for item in part if item['ref']['id'] == evidence['ref']['id']]
            self.assertEqual(''.join(chunks), evidence['text'])
        self.assertTrue(any('마지막 정정 원문입니다.' in item['text'] for part in frozen['summary_parts'] for item in part))

    async def test_budget_rejects_windows_overflow_before_inference_but_preserves_mac_policy(self):
        from lecture_study.outputs import check_budget
        config = ProviderConfig(provider='local', model='qwen3.5:4b', context_limit=32768)
        messages = [{'role':'user', 'content':'x'*6000}]
        with patch('lecture_study.token_budget.sys.platform', 'win32'):
            with self.assertRaises(ValueError): check_budget(config, messages, {}, output_limit=4096)
        with patch('lecture_study.token_budget.sys.platform', 'darwin'):
            self.assertGreater(check_budget(config, messages, {}, output_limit=4096), 6000)

    async def test_embedding_receipt_enforces_x64_and_exe_without_changing_vector_format(self):
        windows, manager, files, payloads = self.fixture()
        from lecture_study.direct_models import EMBEDDING_ENGINE, EMBEDDING_FORMAT
        engine = manager.engine_dir; (engine/'lib').mkdir(parents=True)
        worker = engine/'EmbeddingWorker.exe'; worker.write_bytes(b'worker')
        receipt = {'engine': EMBEDDING_ENGINE, 'revision': '620d2225cc436ab0b001e3200e590e3b286ef9ab',
                   'architecture':'x64', 'files': {'EmbeddingWorker.exe': {'bytes':6, 'sha256':hashlib.sha256(b'worker').hexdigest()}}}
        (engine/'receipt.json').write_text(json.dumps(receipt))
        manager.check_embedding_engine()
        self.assertEqual(manager.embedding_format, EMBEDDING_FORMAT)
        self.assertEqual(manager._embedding_command(Path('model.gguf'))[0], str(worker))
        receipt['architecture'] = 'arm64'; (engine/'receipt.json').write_text(json.dumps(receipt))
        with self.assertRaises(ValueError): manager.check_embedding_engine()

    async def test_failed_initial_download_never_appears_installed(self):
        windows, manager, files, payloads = self.fixture()
        bad = dict(payloads, **{'mmproj.gguf': b'wrong'})
        await self.download(manager, bad)
        self.assertEqual(manager.progress['status'], 'failed')
        self.assertEqual((await manager.available())['models'], [])
        self.assertFalse(list((manager.runtime/'windows-models').glob('.download-*')))
        with self.assertRaises(ValueError): manager.begin_pull('qwen3.5:4b', 'mlx')

    async def test_cancelled_download_removes_partial_files_without_publication(self):
        windows, manager, files, payloads = self.fixture()
        started = asyncio.Event()
        class Pending(httpx.AsyncByteStream):
            async def __aiter__(self):
                started.set()
                await asyncio.Event().wait()
                yield b''
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, stream=Pending()))) as client:
            task = asyncio.create_task(manager.pull('qwen3.5:4b', 'llamacpp', client=client))
            await asyncio.wait_for(started.wait(), 2)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
        self.assertEqual(manager.progress['status'], 'cancelled')
        self.assertEqual(list((manager.runtime/'windows-models').iterdir()), [])

    async def test_valid_hash_does_not_publish_non_gguf_weights(self):
        windows, manager, files, payloads = self.fixture()
        payloads['model.gguf'] = b'not a GGUF'
        files['model.gguf'].update(bytes=10, sha256=hashlib.sha256(payloads['model.gguf']).hexdigest())
        await self.download(manager, payloads)
        self.assertEqual(manager.progress['status'], 'failed')
        self.assertFalse(windows.bundle_directory(manager.runtime).exists())


class WindowsNativeBuildTests(unittest.TestCase):
    def test_build_rejects_unverified_source_before_creating_destination(self):
        import subprocess
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); archive = root/'source.tar.gz'; archive.write_bytes(b'untrusted source')
            result = subprocess.run([sys.executable, 'scripts/build_windows_models.py', '--archive', str(archive),
                                     '--destination', str(root/'engines')], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('SHA256', result.stderr)
            self.assertFalse((root/'engines').exists())

    @unittest.skipUnless(os.environ.get('SOLASI_GENERATION_WORKER'), 'set SOLASI_GENERATION_WORKER to run compiled native protocol tests')
    def test_native_worker_checks_framing_and_rejects_invalid_input_before_loading(self):
        import subprocess
        worker = os.environ['SOLASI_GENERATION_WORKER']
        def invoke(payload=None, check=False):
            command = [worker, str(Path(worker).parent/'lib')]+(['--check'] if check else [])
            run = subprocess.run(command, input=payload, capture_output=True, timeout=15)
            self.assertGreaterEqual(len(run.stdout), 4, run.stderr.decode(errors='replace'))
            size, = struct.unpack('>I', run.stdout[:4])
            self.assertEqual(size, len(run.stdout)-4)
            return run.returncode, json.loads(run.stdout[4:])
        code, result = invoke(check=True)
        self.assertEqual(code, 0)
        self.assertTrue(result['ok'])
        self.assertIn('windows-cpu-qwen35', result['result']['engine'])
        for payload in (b'\x00\x01', struct.pack('>I', 10*1024*1024+1), struct.pack('>I', 3)+b'{}'):
            code, result = invoke(payload)
            self.assertNotEqual(code, 0)
            self.assertFalse(result['ok'])
        base = {'view':'missing', 'messages':[{'role':'user','content':'안녕'}], 'images':[], 'schema':None,
                'context_limit':8192, 'output_limit':10}
        for update, error in (({'output_limit':0}, '예산'), ({'messages':[{'role':'tool','content':'bad'}]}, '역할'),
                              ({'images':['x']*5}, '이미지'), ({'schema':[]}, 'schema')):
            body = json.dumps(base|update).encode()
            code, result = invoke(struct.pack('>I', len(body))+body)
            self.assertNotEqual(code, 0)
            self.assertFalse(result['ok'])
            self.assertIn(error, result['error'])

    @unittest.skipUnless(os.environ.get('SOLASI_GENERATION_WORKER'), 'set SOLASI_GENERATION_WORKER to run compiled Unicode path tests')
    def test_compiled_worker_and_image_paths_accept_korean_directories(self):
        import shutil
        import subprocess
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'한국어 엔진 모음'; root.mkdir()
            original = Path(os.environ['SOLASI_GENERATION_WORKER'])
            worker = root/original.name; shutil.copy2(original, worker)
            libraries = root/'라이브러리'; libraries.mkdir()
            checked = subprocess.run([str(worker), str(libraries), '--check'], capture_output=True, timeout=15)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertTrue(json.loads(checked.stdout[4:])['ok'])
            image = root/'질문 이미지.png'; image.write_bytes(b'\x89PNG\r\n\x1a\n')
            body = json.dumps({'view':str(root/'없는 모델'), 'messages':[{'role':'user','content':'설명'}],
                               'images':[str(image)], 'schema':None, 'context_limit':8192, 'output_limit':1}).encode()
            run = subprocess.run([str(worker), str(libraries)], input=struct.pack('>I', len(body))+body,
                                 capture_output=True, timeout=15)
            self.assertNotEqual(run.returncode, 0)
            result = json.loads(run.stdout[4:])
            # Reaching the model loader proves the Korean image path was opened and read first.
            self.assertEqual(result['error'], 'Qwen3.5 모델을 열 수 없습니다')
            self.assertIn(str(root/'없는 모델'/'model.gguf'), run.stderr.decode('utf-8'))


@unittest.skipUnless(os.environ.get('SOLASI_GENERATION_WORKER') and os.environ.get('SOLASI_GENERATION_MODEL_DIR'),
                     'set SOLASI_GENERATION_WORKER and SOLASI_GENERATION_MODEL_DIR for real model inference')
class WindowsGenerationModelTests(unittest.TestCase):
    def test_real_cpu_text_image_and_schema_contract(self):
        import subprocess
        import zlib
        worker = os.environ['SOLASI_GENERATION_WORKER']
        def chunk(kind, data):
            return struct.pack('>I', len(data))+kind+data+struct.pack('>I', zlib.crc32(kind+data))
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder)/'한국어 image.png'
            image.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>IIBBBBB', 8, 8, 8, 2, 0, 0, 0))+
                              chunk(b'IDAT', zlib.compress((b'\0'+b'\xff\0\0'*8)*8))+chunk(b'IEND', b''))
            counts = []
            for images in ([], [str(image)]):
                body = json.dumps({'view':os.environ['SOLASI_GENERATION_MODEL_DIR'],
                                   'messages':[{'role':'user', 'content':'Return an object with answer OK.'}],
                                   'images':images, 'context_limit':2048, 'output_limit':128,
                                   'schema':{'type':'object', 'properties':{'answer':{'type':'string', 'enum':['OK']}},
                                             'required':['answer'], 'additionalProperties':False}}).encode()
                run = subprocess.run([worker, str(Path(worker).parent/'lib')], input=struct.pack('>I', len(body))+body,
                                     capture_output=True, timeout=900)
                self.assertEqual(run.returncode, 0, run.stderr.decode(errors='replace')[-4000:])
                size, = struct.unpack('>I', run.stdout[:4]); self.assertEqual(size, len(run.stdout)-4)
                reply = json.loads(run.stdout[4:]); self.assertTrue(reply['ok'], reply)
                self.assertEqual(json.loads(reply['result']['text']), {'answer':'OK'})
                self.assertEqual(reply['result']['finish_reason'], 'stop')
                counts.append(reply['result']['usage']['prompt_eval_count'])
            self.assertGreater(counts[1], counts[0])
