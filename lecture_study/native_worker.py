"""One application lifespan over inherited pipes; no network listener."""
import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import re
import signal
import struct
import sys
import threading
from urllib.parse import unquote, urlsplit

from .config import AppConfig
from .server import create_app
from .process_owner import native_owner, watch_owner

MAX_HEADER = 64 * 1024
MAX_BODY = 10 * 1024 * 1024
MAX_CHUNK = 256 * 1024
MAX_REQUESTS = 32
ACK_SECONDS = 30
SHUTDOWN_SECONDS = 5
OPS = {'http', 'ack', 'cancel', 'audio_open', 'audio_packet', 'audio_close', 'shutdown'}
ID = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
PICKER = re.compile(r'^/api/(?:(?:sessions|courses)/[a-f0-9]{32}/files/select|sessions/[a-f0-9]{32}/recordings)$')


class ProtocolError(ValueError):
    pass


def valid_id(value):
    return isinstance(value, str) and ID.fullmatch(value) is not None


async def read_frame(reader):
    try:
        prefix = await reader.readexactly(4)
    except asyncio.IncompleteReadError as exc:
        if not exc.partial:
            return None
        raise ProtocolError('Truncated frame header') from None
    size = struct.unpack('>I', prefix)[0]
    if not 0 < size <= MAX_HEADER:
        raise ProtocolError('Invalid header length')
    try:
        header = json.loads(await reader.readexactly(size))
        if not isinstance(header, dict) or type(header.get('version')) is not int or header['version'] != 1:
            raise ProtocolError('Invalid protocol version')
        if not valid_id(header.get('id')) or not isinstance(header.get('op'), str) or header['op'] not in OPS:
            raise ProtocolError('Invalid request identity or operation')
        length = header.get('body_length')
        limit = MAX_BODY if header['op'] == 'http' else MAX_CHUNK if header['op'] == 'audio_packet' else 0
        if type(length) is not int or not 0 <= length <= limit:
            raise ProtocolError('Invalid body length')
        return header, await reader.readexactly(length)
    except (asyncio.IncompleteReadError, UnicodeError, json.JSONDecodeError, RecursionError):
        raise ProtocolError('Truncated or invalid frame') from None


