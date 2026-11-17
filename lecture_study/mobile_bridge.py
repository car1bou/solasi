"""Native-only embedded transport. No listener, process, platform capture or inference.

Native hosts must authenticate the top frame/origin before calling ``command``.
Only native picker/resource code may call the other methods or see temporary paths.
"""
import asyncio
import base64
import binascii
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import asynccontextmanager
import json
from pathlib import Path
import re
import tempfile
import threading
from urllib.parse import unquote, urlsplit
import uuid

from .config import AppConfig
from .native_worker import MAX_BODY, MAX_CHUNK, MAX_HEADER, PICKER, valid_id
from .windows_bridge import Engine, RESOURCE, byte_range, resource_path

MAX_RESOURCES = 8
MAX_RESOURCE_BYTES = 64 * 1024 * 1024
UNAVAILABLE = '모바일 연결 라이브러리가 준비되지 않았습니다'
ID = r'[a-f0-9]{32}'
# Only mutations known to remain inside SQLite/filesystem are admitted until Task 5.
SAFE_MUTATION = re.compile(
    rf'^/api/(?:courses|sessions|sessions/{ID}/(?:note|terms|participants|transcription-terms)|'
    rf'courses/{ID}/assets/{ID}/pages/[1-9][0-9]*/document|'
    rf'sessions/{ID}/assets/{ID}|jobs/{ID}/cancel|attempts/{ID}|'
    rf'artifacts/{ID}(?:/apply-note)?|transcripts/{ID}|sessions/{ID}/transcripts|'
    rf'knowledge/options|study/(?:threads(?:/{ID})?|options|memories(?:/{ID})?|retry-memory))$')


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate JSON field')
        value[key] = item
    return value


