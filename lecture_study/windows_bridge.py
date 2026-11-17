"""Listener-free Windows transport; the application and SQLite own one asyncio thread."""
import asyncio
from concurrent.futures import Future
from dataclasses import dataclass
import json
import math
import mimetypes
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
from urllib.parse import parse_qsl, unquote, urlsplit
import uuid

from .native_worker import Worker, MAX_BODY, MAX_REQUESTS, ProtocolError, PICKER, valid_id

ORIGIN='https://solasi.invalid'
RESOURCE=re.compile(r'^/api/(assets/[a-f0-9]{32}/(original|pages/[1-9][0-9]*|images/[A-Za-z0-9_.-]+)|recordings/[a-f0-9]{32}/audio|sessions/[a-f0-9]{32}/transcripts/export|artifacts/[a-f0-9]{32}/export)$')
# pywebview's Promise reply wrapper uses eval; external code and frames remain forbidden.
CSP="default-src 'self'; script-src 'self' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; media-src 'self' blob:; object-src 'none'; frame-src 'none'; base-uri 'none'"


def trusted_url(url):
    return url in (ORIGIN+'/',ORIGIN+'/index.html')


def audio_link(url,vault):
    if not isinstance(url,str) or len(url)>8192 or any(ord(c)<32 for c in url):raise ValueError('원음 링크를 확인하세요')
    parts=urlsplit(url);path=parts.path.split('/');query=parse_qsl(parts.query,keep_blank_values=True)
    if parts.scheme!='solasi' or parts.netloc!='audio' or parts.fragment or len(path)!=3 or path[0] or path[1]!=vault or not re.fullmatch('[a-f0-9]{32}',path[2]) or len(query)!=2 or set(k for k,v in query)!={'start_ms','end_ms'}:
        raise ValueError('이 보관함에 연결된 원음 링크가 아닙니다')
    values=dict(query)
    try:start,end=float(values['start_ms']),float(values['end_ms'])
    except ValueError:raise ValueError('원음 재생 구간을 확인하세요') from None
    if not math.isfinite(start) or not math.isfinite(end) or start<0 or end<=start:raise ValueError('원음 재생 구간을 확인하세요')
    return {'url':'/api/recordings/'+path[2]+'/audio','start':start/1000,'end':end/1000}


def resource_path(url):
    if not isinstance(url,str) or any(ord(c)<32 for c in url):raise ValueError('자료 경로를 확인하세요')
    parts=urlsplit(url)
    if parts.scheme!='https' or parts.netloc!='solasi.invalid' or parts.fragment or len(url)>8192:
        raise ValueError('허용하지 않은 앱 자료 주소입니다')
    path=unquote(parts.path)
    if not path.startswith('/') or '\\' in path or any(ord(c)<32 for c in path) or any(p in ('.','..') for p in path.split('/')):
        raise ValueError('자료 경로를 확인하세요')
    if path.startswith('/api/') and not RESOURCE.fullmatch(path):raise ValueError('허용하지 않은 자료 요청입니다')
    return parts.path+('?' + parts.query if parts.query else '')


def byte_range(header,size):
    if header is None:return 0,size
    match=re.fullmatch(r'bytes=(\d*)-(\d*)',header)
    if not match or size<=0:raise ValueError('잘못된 재생 범위입니다')
    first,last=match.groups()
    if not first:
        if not last or int(last)<=0:raise ValueError('잘못된 재생 범위입니다')
        return max(0,size-int(last)),size
    start=int(first);end=min(size,int(last)+1) if last else size
    if not 0<=start<end<=size:raise ValueError('잘못된 재생 범위입니다')
    return start,end


@dataclass
class Response:
    status:int=200
    headers:list=None

    def __post_init__(self):
        self.headers=[] if self.headers is None else self.headers
        self.body=tempfile.NamedTemporaryFile(prefix='solasi-response-',delete=False)
        self.path=Path(self.body.name)

    def close(self):
        self.body.close();self.path.unlink(missing_ok=True)

    def __enter__(self):return self
    def __exit__(self,*_):self.close()


def static_response(root,path,method,headers):
    if method not in ('GET','HEAD'):raise ValueError('허용하지 않은 자료 요청입니다')
    root=Path(root).resolve();relative=unquote(urlsplit(path).path).lstrip('/') or 'index.html'
    file=(root/relative).resolve()
    if not file.is_relative_to(root) or not file.is_file():raise ValueError('앱 화면 파일이 없습니다')
    size=file.stat().st_size;start,end=byte_range(headers.get('range'),size)
    mime=mimetypes.guess_type(file.name)[0] or 'application/octet-stream'
    fields=[('Content-Type',mime),('Content-Length',str(end-start)),('Accept-Ranges','bytes'),('X-Content-Type-Options','nosniff')]
    if file.suffix=='.html':fields.append(('Content-Security-Policy',CSP))
    if 'range' in headers:fields.append(('Content-Range',f'bytes {start}-{end-1}/{size}'))
    response=Response(206 if 'range' in headers else 200,fields)
    try:
        if method!='HEAD':
            with file.open('rb') as source:
                source.seek(start);remaining=end-start
                while remaining:
                    chunk=source.read(min(256*1024,remaining))
                    if not chunk:raise OSError('앱 파일을 끝까지 읽지 못했습니다')
                    response.body.write(chunk);remaining-=len(chunk)
        response.body.flush();response.body.seek(0);return response
    except BaseException:response.close();raise