class Worker:
    def __init__(self, app, writer):
        self.app = app
        self.writer = writer
        self.write_lock = asyncio.Lock()
        self.requests = {}
        self.acks = {}
        self.audio = {}
        self.closing = False

    async def send(self, ident, event, body=b'', **fields):
        header = json.dumps(dict(version=1, id=ident, event=event, body_length=len(body), **fields), ensure_ascii=False, separators=(',', ':')).encode()
        if len(header) > MAX_HEADER or len(body) > MAX_CHUNK:
            raise ProtocolError('Response exceeds frame limit')
        async with self.write_lock:
            self.writer.write(struct.pack('>I', len(header)) + header + body)
            await self.writer.drain()

    async def error(self, ident, message, code='invalid_request'):
        await self.send(ident, 'error', code=code, message=message)

    def scope(self, kind, path, headers=()):
        config = self.app.state.config
        origin = f'http://127.0.0.1:{config.port}'
        return dict(type=kind, asgi={'version': '3.0', 'spec_version': '2.4'}, scheme='ws' if kind == 'websocket' else 'http', http_version='1.1', path=path, raw_path=path.encode(), root_path='', query_string=b'', client=('127.0.0.1', 0), server=('127.0.0.1', config.port), headers=[(b'host', origin[7:].encode()), (b'origin', origin.encode()), (b'cookie', f'{self.app.state.cookie_name}={self.app.state.cookie}'.encode()), (b'x-session-token', self.app.state.csrf.encode()), *headers])

    async def http(self, header, body):
        ident = header['id']
        path = header.get('path')
        method = header.get('method')
        supplied = header.get('headers', {})
        if not isinstance(path, str) or len(path) > 8192 or not isinstance(method, str) or method not in {'GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE'}:
            raise ProtocolError('Invalid method or path')
        parsed = urlsplit(path)
        decoded = unquote(parsed.path)
        if parsed.scheme or parsed.netloc or parsed.fragment or not decoded.startswith('/api/') or '\\' in decoded or any(ord(char) < 32 for char in path + decoded) or any(part in ('.', '..') for part in decoded.split('/')) or decoded in ('/api/bootstrap', '/api/client'):
            raise ProtocolError('Only application API paths are accepted')
        if not isinstance(supplied, dict) or len(supplied) > 8:
            raise ProtocolError('Invalid request headers')
        headers = []
        for key, value in supplied.items():
            if not isinstance(key, str) or key.lower() not in {'accept', 'content-type', 'range', 'if-range'} or not isinstance(value, str) or len(value) > 4096 or '\r' in value or '\n' in value:
                raise ProtocolError('Request header is not allowed')
            try:
                headers.append((key.lower().encode('ascii'), value.encode('latin-1')))
            except UnicodeError:
                raise ProtocolError('Invalid request header encoding') from None
        if body and not any(key == b'content-type' for key, _ in headers):
            headers.append((b'content-type', b'application/json'))
        headers.append((b'content-length', str(len(body)).encode()))
        scope = self.scope('http', decoded, headers)
        scope.update(method=method, raw_path=parsed.path.encode(), query_string=parsed.query.encode())
        if 'native_selected_files' in header:
            selected = header['native_selected_files']
            if method != 'POST' or not PICKER.fullmatch(decoded) or not isinstance(selected, list) or len(selected) > 64 or any(not isinstance(path, str) or not 0 < len(path) <= 4096 or '\x00' in path or not Path(path).is_absolute() for path in selected):
                raise ProtocolError('Invalid native file selection')
            scope['native_selected_files'] = selected
        elif method == 'POST' and PICKER.fullmatch(decoded):
            raise ProtocolError('Native file selection is required')
        delivered = False
        disconnect = asyncio.Event()
        sequence = 0

        async def receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': body, 'more_body': False}
            await disconnect.wait()
            return {'type': 'http.disconnect'}

        async def send(message):
            nonlocal sequence
            if message['type'] == 'http.response.start':
                response_headers = [[key.decode('latin-1'), value.decode('latin-1')] for key, value in message.get('headers', []) if key.lower() not in (b'set-cookie', b'x-session-token')]
                await self.send(ident, 'response_start', status=message['status'], headers=response_headers)
            elif message['type'] == 'http.response.body':
                data = b'' if method=='HEAD' else message.get('body', b'')
                for offset in range(0, len(data), MAX_CHUNK):
                    acknowledgement = asyncio.get_running_loop().create_future()
                    self.acks[ident] = sequence, acknowledgement
                    await self.send(ident, 'body', data[offset:offset+MAX_CHUNK], sequence=sequence)
                    await asyncio.wait_for(acknowledgement, ACK_SECONDS)
                    self.acks.pop(ident, None)
                    sequence += 1
            else:
                raise ProtocolError('Unsupported ASGI response')

        try:
            await self.app(scope, receive, send)
            await self.send(ident, 'complete')
        finally:
            self.acks.pop(ident, None)
            disconnect.set()

    async def audio_open(self, header, body):
        ident = header['id']
        sid, rid, rate = header.get('session_id'), header.get('recording_id'), header.get('sample_rate')
        if not all(isinstance(value, str) and re.fullmatch(r'[a-f0-9]{32}', value) for value in (sid, rid)) or type(rate) is not int or not 8000 <= rate <= 192000:
            raise ProtocolError('Invalid recording identity or sample rate')
        stream = AudioStream(self, ident, sid, rid, rate)
        self.audio[ident] = stream
        stream.task = asyncio.create_task(stream.run())
        await stream.reply(ident)

    async def audio_packet(self, header, body):
        if not valid_id(header.get('stream_id')):
            raise ProtocolError('Invalid recording stream ID')
        stream = self.audio.get(header['stream_id'])
        if stream is None or stream.task.done():
            raise ProtocolError('Recording stream is closed')
        if stream.pending is not None:
            raise ProtocolError('Wait for the previous saved audio ACK')
        stream.pending = asyncio.get_running_loop().create_future()
        stream.incoming.put_nowait({'type': 'websocket.receive', 'bytes': body})
        await stream.reply(header['id'])

    async def audio_close(self, header, body):
        if not valid_id(header.get('stream_id')):
            raise ProtocolError('Invalid recording stream ID')
        stream = self.audio.get(header['stream_id'])
        if stream is None:
            raise ProtocolError('Recording stream is closed')
        if stream.pending is not None:
            raise ProtocolError('Wait for the previous saved audio ACK')
        stream.task.cancel()
        await asyncio.gather(stream.task, return_exceptions=True)
        await self.send(header['id'], 'complete')

    async def run_request(self, header, body):
        ident = header['id']
        try:
            await getattr(self, header['op'])(header, body)
        except asyncio.CancelledError:
            stream = self.audio.get(ident if header['op'] == 'audio_open' else header.get('stream_id', ''))
            if stream:
                stream.task.cancel()
                await asyncio.gather(stream.task, return_exceptions=True)
            if not self.closing:
                await self.error(ident, 'Request cancelled', 'cancelled')
            raise
        except ProtocolError as exc:
            await self.error(ident, str(exc))
        except TimeoutError:
            await self.error(ident, 'Response acknowledgement timed out', 'timeout')
        except Exception:
            logging.exception('Native request failed')
            await self.error(ident, 'Application request failed', 'internal_error')
        finally:
            self.requests.pop(ident, None)

    async def dispatch(self, header, body):
        ident, op = header['id'], header['op']
        if ident in self.requests or ident in self.audio:
            raise ProtocolError('Request ID is already active')
        if op in ('ack', 'cancel') and not valid_id(header.get('target')):
            await self.error(ident, 'Invalid request target')
            return
        if op == 'ack':
            pending = self.acks.get(header.get('target'))
            if pending is None or type(header.get('sequence')) is not int or pending[0] != header['sequence'] or pending[1].done():
                await self.error(ident, 'Unexpected response acknowledgement')
            else:
                pending[1].set_result(None)
            return
        if op == 'cancel':
            target = self.requests.get(header.get('target'))
            if target:
                target.cancel()
            stream = self.audio.get(header['target'])
            if stream:
                stream.task.cancel()
            await self.send(ident, 'complete')
            return
        if len(self.requests) + len(self.audio) >= MAX_REQUESTS:
            await self.error(ident, 'Too many pending requests', 'busy')
            return
        self.requests[ident] = asyncio.create_task(self.run_request(header, body))

    async def close(self):
        self.closing = True
        tasks = list(self.requests.values()) + [stream.task for stream in self.audio.values()]
        for task in tasks:
            task.cancel()
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=SHUTDOWN_SECONDS)
            if pending:
                raise TimeoutError('Application tasks did not stop')