def _message(raw):
    if not isinstance(raw, str) or len(raw.encode('utf-8')) > MAX_BODY + MAX_HEADER:
        raise ValueError('Invalid command size')
    try:
        value = json.loads(raw, object_pairs_hook=_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Invalid JSON number')))
    except (ValueError, RecursionError, UnicodeError):
        raise ValueError('Invalid JSON command') from None
    if not isinstance(value, dict):
        raise ValueError('Command must be an object')
    return value


def _fields(message, allowed):
    if set(message) - set(allowed):
        raise ValueError('Unknown or native-only command fields')


def _path(path):
    if not isinstance(path, str) or len(path) > 8192:
        raise ValueError('Invalid API path')
    try:
        parts = urlsplit(path)
        decoded = unquote(parts.path, errors='strict')
    except (ValueError, UnicodeError):
        raise ValueError('Invalid API path encoding') from None
    if (parts.scheme or parts.netloc or parts.fragment or not decoded.startswith('/api/')
            or '%' in decoded or '\\' in decoded
            or any(ord(c) < 32 or ord(c) == 127 for c in path + decoded)
            or any(part in ('.', '..') for part in decoded.split('/'))
            or decoded in ('/api/bootstrap', '/api/client')):
        raise ValueError('Only canonical application API paths are allowed')
    return decoded


def _headers(supplied):
    if not isinstance(supplied, dict) or len(supplied) > 8:
        raise ValueError('Invalid request headers')
    result = {}
    for key, value in supplied.items():
        if (not isinstance(key, str) or key.lower() not in {'accept', 'content-type', 'range', 'if-range'}
                or key.lower() in result or not isinstance(value, str) or len(value) > 4096
                or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError('Request header is not allowed')
        try:
            value.encode('latin-1')
        except UnicodeError:
            raise ValueError('Invalid request header encoding') from None
        result[key.lower()] = value
    if 'range' in result:
        header = result['range']
        if not re.fullmatch(r'bytes=\d{0,18}-\d{0,18}', header):
            raise ValueError('Invalid resource range')
        # Use the shared byte-range validator for semantics without assuming file size.
        byte_range(header, 2**63 - 1)
    return result


class UnavailableModels:
    async def available(self):
        return {'connected': False, 'managed_connected': False, 'models': [], 'catalog': [],
                'download': {'status': 'unavailable', 'error': UNAVAILABLE},
                'engine': 'mobile-unavailable', 'error': UNAVAILABLE}

    async def stop(self):
        pass


class UnavailableSecrets:
    """Do not touch desktop keychains while the native secure store is unbound."""
    def __init__(self):
        self.memory = {}

    def status(self):
        return {provider: {'configured': False, 'storage': 'unavailable', 'error': UNAVAILABLE}
                for provider in ('openai', 'gemini', 'claude')}


def _create_app(config):
    from fastapi.responses import JSONResponse
    from .server import create_app
    app = create_app(config)
    app.state.direct_models = UnavailableModels()
    app.state.secrets = UnavailableSecrets()
    original = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with original(application):
            # Desktop recovery/brain workers can spawn engines; bind mobile engines first.
            tasks = list(application.state.tasks)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            yield
    app.router.lifespan_context = lifespan

    @app.middleware('http')
    async def mobile_capabilities(request, call_next):
        path = request.url.path
        if path == '/api/runtime/status':
            return JSONResponse([{'label': '기록 저장', 'ready': True},
                                 *[{'label': label, 'ready': False, 'error': UNAVAILABLE}
                                   for label in ('PDF·이미지 추출', '전사', '로컬 모델 연결')]])
        blocked = (path == '/api/runtime/details'
                   or re.fullmatch(rf'/api/assets/{ID}/(?:document|pages/[1-9][0-9]*|images/[^/]+)', path)
                   or (request.method not in ('GET', 'HEAD')
                       and not SAFE_MUTATION.fullmatch(path)
                       and not PICKER.fullmatch(path)))
        if blocked:
            return JSONResponse({'detail': UNAVAILABLE, 'code': 'mobile_adapter_unavailable'}, status_code=501)
        if PICKER.fullmatch(path) and request.scope.get('native_selected_files'):
            return JSONResponse({'detail': UNAVAILABLE, 'code': 'mobile_adapter_unavailable'}, status_code=501)
        return await call_next(request)
    return app


class _BoundedFile:
    def __init__(self, directory):
        self.file = tempfile.NamedTemporaryFile(prefix='resource-', dir=directory, delete=False)
        self.length = 0
        self.exceeded = False

    def write(self, chunk):
        if self.length + len(chunk) > MAX_RESOURCE_BYTES:
            # Drain the ASGI body so its source file is closed normally on overflow.
            self.exceeded = True
        if self.exceeded:
            return len(chunk)
        self.length += len(chunk)
        return self.file.write(chunk)

    def __getattr__(self, name):
        return getattr(self.file, name)


class _Response:
    def __init__(self, directory):
        self.status, self.headers = 200, []
        self.body = _BoundedFile(directory)
        self.path = Path(self.body.name)

    def close(self):
        self.body.close()
        self.path.unlink(missing_ok=True)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class MobileBridge:
    def __init__(self, data_dir, runtime_dir):
        data_dir, runtime_dir = Path(data_dir), Path(runtime_dir)
        runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._temporary = tempfile.TemporaryDirectory(prefix='mobile-responses-', dir=runtime_dir)
        self.response_dir = Path(self._temporary.name)
        self._resources = {}
        self._streams = {}
        self._lock = threading.RLock()
        self._audio_lock = threading.Lock()
        self._closed = False
        self.engine = Engine(AppConfig(data_dir, runtime_dir, embedded=True),
                             app_factory=_create_app, response_factory=self._response)
        try:
            self.engine.start()
        except BaseException:
            self._temporary.cleanup()
            raise

    def _response(self):
        return _Response(self.response_dir)

    def _check_open(self):
        if self._closed:
            raise ValueError('Mobile bridge is closed')

    def _wait(self, operation):
        pending = self.engine.submit(operation)
        try:
            return pending.result(120)
        except FutureTimeout:
            pending.cancel()
            raise ValueError('Mobile operation timed out and was cancelled') from None

    def _audio_wait(self, operation):
        if not self._audio_lock.acquire(blocking=False):
            operation.close()
            raise ValueError('Wait for the previous saved audio ACK')
        try:
            return self._wait(operation)
        finally:
            self._audio_lock.release()

    def _response_wait(self, operation):
        response = self._wait(operation)
        if response.body.exceeded:
            response.close()
            raise ValueError('Resource exceeds 64 MiB; use byte ranges')
        return response

    def _http(self, message, selected=None, native=False):
        _fields(message, ('op', 'id', 'path', 'method', 'body', 'headers'))
        if message.get('op') != 'http' or not valid_id(message.get('id')):
            raise ValueError('Invalid HTTP command identity')
        path = _path(message.get('path'))
        method = message.get('method')
        if method not in {'GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE'}:
            raise ValueError('Invalid HTTP method')
        picker = method == 'POST' and PICKER.fullmatch(path)
        if bool(picker) != native:
            raise ValueError('Picker requests require the native selection entrypoint')
        body = message.get('body', '')
        if not isinstance(body, str):
            raise ValueError('HTTP body must be a string')
        body = body.encode('utf-8')
        if len(body) > MAX_BODY:
            raise ValueError('HTTP body exceeds 10 MiB')
        headers = _headers(message.get('headers', {}))
        return self._response_wait(self.engine.http(message['path'], method, body, headers,
                                           ident=message['id'], selected=selected))

    @staticmethod
    def _reply(response):
        with response:
            if response.path.stat().st_size > MAX_BODY:
                raise ValueError('Command response exceeds 10 MiB; use native resource routing')
            return _json({'status': response.status, 'text': response.body.read().decode('utf-8')})

    def command(self, raw):
        self._check_open()
        message = _message(raw)
        op = message.get('op')
        if op == 'ui_ready':
            _fields(message, ('op',))
            return _json({'ready': True})
        if op == 'cancel':
            _fields(message, ('op', 'target'))
            if not valid_id(message.get('target')):
                raise ValueError('Invalid cancellation target')
            self.engine.loop.call_soon_threadsafe(self.engine.cancel, message['target'])
            return _json({'cancelled': True})
        if op != 'http':
            raise ValueError('Unknown or native-only operation; platform capture is unavailable')
        return self._reply(self._http(message))

    def select(self, raw, native_selected_paths):
        self._check_open()
        if (not isinstance(native_selected_paths, list) or len(native_selected_paths) > 64
                or any(not isinstance(p, str) or not 0 < len(p) <= 4096 or '\x00' in p
                       or not Path(p).is_absolute() for p in native_selected_paths)):
            raise ValueError('Invalid native file selection')
        return self._reply(self._http(_message(raw), selected=native_selected_paths, native=True))

    def resource(self, raw):
        message = _message(raw)
        _fields(message, ('url', 'method', 'headers'))
        path = resource_path(message.get('url'))
        if not RESOURCE.fullmatch(_path(path)):
            raise ValueError('Only known API resources are allowed')
        method = message.get('method', 'GET')
        if method not in ('GET', 'HEAD'):
            raise ValueError('Only read-only resources are allowed')
        headers = _headers(message.get('headers', {}))
        with self._lock:
            self._check_open()
            if len(self._resources) >= MAX_RESOURCES:
                raise ValueError('Release outstanding native resources first')
            response = self._response_wait(self.engine.http(path, method, headers=headers))
            token = uuid.uuid4().hex
            self._resources[token] = response
            return _json({'status': response.status, 'headers': response.headers,
                          'path': str(response.path), 'token': token})

    def release_resource(self, token):
        if not isinstance(token, str) or not re.fullmatch('[a-f0-9]{32}', token):
            raise ValueError('Invalid resource token')
        with self._lock:
            response = self._resources.pop(token, None)
            if response:
                response.close()

    def audio_open(self, raw):
        """Native microphone lifecycle only; availability of ASR never gates saving PCM."""
        self._check_open()
        message = _message(raw)
        _fields(message, ('session_id', 'sample_rate', 'transcription_mode'))
        sid, rate, mode = (message.get(key) for key in ('session_id', 'sample_rate', 'transcription_mode'))
        if (not isinstance(sid, str) or not re.fullmatch(ID, sid) or type(rate) is not int
                or not 8000 <= rate <= 192000 or mode not in ('after_stop', 'realtime')):
            raise ValueError('Invalid native audio configuration')
        return _json(self._audio_wait(self._open_audio(sid, rate, mode)))

    async def _open_audio(self, sid, rate, mode):
        from .audio import start_recording
        if self._streams:
            raise ValueError('A native capture is already active')
        rid = start_recording(self.engine.app.state.db, sid, rate, mode)
        stream = uuid.uuid4().hex
        self._streams[stream] = rid
        return {'stream_id': stream, 'recording_id': rid, 'sample_rate': rate,
                'transcription_available': False}

    def audio_packet(self, raw):
        self._check_open()
        message = _message(raw)
        _fields(message, ('stream_id', 'seq', 'first_frame', 'frame_count', 'pcm_base64'))
        encoded = message.get('pcm_base64')
        if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_CHUNK + 2) // 3):
            raise ValueError('PCM packet exceeds 256 KiB')
        try:
            payload = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError('Invalid PCM base64') from None
        if len(payload) > MAX_CHUNK:
            raise ValueError('PCM packet exceeds 256 KiB')
        return _json(self._audio_wait(self._append_audio(message, payload)))

    def _recording(self, message):
        stream = message.get('stream_id')
        if not isinstance(stream, str) or stream not in self._streams:
            raise ValueError('Native recording stream is closed')
        return self._streams[stream]

    async def _append_audio(self, message, payload):
        from .audio import append_pcm
        rid = self._recording(message)
        ack = append_pcm(self.engine.app.state.db, rid, message.get('seq'),
                         message.get('first_frame'), message.get('frame_count'), payload)
        return {'type': 'ack', **ack}

    def audio_close(self, raw):
        self._check_open()
        message = _message(raw)
        _fields(message, ('stream_id', 'end_frame', 'interrupted', 'reason'))
        end = message.get('end_frame')
        reason = message.get('reason')
        if (end is not None and (type(end) is not int or end < 0)
                or type(message.get('interrupted', False)) is not bool
                or reason is not None and (not isinstance(reason, str) or len(reason) > 300)):
            raise ValueError('Invalid native audio close')
        return _json(self._audio_wait(self._close_audio(message)))

    async def _close_audio(self, message):
        from .audio import get_recording, stop_recording
        rid = self._recording(message)
        db = self.engine.app.state.db
        job = stop_recording(db, rid, message.get('end_frame'), message.get('interrupted', False),
                             message.get('reason'))
        with db:
            db.execute('UPDATE jobs SET result=? WHERE id=?',
                       (_json({'paused_reason': UNAVAILABLE}), job['id']))
        row = get_recording(db, rid)
        self._streams.pop(message['stream_id'])
        return {key: row[key] for key in ('status', 'stored_frames', 'source_frames', 'gaps')} | {
            'recording_id': rid, 'job_id': job['id'], 'transcription_available': False}

    async def _interrupt_audio(self):
        for stream in list(self._streams):
            await self._close_audio({'stream_id': stream, 'interrupted': True,
                                     'reason': '모바일 앱이 종료되었습니다'})

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            self._wait(self._interrupt_audio())
        finally:
            self.engine.close()
            with self._lock:
                for response in self._resources.values():
                    response.close()
                self._resources.clear()
                self._temporary.cleanup()


def start(data_dir, runtime_dir):
    """Create one vault-scoped handle; never pass installed desktop vault paths."""
    return MobileBridge(data_dir, runtime_dir)