def publish_export(staging,destination):
    try:
        # Windows rename refuses to replace, and works on USB filesystems without hardlinks.
        if sys.platform=='win32':os.rename(staging,destination)
        else:os.link(staging,destination);staging.unlink()
    except OSError:raise ValueError('기존 파일은 보존했습니다. 내보낸 사본: '+str(staging)) from None


def export_text(destination,text):
    destination=Path(destination)
    with tempfile.NamedTemporaryFile(prefix='.solasi-export-',dir=destination.parent,delete=False) as output:
        staging=Path(output.name)
        try:output.write(text.encode('utf-8'));output.flush();os.fsync(output.fileno())
        except BaseException:
            raise ValueError('내보내기 실패 · 일부만 저장된 사본: '+str(staging)) from None
    publish_export(staging,destination)


class InProcessWorker(Worker):
    def __init__(self,app):
        super().__init__(app,None);self.sinks={}

    async def send(self,ident,event,body=b'',**fields):
        sink=self.sinks.get(ident)
        if sink:sink(event,body,fields)
        if event=='body':
            pending=self.acks.get(ident)
            if pending and not pending[1].done():pending[1].set_result(None)


class Engine:
    def __init__(self,config,*,app_factory=None,response_factory=Response):
        if not config.embedded:raise ValueError('Windows 앱은 내장 실행 모드가 필요합니다')
        self.config=config;self.ready=Future();self.captures={};self.stopped=False
        self.app_factory=app_factory;self.response_factory=response_factory
        self.thread=threading.Thread(target=self._run,name='Solasi.application',daemon=True)

    def start(self):
        self.thread.start();self.ready.result(30)

    def _run(self):
        try:asyncio.run(self._main())
        except BaseException as error:
            if not self.ready.done():self.ready.set_exception(error)
            else:
                import logging
                logging.exception('Windows application stopped')

    async def _main(self):
        from .server import create_app
        self.loop=asyncio.get_running_loop();self.stop_event=asyncio.Event()
        self.app=(self.app_factory or create_app)(self.config);self.worker=InProcessWorker(self.app)
        async with self.app.router.lifespan_context(self.app):
            self.ready.set_result(True)
            try:await self.stop_event.wait()
            finally:await self.worker.close()

    def submit(self,operation):
        if self.stopped:operation.close();raise ValueError('앱이 종료 중입니다')
        return asyncio.run_coroutine_threadsafe(operation,self.loop)

    async def http(self,path,method='GET',body=b'',headers=None,ident=None,selected=None):
        ident=ident or uuid.uuid4().hex
        if not valid_id(ident) or len(body)>MAX_BODY or ident in self.worker.requests or len(self.worker.requests)>=MAX_REQUESTS:
            raise ValueError('요청 식별자·크기·동시 실행 수를 확인하세요')
        response=self.response_factory()
        def receive(event,chunk,fields):
            if event=='response_start':response.status=fields['status'];response.headers=fields['headers']
            elif event=='body':response.body.write(chunk)
            elif event=='error':raise ValueError(fields.get('message','앱 요청 실패'))
        self.worker.sinks[ident]=receive;self.worker.requests[ident]=asyncio.current_task()
        header={'id':ident,'method':method,'path':path,'headers':headers or {}}
        if selected is not None:header['native_selected_files']=selected
        try:
            await self.worker.http(header,body)
            response.body.flush();response.body.seek(0);return response
        except BaseException:response.close();raise
        finally:self.worker.sinks.pop(ident,None);self.worker.requests.pop(ident,None)

    async def json(self,path,body=None,method='POST'):
        with await self.http(path,method,json.dumps(body).encode() if body is not None else b'') as response:
            result=json.load(response.body) if response.path.stat().st_size else None
            if not 200<=response.status<300:raise ValueError(result.get('detail','앱 요청 실패') if isinstance(result,dict) else '앱 요청 실패')
            return result

    async def audio_rpc(self,op,body=b'',**fields):
        ident=uuid.uuid4().hex;result={}
        def receive(event,chunk,header):
            if event=='error':raise ValueError(header.get('message','원음 저장 실패'))
            if event=='complete':result.update(header.get('payload',{}))
        self.worker.sinks[ident]=receive
        try:await getattr(self.worker,op)({'id':ident,**fields},body);return result
        finally:self.worker.sinks.pop(ident,None)

    def cancel(self,ident):
        task=self.worker.requests.get(ident)
        if task:task.cancel()

    async def stop_captures(self):
        for capture in list(self.captures.values()):await capture.stop()

    async def original(self,url):
        from .materials import asset_dir,original_path
        from .course_materials import checked_document_path
        from urllib.parse import parse_qs
        path=resource_path(url);parts=urlsplit(path)
        match=re.fullmatch('/api/assets/([a-f0-9]{32})/original',parts.path)
        if not match:raise ValueError('원본 자료 경로를 확인하세요')
        ident=match[1];_,asset=asset_dir(self.app.state.db,ident)
        digest=parse_qs(parts.query).get('document_sha256',[None])[0]
        return checked_document_path(self.app.state.db,ident,digest) if digest else original_path(self.app.state.db,asset)

    async def clip(self,url):
        row=self.app.state.db.execute("SELECT value FROM settings WHERE key='native_vault_id'").fetchone()
        return audio_link(url,row[0])

    def close(self):
        if self.stopped or not self.thread.is_alive():return
        self.submit(self.stop_captures()).result(15)
        self.loop.call_soon_threadsafe(self.stop_event.set)
        self.thread.join(15)
        if self.thread.is_alive():raise TimeoutError('앱 저장 작업의 종료를 확인하지 못했습니다')
        self.stopped=True