class AudioStream:
    def __init__(self, worker, ident, sid, rid, rate):
        self.worker, self.ident = worker, ident
        self.scope = worker.scope('websocket', f'/api/sessions/{sid}/audio')
        self.scope['subprotocols'] = []
        self.incoming = asyncio.Queue(maxsize=2)
        self.incoming.put_nowait({'type': 'websocket.connect'})
        self.incoming.put_nowait({'type': 'websocket.receive', 'text': json.dumps(dict(recording_id=rid, sample_rate=rate, channels=1, format='pcm_s16le', csrf_token=worker.app.state.csrf))})
        self.pending = asyncio.get_running_loop().create_future()
        self.task = None

    async def reply(self, ident):
        pending = self.pending
        try:
            payload = await pending
            if payload.get('type') == 'error':
                await self.worker.send(ident, 'error', code='audio_error', message=payload.get('error', 'Recording failed'), payload=payload)
            else:
                await self.worker.send(ident, 'complete', payload=payload)
        finally:
            if self.pending is pending:
                self.pending = None

    async def run(self):
        async def send(message):
            if message['type'] == 'websocket.send':
                payload = json.loads(message['text'])
                if self.pending and not self.pending.done():
                    self.pending.set_result(payload)
                else:
                    await self.worker.send(self.ident, 'audio_event', payload=payload)
            elif message['type'] == 'websocket.close' and self.pending and not self.pending.done():
                self.pending.set_result({'type': 'error', 'error': 'Recording connection rejected'})
        try:
            await self.worker.app(self.scope, self.incoming.get, send)
        except Exception:
            logging.exception('Native recording stream failed')
        finally:
            if self.pending and not self.pending.done():
                self.pending.set_result({'type': 'error', 'error': 'Recording stream closed'})
            self.worker.audio.pop(self.ident, None)


async def serve(config, reader, writer, *, on_shutdown=None):
    if not config.embedded:
        raise ValueError('Native worker requires embedded application mode')
    app = create_app(config)
    worker = Worker(app, writer)
    shutdown_id = None
    async with app.router.lifespan_context(app):
        try:
            await worker.send('worker', 'ready',process_group=os.getpgrp() if os.name=='posix' else None)
            while (item := await read_frame(reader)) is not None:
                header, body = item
                if header['op'] == 'shutdown':
                    if header['id'] in worker.requests or header['id'] in worker.audio:
                        raise ProtocolError('Request ID is already active')
                    shutdown_id = header['id']
                    break
                await worker.dispatch(header, body)
        finally:
            if on_shutdown:
                on_shutdown()
            await worker.close()
    if shutdown_id:
        await worker.send(shutdown_id, 'complete')


async def stdio(config, output, on_shutdown):
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer)
    transport, protocol = await loop.connect_write_pipe(asyncio.streams.FlowControlMixin, output)
    writer = asyncio.StreamWriter(transport, protocol, None, loop)
    task = asyncio.current_task()
    owner = native_owner()
    owner_task = asyncio.create_task(watch_owner(owner)) if owner else None

    def terminate():
        on_shutdown()
        task.cancel()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, terminate)
    try:
        await serve(config, reader, writer, on_shutdown=on_shutdown)
    finally:
        writer.close()
        if owner_task:
            owner_task.cancel()
            await asyncio.gather(owner_task, return_exceptions=True)
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(sig)


def main():
    parser = argparse.ArgumentParser(description='Solasi internal application worker')
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--runtime-dir', type=Path, required=True)
    args = parser.parse_args()
    if os.name=='posix' and os.getpgrp()!=os.getpid():os.setpgid(0,0)
    # Keep all Python/library print output off the framed protocol descriptor.
    output = os.fdopen(os.dup(sys.stdout.fileno()), 'wb', buffering=0)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    # Threaded file/OS calls cannot always be cancelled; crash recovery covers this deadline.
    deadline = threading.Timer(SHUTDOWN_SECONDS + 1, os._exit, args=(2,))
    deadline.daemon = True
    shutting_down = False
    def begin_shutdown():
        nonlocal shutting_down
        if not shutting_down:
            shutting_down = True
            deadline.start()
    try:
        asyncio.run(stdio(AppConfig(args.data_dir, args.runtime_dir, embedded=True), output, begin_shutdown))
    except asyncio.CancelledError:
        pass
    except (ProtocolError, OSError, ValueError, TimeoutError) as exc:
        print(f'Native worker stopped: {exc}', file=sys.stderr)
        raise SystemExit(2) from None
    finally:
        deadline.cancel()
        output.close()


if __name__ == '__main__':
    main()