class Commands:
    def __init__(self,engine,trusted,select_files,save_file,emit=None):
        self.engine=engine;self.trusted=trusted;self.select_files=select_files;self.save_file=save_file;self.emit=emit or (lambda *_:None)

    def command(self,message):
        if not self.trusted() or not isinstance(message,dict):raise ValueError('허용하지 않은 앱 요청입니다')
        op=message.get('op')
        if op=='ui_ready':return {'ready':True}
        if op=='cancel':
            target=message.get('target')
            if not valid_id(target):raise ValueError('요청 식별자를 확인하세요')
            self.engine.loop.call_soon_threadsafe(self.engine.cancel,target);return {'cancelled':True}
        if op=='export_text':
            filename,text=message.get('filename'),message.get('text')
            if not isinstance(filename,str) or len(filename.encode())>=256 or Path(filename).name!=filename or not isinstance(text,str) or len(text.encode())>64*1024*1024:
                raise ValueError('내보낼 파일을 확인하세요')
            target=self.save_file(filename)
            if not target:return {'cancelled':True}
            export_text(target,text);return {'saved':True}
        if op in ('audio_start','audio_stop'):
            return self.engine.submit(self._audio(message)).result(20)
        if op!='http' or 'native_selected_files' in message:raise ValueError('허용하지 않은 앱 작업입니다')
        ident=message.get('id');path=message.get('path');method=message.get('method')
        if not isinstance(ident,str):raise ValueError('요청 식별자가 없습니다')
        try:uuid.UUID(ident)
        except ValueError:raise ValueError('요청 식별자를 확인하세요') from None
        if not isinstance(path,str) or not isinstance(method,str) or not isinstance(message.get('body',''),str):raise ValueError('앱 요청 형식을 확인하세요')
        selected=None
        if method=='POST' and PICKER.fullmatch(unquote(urlsplit(path).path)):
            selected=list(self.select_files(path) or [])
        body=message.get('body','').encode()
        with self.engine.submit(self.engine.http(path,method,body,ident=ident,selected=selected)).result(120) as response:
            if response.path.stat().st_size>MAX_BODY:raise ValueError('앱 응답 크기를 초과했습니다')
            return {'status':response.status,'text':response.body.read().decode('utf-8')}

    async def _audio(self,message):
        from .windows_audio import Capture
        ident=message.get('capture_id')
        try:uuid.UUID(ident)
        except (ValueError,TypeError,AttributeError):raise ValueError('녹음 식별자를 확인하세요') from None
        if message['op']=='audio_stop':
            capture=self.engine.captures.get(ident)
            if capture:await capture.stop(interrupted=message.get('interrupted',False) is True)
            return {'stopped':True}
        sid=message.get('session_id');mode=message.get('transcription_mode')
        if not isinstance(sid,str) or not re.fullmatch('[a-f0-9]{32}',sid) or mode not in ('realtime','after_stop') or self.engine.captures:
            raise ValueError('녹음 대상·방식·진행 상태를 확인하세요')
        capture=Capture(ident,sid,mode,self.engine,self.emit)
        self.engine.captures[ident]=capture
        try:await capture.start()
        except BaseException:self.engine.captures.pop(ident,None);raise
        return {'accepted':True}
