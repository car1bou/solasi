import secrets
import logging
import time
import threading
import weakref
import asyncio
import json
import struct
import hashlib
import importlib.util
import httpx
from typing import Literal
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse,PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from .config import AppConfig,acquire_data_lock
from .process_owner import native_owner,watch_owner
from .runtime import probe_runtime,prepare_runtime,component_status
from .db import open_db, now, new_id, create_session, session,course
from .models import CourseInput, SessionInput, Input,OwnerInput,PageDocumentInput
from .course_materials import list_course_materials,linked_asset,document_metadata,page_document,save_page_document,checked_document_path
from .file_access import select_files
from .materials import render_image, prune_cache, inspect_file, register_file, public_asset, original_path, ingest_asset, render_page, asset_dir, save_note, list_materials
from .jobs import submit_job, get_job, launch_job,wait_for_transcription
from .lifecycle import delete_session,delete_audio,resolve_source,playable_path,cleanup_files
from .models import SourceRef,Scope,ProviderConfig
from .providers import model_status,local_url
from .credentials import Secrets
from .local_models import OwnedOllama,catalog,installed_models
from .direct_models import DirectModels,DirectEmbeddings
from .answers import freeze_request,run_ai_request,get_artifact,capture_request,checked_evidence
from .outputs import cached_summary_parts,public_artifact,submit_attempt,save_attempt,grade_attempt,quiz_question,override_attempt,review_attempts,related_quizzes,list_participants,save_participants,edit_artifact,export_markdown
from .models import AIRequest
from .retrieval import backfill_sources,retrieve,list_terms,save_term,concept_detail,rebuild_embeddings,index_status,capture_search
from .transcription import plan_chunks,process_chunk,list_transcripts,transcription_status,register_audio,edit_segment,edit_segments,export_transcript,TranscriptConflict,get_asr_terms,save_asr_terms,asr_prompt,engine_paths,verify_model,MODEL_NAME,VAD_SHA
from .asr_review import queue_review,process_review,apply_review,public_reviews,empty_ranges,unchanged
from .audio import start_recording, append_pcm, stop_recording, get_recording, interrupt_recording, recover_recordings
from .native_drafts import attach_native_drafts

AUDIO_IDLE_SECONDS=15
AUDIO_RELEASE_SECONDS=30

def token_matches(value,expected):
    return isinstance(value,str) and secrets.compare_digest(value.encode('utf-8'),expected.encode('utf-8'))

def create_app(config: AppConfig) -> FastAPI:
    owner=None if config.embedded else native_owner()
    instance=acquire_data_lock(config.data_dir)
    try:
        db = open_db(config.data_dir)
        for row in db.execute('SELECT id FROM sessions WHERE deleted=1').fetchall(): delete_session(db,row['id'],True)
        cleanup_files(db)
        recover_recordings(db)
        backfill_sources(db)
    except BaseException:
        instance.close();raise

    @asynccontextmanager
    async def lifespan(app):
        owner_task=asyncio.create_task(watch_owner(owner)) if owner else None
        try:
            saved=db.execute("SELECT value FROM settings WHERE key='local_connection'").fetchone()
            if saved and not config.embedded:
                choice=json.loads(saved[0])
                try:
                    url=await app.state.local_models.start() if choice['mode']=='managed' else local_url(choice['url'])
                    await installed_models(url);app.state.ollama_url=url
                except ValueError as exc: app.state.local_error=str(exc)
            for saved in db.execute("SELECT id FROM recordings WHERE transcription_mode='after_stop' AND status!='recording' AND (transcription_released=0 OR stop_job_id IN (SELECT id FROM jobs WHERE status='interrupted'))").fetchall():
                try:release_capture(saved['id'])
                except (KeyError,OSError,ValueError) as exc:
                    with db:db.execute('UPDATE recordings SET error=? WHERE id=?',(str(exc)[:300],saved['id']))
            yield
        finally:
            app.state.closing=True
            try:
                if owner_task:
                    owner_task.cancel()
                    await asyncio.gather(owner_task,return_exceptions=True)
                for task in list(app.state.tasks):
                    task.cancel()
                await asyncio.gather(*app.state.tasks,return_exceptions=True)
                await app.state.local_models.stop()
                await app.state.direct_models.stop()
                app.state.secrets.memory.clear()
            finally:db.close();instance.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.instance_lock=instance
    weakref.finalize(app,instance.close)
    app.state.closing=False
    app.state.tasks = set()
    app.state.job_tasks = {}
    app.state.runtime_lock=asyncio.Lock()
    app.state.parse_lock = asyncio.Semaphore(1)
    app.state.file_selection = asyncio.Lock()
    app.state.transcription_task = None
    app.state.audio_sockets = {}
    app.state.audio_starts = {}
    app.state.audio_releases = {}
    app.state.active_transcription = None
    app.state.active_asr = None
    app.state.ollama_url = None
    app.state.local_error = None
    app.state.local_models = OwnedOllama(config.runtime_dir)
    app.state.direct_models = DirectModels(config.runtime_dir,config.data_dir/'model-cache')
    app.state.secrets = Secrets("LectureStudy:"+hashlib.sha256(str(config.data_dir.resolve()).encode()).hexdigest()[:16])
    app.state.generation_lock = asyncio.Semaphore(1)
    app.state.external_generation_lock = asyncio.Semaphore(1)
    app.state.embedding_lock = asyncio.Semaphore(1)
    app.state.active_embedding_clients=0
    with db:
        db.execute("UPDATE embedding_sets SET status='failed' WHERE status='building'")
        db.execute("UPDATE attempts SET status='interrupted',error='앱 실행이 중단되었습니다' WHERE status='grading'")
        db.execute("UPDATE ai_attempts SET status='interrupted',error='앱 실행이 중단되었습니다' WHERE status='running'")
        db.execute("UPDATE jobs SET status='interrupted',error='앱 실행이 중단되었습니다' WHERE status IN ('queued','running')")
        db.execute("UPDATE transcript_ranges SET status='interrupted',error='전사가 중단되었습니다' WHERE status IN ('queued','running')")
        db.execute("UPDATE assets SET status='failed',error='추출이 중단되었습니다' WHERE status IN ('queued','running')")
    app.state.config = config
    app.state.db = db
    if config.embedded: attach_native_drafts(app, db)
    app.state.bootstrap_token = secrets.token_urlsafe(32)
    app.state.bootstrap_used = False
    app.state.cookie_name='lecture_session_'+str(config.port)
    app.state.cookie = secrets.token_urlsafe(32)
    app.state.csrf = secrets.token_urlsafe(32)
    origins = {f"http://127.0.0.1:{config.port}", f"http://localhost:{config.port}"}
    hosts = {f"127.0.0.1:{config.port}", f"localhost:{config.port}"}

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.headers.get("host") not in hosts or (origin and origin not in origins):
            return JSONResponse({"detail": "로컬 앱에서만 접근할 수 있습니다"}, status_code=403)
        if request.url.path.startswith("/api/") and request.url.path not in ("/api/health", "/api/bootstrap"):
            if not token_matches(request.cookies.get(app.state.cookie_name, ""), app.state.cookie):
                return JSONResponse({"detail": "앱 실행 링크에서 연결하세요"}, status_code=403)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if origin not in origins:
                return JSONResponse({"detail": "요청 origin을 확인할 수 없습니다"}, status_code=403)
            if request.url.path != "/api/bootstrap" and not token_matches(request.headers.get("x-session-token", ""), app.state.csrf):
                return JSONResponse({"detail": "요청 토큰이 유효하지 않습니다"}, status_code=403)
        if request.method=='PUT' and '/pages/' in request.url.path and request.url.path.endswith('/document'):
            body=bytearray()
            async for chunk in request.stream():
                if len(body)+len(chunk)>10*1024*1024:return JSONResponse({'detail':'페이지 문서는 10 MiB까지 전송할 수 있습니다'},status_code=413)
                body.extend(chunk)
            request._body=bytes(body)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = f"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' ws://127.0.0.1:{config.port} ws://localhost:{config.port}; media-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request,exc):
        return JSONResponse({'detail':'입력 정보를 확인하세요'},status_code=422)

    @app.exception_handler(KeyError)
    async def not_found(request, exc):
        return JSONResponse({"detail": str(exc.args[0])}, status_code=404)

    @app.exception_handler(ValueError)
    async def bad_input(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(TranscriptConflict)
    async def transcript_conflict(request,exc):
        return JSONResponse({'detail':str(exc)},status_code=409)

    @app.exception_handler(OSError)
    async def inaccessible_file(request,exc):
        return JSONResponse({"detail":"파일을 읽을 수 없습니다. 위치와 접근 권한을 확인하세요"},status_code=409)

    @app.get("/api/health")
    async def health():
        return {"ready": True}

    class Bootstrap(BaseModel):
        token: str

    @app.post("/api/bootstrap")
    async def bootstrap(body: Bootstrap):
        if app.state.bootstrap_used or not token_matches(body.token, app.state.bootstrap_token):
            return JSONResponse({"detail": "실행 링크가 만료되었습니다"}, status_code=403)
        app.state.bootstrap_used = True
        response = JSONResponse({"csrf_token": app.state.csrf})
        response.set_cookie(app.state.cookie_name, app.state.cookie, httponly=True, samesite="strict", path="/")
        return response

    @app.get("/api/client")
    async def client_state():
        return {"csrf_token": app.state.csrf}

    @app.get("/api/runtime/status")
    async def runtime_status():
        try:
            await asyncio.to_thread(engine_paths,config.runtime_dir)
            await asyncio.to_thread(verify_model,config.runtime_dir/"models/ggml-silero-v6.2.0.bin",VAD_SHA)
            asr_ready=True
        except (OSError,ValueError): asr_ready=False
        direct=await app.state.direct_models.available() if config.embedded else None
        return [
            {"label": "기록 저장", "ready": True},
            {"label": "PDF·이미지 추출", "ready": importlib.util.find_spec("liteparse") is not None},
            {"label": "전사 · Whisper "+MODEL_NAME, "ready": asr_ready},
            {"label": "로컬 모델 연결", "ready": direct["connected"] if direct else app.state.ollama_url is not None},
        ]

    @app.get('/api/runtime/details')
    async def runtime_details():
        result=await asyncio.to_thread(probe_runtime,config)
        latest=db.execute("SELECT id FROM jobs WHERE kind='runtime' ORDER BY created_at DESC LIMIT 1").fetchone()
        return result|{'job':get_job(db,latest[0]) if latest else None}

    class RuntimeInput(Input):
        component:str
        confirmed:bool=Field(strict=True)

    def launch_runtime(job):
        async def operation():
            async with app.state.runtime_lock:
                loop=asyncio.get_running_loop();cancel=threading.Event()
                def update(progress):
                    def write():
                        with db:db.execute('UPDATE jobs SET result=?,updated_at=? WHERE id=?',(json.dumps(progress),now(),job['id']))
                    loop.call_soon_threadsafe(write)
                future=loop.run_in_executor(None,prepare_runtime,job['request']['component'],config.runtime_dir,update,cancel)
                try:return await asyncio.shield(future)
                except asyncio.CancelledError:
                    cancel.set()
                    try:await asyncio.shield(future)
                    except (InterruptedError,ValueError,OSError):pass
                    raise
        return launch_job(app,job,operation)

    @app.post('/api/runtime/prepare',status_code=202)
    async def prepare(body:RuntimeInput):
        if not body.confirmed:raise ValueError('용량·라이선스·저장 위치를 확인하고 준비를 선택하세요')
        if config.embedded and body.component=='ollama':raise ValueError('앱 내부 엔진을 사용합니다')
        if body.component not in ('asr','ocr','ollama'):raise ValueError('준비할 엔진을 선택하세요')
        if db.execute("SELECT 1 FROM recordings WHERE status='recording'").fetchone() or app.state.active_transcription or db.execute("SELECT 1 FROM jobs WHERE kind IN ('parse','ai') AND status IN ('queued','running')").fetchone():raise ValueError('녹음·자료 처리·생성 완료 후 엔진을 준비하세요')
        if body.component=='ollama' and app.state.local_models.process and app.state.local_models.process.returncode is None:raise ValueError('앱 엔진 연결을 종료한 후 준비하세요')
        if db.execute("SELECT 1 FROM jobs WHERE kind='runtime' AND status IN ('queued','running')").fetchone():raise ValueError('런타임 준비가 진행 중입니다')
        return launch_runtime(submit_job(db,None,'runtime',body.model_dump()))

    @app.post('/api/local/disconnect')
    async def disconnect_local():
        if config.embedded:
            await app.state.direct_models.stop()
            return {'connected':False}
        await app.state.local_models.stop();app.state.ollama_url=None
        with db:db.execute("DELETE FROM settings WHERE key='local_connection'")
        return {'connected':False}

    def provider_config():
        saved=db.execute("SELECT value FROM settings WHERE key='provider'").fetchone()
        selected=ProviderConfig.model_validate_json(saved[0]) if saved else ProviderConfig()
        return selected.model_copy(update={'provider':'local'}) if config.embedded and selected.provider=='ollama' else selected

    @app.get('/api/settings')
    async def settings():
        return {'provider':provider_config().model_dump(),'credentials':await asyncio.to_thread(app.state.secrets.status),'local_connected':(await app.state.direct_models.available())['connected'] if config.embedded else app.state.ollama_url is not None}

    class ProviderInput(Input):
        provider: str
        model: str
        context_limit: int=8192

    @app.put('/api/settings')
    async def save_settings(body:ProviderInput):
        try: selected=ProviderConfig(**body.model_dump())
        except ValidationError: raise ValueError('제공자·모델·입력 한도를 확인하세요') from None
        if config.embedded and selected.provider=='ollama':selected=selected.model_copy(update={'provider':'local'})
        if selected.provider=='local':await app.state.direct_models.status(selected.model)
        with db: db.execute("INSERT OR REPLACE INTO settings VALUES ('provider',?)",(selected.model_dump_json(),))
        return selected

    class SecretInput(Input):
        value: str=Field(min_length=1,max_length=4096)
        persistent: bool=Field(default=False,strict=True)

    @app.put('/api/credentials/{provider}')
    async def put_credentials(provider:str,body:SecretInput):
        await asyncio.to_thread(app.state.secrets.set_secret,provider,body.value,body.persistent)
        return {'configured':True,'storage':'os' if body.persistent else 'memory'}

    @app.delete('/api/credentials/{provider}')
    async def remove_credentials(provider:str):
        await asyncio.to_thread(app.state.secrets.delete_secret,provider)
        return {'configured':False}

    @app.post('/api/models/check')
    async def check_model():
        selected=provider_config()
        key=await asyncio.to_thread(app.state.secrets.get_secret,selected.provider) if selected.provider not in ('ollama','local') else None
        result=await model_status(selected,secret=key,ollama_url=app.state.ollama_url,direct_models=app.state.direct_models)
        selected=selected.model_copy(update={'vision':result['vision'],'context_limit':result['context_limit']})
        with db: db.execute("INSERT OR REPLACE INTO settings VALUES ('provider',?)",(selected.model_dump_json(),))
        return result

    class LocalInput(Input):
        mode: str=Field(pattern='^(managed|existing)$')
        url: str='http://127.0.0.1:11434'

    @app.get('/api/local/status')
    async def local_status():
        if config.embedded:return await app.state.direct_models.available()
        manager=app.state.local_models
        result={'connected':False,'managed_connected':manager.url is not None and manager.url==app.state.ollama_url,'models':[],'catalog':catalog(),'download':manager.progress,'model_directory':str((config.runtime_dir/'ollama-models').resolve())}
        if app.state.local_error: result['error']=app.state.local_error
        if app.state.ollama_url:
            try: result.update(await installed_models(app.state.ollama_url))
            except ValueError as exc: result['error']=str(exc)
        return result

    @app.post('/api/local/connect')
    async def connect_local(body:LocalInput):
        if config.embedded:
            if body.mode!='managed':raise ValueError('앱 내부 모델을 사용하세요')
            return await app.state.direct_models.available()
        url=await app.state.local_models.start() if body.mode=='managed' else local_url(body.url)
        result=await installed_models(url)
        app.state.ollama_url=url;app.state.local_error=None
        with db: db.execute("INSERT OR REPLACE INTO settings VALUES ('local_connection',?)",(json.dumps(body.model_dump()),))
        return result

    class PullInput(Input):
        model: str
        runner: str
        confirmed: bool=Field(strict=True)

    @app.post('/api/local/pull',status_code=202)
    async def pull_model(body:PullInput):
        if not body.confirmed: raise ValueError('용량·저장 위치·라이선스를 확인하고 다운로드를 선택하세요')
        manager=app.state.direct_models if config.embedded else app.state.local_models
        return manager.begin_pull(body.model,body.runner)

    @app.post('/api/local/pull/cancel')
    async def cancel_pull():
        manager=app.state.direct_models if config.embedded else app.state.local_models
        if manager.pull_task and not manager.pull_task.done():
            manager.pull_task.cancel();await asyncio.gather(manager.pull_task,return_exceptions=True)
        return manager.progress

    @asynccontextmanager
    async def local_embedding_client(job_id=None):
        if config.embedded:
            app.state.active_embedding_clients+=1
            try:yield DirectEmbeddings(app.state.direct_models,lambda:wait_for_transcription(db,job_id))
            finally:
                app.state.active_embedding_clients-=1
                if not app.state.closing and db.execute("SELECT 1 FROM jobs WHERE kind='asr_review' AND status='queued' LIMIT 1").fetchone():kick_transcription()
        elif app.state.ollama_url is None:
            yield None
        else:
            async def before_request(request):
                if request.method=='POST' and request.url.path=='/api/embed':await wait_for_transcription(db,job_id)
            app.state.active_embedding_clients+=1
            try:
                async with httpx.AsyncClient(base_url=app.state.ollama_url,timeout=60,trust_env=False,event_hooks={'request':[before_request]}) as client:
                    yield client
            finally:
                app.state.active_embedding_clients-=1
                if not app.state.closing and db.execute("SELECT 1 FROM jobs WHERE kind='asr_review' AND status='queued' LIMIT 1").fetchone():kick_transcription()

    @asynccontextmanager
    async def generation_slot(provider,job_id):
        if provider in ('ollama','local'):await wait_for_transcription(db,job_id)
        lock=app.state.generation_lock if provider in ('ollama','local') else app.state.external_generation_lock
        try:
            async with lock:
                if provider in ('ollama','local'):await wait_for_transcription(db,job_id)
                yield
        finally:
            if provider in ('ollama','local') and db.execute("SELECT 1 FROM jobs WHERE kind='asr_review' AND status='queued' LIMIT 1").fetchone():kick_transcription()

    class AIInput(OwnerInput):
        kind:str=Field(default='answer')
        prompt:str=Field(min_length=1,max_length=10000)
        scope:Scope
        web:bool=False
        web_query:str|None=Field(default=None,max_length=500)
        image_id:str|None=None
        note_source_id:str|None=None
        anchor_ms:int|None=Field(default=None,ge=0,strict=True)

    def launch_ai(job):
        async def operation():
            if config.embedded and job['request']['request']['provider']['provider']=='ollama':raise ValueError('이전 모델 엔진의 요청입니다. 새 작업으로 실행하세요')
            if 'snapshot' in job['request']:
                request=AIRequest.model_validate(job['request']['request'])
                web_key=await asyncio.to_thread(app.state.secrets.get_secret,'exa') if request.web else None
                async with local_embedding_client(job['id']) as client:
                    frozen=await freeze_request(db,request,client,web_key,snapshot=job['request']['snapshot'],runtime_dir=config.runtime_dir if config.embedded or app.state.local_models.url==app.state.ollama_url else None)
                with db:db.execute('UPDATE jobs SET request=? WHERE id=?',(json.dumps(frozen,ensure_ascii=False),job['id']))
                job['request']=frozen
            async with generation_slot(job['request']['request']['provider']['provider'],job['id']):
                provider=job['request']['request']['provider']['provider']
                key=await asyncio.to_thread(app.state.secrets.get_secret,provider) if provider not in ('ollama','local') else None
                async def before_local():
                    await wait_for_transcription(db,job['id'])
                    checked_evidence(db,job['request'])
                result=await run_ai_request(db,job['request'],job['id'],secret=key,ollama_url=app.state.ollama_url,runtime_dir=config.runtime_dir,before_local=before_local,direct_models=app.state.direct_models)
                return {'id':result.id,'kind':result.kind}
        return launch_job(app,job,operation)

    @app.post('/api/ai/jobs',status_code=202)
    async def ai_job(body:AIInput):
        try: request=AIRequest(**body.model_dump(),provider=provider_config())
        except ValidationError: raise ValueError('생성 요청을 확인하세요') from None
        frozen=await freeze_request(db,request) if request.kind=='vision' else {'request':request.model_dump(),'snapshot':capture_request(db,request)}
        return launch_ai(submit_job(db,body.session_id,'ai',frozen,course_id=body.course_id))

    @app.get('/api/artifacts/{ident}')
    async def artifact(ident:str):
        return public_artifact(db,ident)

    class NoteApply(Input):
        addition:str=Field(min_length=1,max_length=20000)

    @app.post('/api/artifacts/{ident}/apply-note')
    async def apply_note_proposal(ident:str,body:NoteApply):
        from .assistance import apply_note
        return apply_note(db,ident,body.addition)

    def saved_setting(key,default=None):
        row=db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else default

    class CandidateOption(Input):
        enabled:bool=Field(strict=True)

    @app.put('/api/sessions/{sid}/question-candidates/options')
    async def candidate_options(sid:str,body:CandidateOption):
        session(db,sid)
        if body.enabled and provider_config().provider not in ('ollama','local'):raise ValueError('자동 추출은 로컬 모델에서만 켤 수 있습니다')
        with db:db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('candidate_options:'+sid,json.dumps(body.model_dump())))
        return body.model_dump()

    @app.get('/api/sessions/{sid}/question-cards')
    async def get_question_cards(sid:str):
        from .assistance import question_cards
        last=saved_setting('candidate_last:'+sid,{})
        try:job=get_job(db,last['job_id']) if last.get('job_id') else None
        except KeyError:job=None
        return {'cards':question_cards(db,sid),'options':saved_setting('candidate_options:'+sid,{'enabled':False}),'local':provider_config().provider in ('ollama','local'),'job':job}

    class CandidateRun(Input):
        automatic:bool=Field(default=False,strict=True)

    @app.post('/api/sessions/{sid}/question-candidates',status_code=202)
    async def extract_question_candidates(sid:str,body:CandidateRun):
        from .assistance import scoped_evidence
        from .jobs import active_candidate
        provider=provider_config();options=saved_setting('candidate_options:'+sid,{'enabled':False})
        if body.automatic and (not options['enabled'] or provider.provider not in ('ollama','local')):raise ValueError('자동 질문 후보 추출이 꺼져 있습니다. API는 직접 실행하세요')
        request=AIRequest(session_id=sid,kind='candidates',prompt='최근 확정 전사에서 원문 인용을 붙인 질문 후보를 추출하세요.',scope=Scope(session_id=sid,mode='current'),provider=provider)
        active=active_candidate(db,sid)
        if active:return {'job':active,'reason':'기존 후보 추출 작업'}
        snapshot=capture_request(db,request);evidence=scoped_evidence(db,request,snapshot)
        if not evidence:return {'job':None,'reason':'확정 전사 대기'}
        signature=hashlib.sha256(json.dumps([[e.ref.id for e in evidence],provider.model_dump()],sort_keys=True).encode()).hexdigest()
        last=saved_setting('candidate_last:'+sid,{})
        if last.get('job_id'):
            try:old=get_job(db,last['job_id'])
            except KeyError:old=None
            if old and (old['status'] in ('queued','running') or signature==last.get('signature')):return {'job':old,'reason':'기존 후보 추출 작업'}
        if body.automatic and time.time()-last.get('submitted_at',0)<30:return {'job':None,'reason':'추출 간격 대기'}
        job=submit_job(db,sid,'ai',{'request':request.model_dump(),'snapshot':snapshot})
        with db:db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('candidate_last:'+sid,json.dumps({'job_id':job['id'],'signature':signature,'submitted_at':time.time()})))
        return {'job':launch_ai(job),'reason':None}

    class CardChange(Input):
        prompt:str|None=Field(default=None,min_length=1,max_length=2000)
        pinned:bool|None=Field(default=None,strict=True)
        dismissed:bool|None=Field(default=None,strict=True)

    @app.patch('/api/sessions/{sid}/question-cards/{ident}')
    async def change_question_card(sid:str,ident:str,body:CardChange):
        from .assistance import update_card
        return update_card(db,sid,ident,body.model_dump(exclude_none=True))

    class CardAnswer(Input):
        scope:Scope

    @app.post('/api/sessions/{sid}/question-cards/{ident}/answer',status_code=202)
    async def answer_question_card(sid:str,ident:str,body:CardAnswer):
        from .assistance import question_cards,update_card
        if body.scope.session_id!=sid:raise ValueError('질문 기록과 검색 범위가 일치하지 않습니다')
        card=next((c for c in question_cards(db,sid) if c['id']==ident),None)
        if card is None or card['dismissed']:raise ValueError('답변할 질문 후보를 선택하세요')
        if card['answer_job_id']:return get_job(db,card['answer_job_id'])
        job=await ai_job(AIInput(session_id=sid,prompt=card['prompt'],scope=body.scope))
        update_card(db,sid,ident,{'answer_job_id':job['id']})
        return job

    @app.get('/api/sessions/{sid}/artifacts')
    async def artifacts(sid:str):
        session(db,sid)
        return [public_artifact(db,row[0]) for row in db.execute('SELECT id FROM artifacts WHERE session_id=? ORDER BY created_at DESC',(sid,))]

    class ParticipantsInput(Input):
        names:list[str]=Field(max_length=100)

    class EditArtifactInput(Input):
        body:dict
        confirmed:bool=False

    @app.get('/api/sessions/{sid}/participants')
    async def participants(sid:str):
        return list_participants(db,sid)

    @app.put('/api/sessions/{sid}/participants')
    async def put_participants(sid:str,body:ParticipantsInput):
        return save_participants(db,sid,body.names)

    @app.patch('/api/artifacts/{ident}')
    async def patch_artifact(ident:str,body:EditArtifactInput):
        return edit_artifact(db,ident,body.body,body.confirmed)

    @app.api_route('/api/artifacts/{ident}/export',methods=['GET','HEAD'])
    async def export_artifact(ident:str):
        return PlainTextResponse(export_markdown(db,ident),media_type='text/markdown',headers={'Content-Disposition':'attachment; filename="lecture-study.md"'})

    class AttemptInput(Input):
        question_id:str
        answer:str=Field(min_length=1,max_length=10000)

    class OverrideInput(Input):
        grade:str
        explanation:str=Field(min_length=1,max_length=10000)

    @app.post('/api/quizzes/{ident}/attempts')
    async def attempt(ident:str,body:AttemptInput):
        _,question=quiz_question(db,ident,body.question_id)
        provider=provider_config() if question['kind']=='free' else None
        if provider and provider.provider in ('ollama','local'):
            aid=save_attempt(db,ident,body.question_id,body.answer)
            quiz,_=quiz_question(db,ident,body.question_id)
            job=submit_job(db,quiz['session_id'],'grade',{'attempt_id':aid,'provider':provider.model_dump()})
            with db:db.execute('UPDATE attempts SET metadata=? WHERE id=?',(json.dumps({'job_id':job['id']}),aid))
            launch_grade(job)
            return JSONResponse(job,status_code=202)
        return await submit_attempt(db,ident,body.question_id,body.answer,provider=provider,secret_loader=app.state.secrets.get_secret,generation_lock=app.state.external_generation_lock,ollama_url=app.state.ollama_url)

    def launch_grade(job):
        async def operation():
            provider=ProviderConfig.model_validate(job['request']['provider'])
            if config.embedded and provider.provider=='ollama':raise ValueError('이전 모델 엔진의 채점입니다. 새 작업으로 실행하세요')
            result=await grade_attempt(db,job['request']['attempt_id'],provider=provider,generation_lock=generation_slot(provider.provider,job['id']),ollama_url=app.state.ollama_url,before_local=lambda:wait_for_transcription(db,job['id']),direct_models=app.state.direct_models)
            if result['status']!='done':raise ValueError(result['error'] or '채점 실패')
            return {'attempt_id':result['id']}
        return launch_job(app,job,operation)

    @app.patch('/api/attempts/{ident}')
    async def patch_attempt(ident:str,body:OverrideInput):
        return override_attempt(db,ident,body.grade,body.explanation)

    @app.get('/api/sessions/{sid}/review')
    async def review(sid:str):
        return review_attempts(db,sid)

    class LocalRetry(Input):
        model:str='qwen3.5:4b'
        context_limit:int=Field(default=8192,ge=512,le=262144)

    @app.post('/api/jobs/{ident}/retry-local')
    async def retry_local(ident:str,body:LocalRetry):
        old=get_job(db,ident)
        if old['kind']!='ai' or old['status'] not in ('failed','cancelled','interrupted'): raise ValueError('실패·취소·중단된 생성 작업만 로컬 재시도가 가능합니다')
        selected=ProviderConfig(provider='local' if config.embedded else 'ollama',model=body.model,context_limit=body.context_limit)
        status=await model_status(selected,ollama_url=app.state.ollama_url,direct_models=app.state.direct_models)
        if not status['completion'] or old['request']['request']['kind']=='vision' and not status['vision']: raise ValueError('로컬 모델이 요청 기능을 지원하지 않습니다')
        selected=selected.model_copy(update={'vision':status['vision']})
        if config.embedded:
            request=AIRequest.model_validate(old['request']['request']).model_copy(update={'provider':selected})
            fresh=await freeze_request(db,request) if request.kind=='vision' else {'request':request.model_dump(),'snapshot':capture_request(db,request)}
            return launch_ai(submit_job(db,old['session_id'],'ai',fresh,course_id=old['course_id']))
        frozen=old['request'];frozen['request']['provider']=selected.model_dump()
        with db: db.execute('UPDATE jobs SET request=? WHERE id=?',(json.dumps(frozen,ensure_ascii=False),ident))
        return launch_ai(submit_job(db,old['session_id'],'ai',frozen,ident,course_id=old['course_id']))

    class SearchInput(Input):
        query: str = Field(min_length=1,max_length=2000)
        scope: Scope

    class TermInput(Input):
        canonical: str = Field(min_length=1,max_length=120)
        aliases: list[str] = Field(default_factory=list,max_length=30)
        explanation: str = Field(default="",max_length=10000)
        evidence: list[SourceRef] = Field(default_factory=list,max_length=32)
        term_id: str | None = None

    class RebuildInput(Input):
        session_id: str
        model: str = Field(default="embeddinggemma",pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,199}$")

    @app.post("/api/sessions/{sid}/search")
    async def search_sources(sid: str,body: SearchInput):
        if body.scope.session_id!=sid: raise ValueError("검색 기록이 일치하지 않습니다")
        if (config.embedded or app.state.ollama_url) and index_status(db)['ready']:
            job=submit_job(db,sid,'search',body.model_dump()|{'snapshot':capture_search(db,body.scope,None)})
            launch_search(job)
            return JSONResponse(job,status_code=202)
        async with local_embedding_client() as client:
            return await retrieve(db,body.query,body.scope,None,client=client)

    def launch_search(job):
        async def operation():
            body=job['request']
            async with local_embedding_client(job['id']) as client:
                return await retrieve(db,body['query'],Scope.model_validate(body['scope']),None,client=client,snapshot=body['snapshot'])
        return launch_job(app,job,operation)

    @app.get("/api/sessions/{sid}/terms")
    async def terms(sid: str):
        return list_terms(db,sid)

    @app.put("/api/sessions/{sid}/terms")
    async def put_term(sid: str,body: TermInput):
        ident=save_term(db,sid,body.canonical,body.aliases,body.explanation,body.evidence,body.term_id)
        return next(t for t in list_terms(db,sid) if t['id']==ident)

    @app.get("/api/sessions/{sid}/terms/{term_id}")
    async def get_concept(sid: str,term_id: str):
        return concept_detail(db,sid,term_id)|{'related_quizzes':related_quizzes(db,sid,term_id)}

    @app.get("/api/index/status")
    async def get_index_status():
        return index_status(db)

    def launch_index(job):
        async def operation():
            async with app.state.embedding_lock,local_embedding_client(job['id']) as client:
                if client is None: raise ValueError("로컬 임베딩 모델 연결이 끊겼습니다")
                return await rebuild_embeddings(db,job['request']['model'],client,job['id'])
        return launch_job(app,job,operation)

    @app.post("/api/index/rebuild",status_code=202)
    async def rebuild_index(body: RebuildInput):
        session(db,body.session_id)
        if not config.embedded and app.state.ollama_url is None: raise ValueError("로컬 임베딩 모델 연결을 먼저 준비하세요")
        return launch_index(submit_job(db,body.session_id,'index',body.model_dump()))

    @app.get("/api/courses")
    async def courses():
        return [dict(row) for row in db.execute("SELECT * FROM courses ORDER BY created_at DESC")]

    @app.post("/api/courses", status_code=201)
    async def add_course(body: CourseInput):
        ident = new_id()
        with db:
            db.execute("INSERT INTO courses VALUES (?,?,?,?)", (ident,body.title,body.description,now()))
        return dict(db.execute("SELECT * FROM courses WHERE id=?", (ident,)).fetchone())

    @app.get('/api/courses/{ident}/materials')
    async def materials_for_course(ident:str):
        return list_course_materials(db,ident)

    @app.get('/api/courses/{ident}/jobs')
    async def course_jobs(ident:str):
        course(db,ident)
        return [get_job(db,row[0]) for row in db.execute('SELECT id FROM jobs WHERE course_id=? ORDER BY created_at DESC',(ident,))]

    @app.get('/api/courses/{ident}/artifacts')
    async def course_artifacts(ident:str):
        course(db,ident)
        return [public_artifact(db,row[0]) for row in db.execute('SELECT id FROM artifacts WHERE course_id=? ORDER BY created_at DESC',(ident,))]

    @app.get('/api/courses/{ident}/terms')
    async def course_terms(ident:str):
        return list_terms(db,Scope(course_id=ident))

    @app.post('/api/courses/{ident}/search')
    async def search_course(ident:str,body:SearchInput):
        if body.scope.course_id!=ident:raise ValueError('검색 과목이 일치하지 않습니다')
        if (config.embedded or app.state.ollama_url) and index_status(db)['ready']:
            job=submit_job(db,None,'search',body.model_dump()|{'snapshot':capture_search(db,body.scope,None)},course_id=ident)
            launch_search(job)
            return JSONResponse(job,status_code=202)
        async with local_embedding_client() as client:return await retrieve(db,body.query,body.scope,None,client=client)

    @app.get("/api/sessions")
    async def sessions():
        return [dict(row) for row in db.execute("SELECT * FROM sessions WHERE deleted=0 ORDER BY started_at DESC")]

    @app.post("/api/sessions", status_code=201)
    async def add_session(body: SessionInput):
        return create_session(db, body.kind, body.title, body.course_id, body.lecture_no, body.started_at, body.description)

    @app.get("/api/sessions/{ident}")
    async def get_session(ident: str):
        return session(db, ident)


    async def parse_asset(ident):
        async with app.state.parse_lock:
            with db:
                db.execute("UPDATE assets SET status='running',error=NULL WHERE id=?",(ident,))
            return await ingest_asset(db,ident,config.runtime_dir)

    async def chosen_files(selected,kind='material'):
        if config.embedded:
            if selected is None:raise ValueError('앱의 파일 선택 창을 사용하세요')
            return [Path(path) for path in selected]
        return await select_files(config.runtime_dir,kind)

    @app.post("/api/sessions/{ident}/files/select",status_code=201)
    async def connect_files(ident: str,request:Request):
        session(db,ident)
        return await connect_owner_files(session_id=ident,selected=request.scope.get('native_selected_files'))

    @app.post('/api/courses/{ident}/files/select',status_code=201)
    async def connect_course_files(ident:str,request:Request):
        course(db,ident)
        return await connect_owner_files(course_id=ident,selected=request.scope.get('native_selected_files'))

    async def connect_owner_files(session_id=None,course_id=None,selected=None):
        async with app.state.file_selection:
            paths = await chosen_files(selected)
        result = []
        for path in paths:
            inspected = await asyncio.to_thread(inspect_file,path)
            asset = register_file(db,session_id,inspected,course_id)
            job = None
            if asset["status"] not in ("ready","partial") or public_asset(db,asset)["source_status"]!="current":
                job = submit_job(db,session_id,"parse",{"asset_id":asset["id"]},course_id=course_id)
                launch_job(app,job,lambda ident=asset["id"]:parse_asset(ident))
            result.append({"asset":public_asset(db,asset),"job":job})
        return result

    @app.post("/api/sessions/{ident}/assets/{asset_id}", status_code=201)
    async def link_asset(ident: str, asset_id: str):
        owner=session(db,ident)
        asset_dir(db,asset_id)
        with db:
            db.execute("INSERT OR IGNORE INTO session_assets VALUES (?,?)",(ident,asset_id))
            if owner['course_id']:db.execute('INSERT OR IGNORE INTO course_assets VALUES (?,?)',(owner['course_id'],asset_id))
        return {"linked":True}


    @app.post("/api/sessions/{ident}/assets/{asset_id}/extract",status_code=201)
    async def reextract(ident: str,asset_id: str):
        owner=session(db,ident)
        if not db.execute("SELECT 1 FROM session_assets WHERE session_id=? AND asset_id=? UNION ALL SELECT 1 FROM course_assets WHERE course_id=? AND asset_id=?",(ident,asset_id,owner['course_id'],asset_id)).fetchone():
            raise KeyError("연결된 자료가 아닙니다")
        return queue_extraction(asset_id,session_id=ident)

    @app.post('/api/courses/{ident}/assets/{asset_id}/extract',status_code=201)
    async def reextract_course(ident:str,asset_id:str):
        linked_asset(db,ident,asset_id)
        return queue_extraction(asset_id,course_id=ident)

    def queue_extraction(asset_id,session_id=None,course_id=None):
        for row in db.execute("SELECT id FROM jobs WHERE kind='parse' AND status IN ('queued','running')"):
            old = get_job(db,row["id"])
            if old["request"]["asset_id"]==asset_id:
                return old
        job = submit_job(db,session_id,"parse",{"asset_id":asset_id},course_id=course_id)
        launch_job(app,job,lambda:parse_asset(asset_id))
        return job

    @app.get("/api/sessions/{ident}/materials")
    async def materials_for_session(ident: str):
        return list_materials(db,ident)

    @app.api_route("/api/assets/{ident}/pages/{page}",methods=["GET","HEAD"])
    async def page_image(ident: str, page: int,document_sha256:str|None=None):
        async with app.state.parse_lock:
            path = await render_page(db,ident,page,config.runtime_dir,document_sha256)
        return cached_image(path,"image/png")

    @app.get('/api/assets/{ident}/document')
    async def asset_document(ident:str):
        async with app.state.parse_lock:return await document_metadata(db,ident,config.runtime_dir)

    @app.get('/api/courses/{ident}/assets/{asset_id}/pages/{page}/document')
    async def get_page_document(ident:str,asset_id:str,page:int,document_sha256:str,revision:int|None=None):
        return page_document(db,ident,asset_id,page,document_sha256,revision)

    @app.put('/api/courses/{ident}/assets/{asset_id}/pages/{page}/document')
    async def put_page_document(ident:str,asset_id:str,page:int,body:PageDocumentInput):
        return save_page_document(db,ident,asset_id,page,body)

    @app.api_route("/api/assets/{ident}/original",methods=["GET","HEAD"])
    async def original_material(ident: str,document_sha256:str|None=None):
        folder,asset = asset_dir(db,ident)
        source=checked_document_path(db,ident,document_sha256) if document_sha256 else original_path(db,asset)
        return FileResponse(source,filename=asset["filename"],media_type={"pdf":"application/pdf","png":"image/png","jpg":"image/jpeg","txt":"text/plain; charset=utf-8","md":"text/plain; charset=utf-8"}[asset["kind"]],content_disposition_type="inline")

    def cached_image(path,media_type):
        handle = path.open("rb")
        oversized = prune_cache(db,keep=path)
        def chunks():
            try:
                while chunk:=handle.read(65536):
                    yield chunk
            finally:
                handle.close()
                if oversized:
                    path.unlink(missing_ok=True)
        return StreamingResponse(chunks(),media_type=media_type)

    @app.api_route("/api/assets/{ident}/images/{image_id}",methods=["GET","HEAD"])
    async def embedded_image(ident: str, image_id: str):
        async with app.state.parse_lock:
            path = await render_image(db,ident,image_id,config.runtime_dir)
        return cached_image(path,"image/"+path.suffix[1:].replace("jpg","jpeg"))

    class NoteInput(BaseModel):
        text: str = Field(max_length=2_000_000)

    @app.put("/api/sessions/{ident}/note")
    async def update_note(ident: str, body: NoteInput):
        return save_note(db,ident,body.text)

    @app.get("/api/sessions/{ident}/jobs")
    async def session_jobs(ident: str):
        session(db,ident)
        return [get_job(db,row["id"]) for row in db.execute("SELECT id FROM jobs WHERE session_id=? ORDER BY created_at DESC",(ident,))]

    @app.get("/api/jobs/{ident}")
    async def job_status(ident: str):
        return get_job(db,ident)

    @app.get('/api/jobs/{ident}/summary-parts')
    async def summary_progress(ident:str):
        return cached_summary_parts(db,ident)

    @app.post("/api/jobs/{ident}/retry")
    async def retry_job(ident: str):
        old = get_job(db,ident)
        if old['kind']=='runtime':
            job=submit_job(db,None,'runtime',old['request'],ident)
            if job['status']=='queued' and ident not in app.state.job_tasks:launch_runtime(job)
            return job
        if old["kind"]=="transcribe":
            return await retry_transcription(old["request"]["recording_id"])
        if old['kind']=='asr_review':
            unchanged(db,old['request'])
            job=submit_job(db,old['session_id'],old['kind'],old['request'],ident)
            kick_transcription()
            return job
        if old['kind']=='ai':
            if config.embedded and old['request']['request']['provider']['provider']=='ollama':raise ValueError('이전 모델 엔진의 요청입니다. 새 작업으로 실행하세요')
            job=submit_job(db,old['session_id'],'ai',old['request'],ident,course_id=old['course_id'])
            if job['status']=='queued' and ident not in app.state.job_tasks: launch_ai(job)
            return job
        if old['kind'] in ('grade','search'):
            if config.embedded and old['kind']=='grade' and old['request']['provider']['provider']=='ollama':raise ValueError('이전 모델 엔진의 채점입니다. 새 작업으로 실행하세요')
            job=submit_job(db,old['session_id'],old['kind'],old['request'],ident,course_id=old['course_id'])
            if job['status']=='queued' and ident not in app.state.job_tasks:
                (launch_grade if old['kind']=='grade' else launch_search)(job)
            return job
        if old["kind"]=="index":
            if not config.embedded and app.state.ollama_url is None: raise ValueError("로컬 임베딩 모델 연결을 먼저 준비하세요")
            job=submit_job(db,old["session_id"],old["kind"],old["request"],ident)
            if job["status"]=="queued" and ident not in app.state.job_tasks: launch_index(job)
            return job
        if old["kind"]!="parse":
            raise ValueError("재시도할 수 없는 작업입니다")
        job = submit_job(db,old["session_id"],old["kind"],old["request"],ident,course_id=old['course_id'])
        if job["status"]=="queued" and ident not in app.state.job_tasks:
            launch_job(app,job,lambda:parse_asset(old["request"]["asset_id"]))
        return job

    @app.post("/api/jobs/{ident}/cancel")
    async def cancel_job(ident: str):
        old=get_job(db,ident)
        if old["kind"]=="transcribe" and old["status"] in ("queued","running"):
            rid=old["request"]["recording_id"]
            with db:
                db.execute("UPDATE transcript_ranges SET status='cancelled' WHERE recording_id=? AND status IN ('queued','running')",(rid,))
                db.execute("UPDATE jobs SET status='cancelled',updated_at=? WHERE id=?",(now(),ident))
            if app.state.active_transcription==rid:
                app.state.transcription_task.cancel()
                await asyncio.gather(app.state.transcription_task,return_exceptions=True)
            kick_transcription()
            return get_job(db,ident)
        if old['kind']=='asr_review' and old['status']=='queued':
            with db:db.execute("UPDATE jobs SET status='cancelled',updated_at=? WHERE id=?",(now(),ident))
        task = app.state.job_tasks.get(ident)
        if task:
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
        if old['kind']=='grade':
            with db:db.execute("UPDATE attempts SET status='cancelled',error='채점 취소' WHERE id=? AND status='grading'",(old['request']['attempt_id'],))
        return get_job(db,ident)


    class DeleteInput(Input):
        confirmed: bool = Field(strict=True)

    async def stop_session_work(ident,all_jobs=False):
        recordings={r["id"] for r in db.execute("SELECT id FROM recordings WHERE session_id=?",(ident,))}
        tasks=[]
        for job in db.execute("SELECT id FROM jobs WHERE session_id=? AND kind='asr_review' AND status IN ('queued','running')",(ident,)).fetchall():
            if task:=app.state.job_tasks.get(job['id']):task.cancel();tasks.append(task)
            with db:db.execute("UPDATE jobs SET status='cancelled',updated_at=? WHERE id=?",(now(),job['id']))
        if all_jobs:
            for job in db.execute("SELECT id FROM jobs WHERE session_id=?",(ident,)):
                if task:=app.state.job_tasks.get(job["id"]): task.cancel();tasks.append(task)
        if app.state.active_transcription in recordings and app.state.transcription_task:
            app.state.transcription_task.cancel();tasks.append(app.state.transcription_task)
        with db:
            for rid in recordings:
                db.execute("UPDATE transcript_ranges SET status='cancelled' WHERE recording_id=? AND status IN ('queued','running')",(rid,))
                db.execute("UPDATE recordings SET status='interrupted' WHERE id=? AND status='recording'",(rid,))
        for rid in recordings:
            if ws:=app.state.audio_sockets.get(rid):
                try: await ws.close(code=1001)
                except RuntimeError: pass
        await asyncio.gather(*tasks,return_exceptions=True)

    @app.delete("/api/sessions/{ident}")
    async def remove_session(ident: str,body: DeleteInput):
        session(db,ident)
        if not body.confirmed: raise ValueError("기록 삭제를 확인하세요")
        with db: db.execute("UPDATE sessions SET deleted=1 WHERE id=?",(ident,))
        await stop_session_work(ident,True)
        delete_session(db,ident,True)
        kick_transcription()
        return {"deleted":True,"cleanup_pending":db.execute("SELECT count(*) FROM file_cleanup").fetchone()[0]}

    @app.delete("/api/sessions/{ident}/audio")
    async def remove_audio(ident: str,body: DeleteInput):
        session(db,ident)
        if not body.confirmed: raise ValueError("원음 삭제·연결 해제를 확인하세요")
        await stop_session_work(ident)
        delete_audio(db,ident)
        kick_transcription()
        return {"deleted":True,"cleanup_pending":db.execute("SELECT count(*) FROM file_cleanup").fetchone()[0]}

    @app.api_route("/api/recordings/{ident}/audio",methods=["GET","HEAD"])
    async def original_audio(ident: str):
        import mimetypes
        path=playable_path(db,ident)
        return FileResponse(path,media_type=mimetypes.guess_type(path.name)[0] or "audio/wav")

    @app.get("/api/sources/{ident}")
    async def source_details(ident: str):
        row=db.execute("SELECT ref FROM sources WHERE id=?",(ident,)).fetchone()
        if row is None: raise KeyError("출처를 찾을 수 없습니다")
        return resolve_source(db,SourceRef.model_validate_json(row["ref"]))

    def finish_audio_jobs():
        for record in db.execute("SELECT id,stop_job_id FROM recordings WHERE stop_job_id IS NOT NULL AND status!='recording' AND transcription_released=1").fetchall():
            status=transcription_status(db,record["id"])
            if status["queued"] or status["running"]: continue
            error=db.execute("SELECT error FROM transcript_ranges WHERE recording_id=? AND status IN ('failed','interrupted') LIMIT 1",(record["id"],)).fetchone()
            with db:
                db.execute("UPDATE jobs SET status=?,result=?,error=?,updated_at=? WHERE id=? AND status IN ('queued','running')",
                           ("failed" if error else "cancelled" if status["cancelled"] else "done",json.dumps(status),error[0] if error else None,now(),record["stop_job_id"]))

    async def transcription_loop():
        try:
            while True:
                chunk=db.execute("SELECT t.* FROM transcript_ranges t JOIN recordings r ON r.id=t.recording_id WHERE t.status='queued' AND r.transcription_released=1 ORDER BY t.final DESC,t.start_frame LIMIT 1").fetchone()
                if chunk:
                    app.state.active_transcription=chunk['recording_id']
                    record=get_recording(db,chunk['recording_id'])
                    if record['stop_job_id']:
                        with db:db.execute("UPDATE jobs SET status='running',updated_at=? WHERE id=? AND status='queued'",(now(),record['stop_job_id']))
                    task=asyncio.create_task(process_chunk(db,dict(chunk),config.runtime_dir))
                    app.state.active_asr=(task,dict(chunk))
                    try:await task
                    except asyncio.CancelledError:
                        if asyncio.current_task().cancelling():raise
                    finally:app.state.active_asr=None
                    latest=db.execute('SELECT * FROM transcript_ranges WHERE id=?',(chunk['id'],)).fetchone()
                    if latest and latest['final'] and latest['status']=='done':
                        activity=task.result()if not task.cancelled()else None
                        try:queue_review(db,latest['id'],automatic=True,runtime=config.runtime_dir,**({'activity':activity}if isinstance(activity,list)else{}))
                        except (KeyError,ValueError,OSError) as exc:logging.getLogger(__name__).warning('Optional transcription review skipped: %s',exc)
                    app.state.active_transcription=None
                    finish_audio_jobs()
                    continue
                if app.state.generation_lock.locked() or app.state.embedding_lock.locked() or app.state.active_embedding_clients:break
                if db.execute("SELECT 1 FROM jobs WHERE status IN ('queued','running') AND (kind IN ('search','index') OR (kind='ai' AND json_extract(request,'$.request.provider.provider') IN ('ollama','local')) OR (kind='grade' AND json_extract(request,'$.provider.provider') IN ('ollama','local'))) LIMIT 1").fetchone():break
                pending=db.execute("SELECT id FROM jobs WHERE kind='asr_review' AND status='queued' AND EXISTS(SELECT 1 FROM recordings r WHERE r.id=json_extract(jobs.request,'$.recording_id') AND r.transcription_released=1) ORDER BY created_at LIMIT 1").fetchone()
                if not pending:break
                job=get_job(db,pending['id'])
                async def operation():
                    async with app.state.generation_lock:
                        return await process_review(db,job,config.runtime_dir)
                launch_job(app,job,operation)
                task=app.state.job_tasks[job['id']]
                app.state.active_transcription=job['request']['recording_id']
                app.state.active_asr=(task,{'review_job':job['id']})
                try:await task
                except asyncio.CancelledError:
                    if asyncio.current_task().cancelling():raise
                finally:app.state.active_asr=None;app.state.active_transcription=None
        finally:
            app.state.active_transcription=None
            finish_audio_jobs()

    def kick_transcription():
        if app.state.closing:return
        active=app.state.active_asr
        if active and 'review_job' in active[1] and not active[0].cancelling() and db.execute("SELECT 1 FROM transcript_ranges WHERE final=1 AND status='queued' LIMIT 1").fetchone():active[0].cancel()
        task=app.state.transcription_task
        if task is None or task.done():
            task=asyncio.create_task(transcription_loop())
            app.state.transcription_task=task
            app.state.tasks.add(task)
            task.add_done_callback(app.state.tasks.discard)

    app.state.kick_transcription=kick_transcription

    def plan_audio(ident,stopping=False):
        if not get_recording(db,ident)['transcription_released']:return
        try: plan_chunks(db,ident,stopping)
        except (OSError,ValueError) as exc:
            with db:
                db.execute("UPDATE recordings SET error=? WHERE id=?",(str(exc)[:300],ident))
                db.execute("UPDATE jobs SET status='failed',error=?,updated_at=? WHERE id=(SELECT stop_job_id FROM recordings WHERE id=?) AND status IN ('queued','running')",(str(exc)[:300],now(),ident))
            return
        active=app.state.active_asr
        if active and 'review_job' not in active[1] and not active[1]['final'] and not active[0].cancelling():
            latest=db.execute('SELECT final FROM transcript_ranges WHERE id=?',(active[1]['id'],)).fetchone()
            if latest and latest['final']:active[0].cancel()
        kick_transcription()

    def release_capture(ident):
        record=get_recording(db,ident)
        if record['transcription_mode']=='realtime':plan_audio(ident,True);return True
        group=record['capture_id']or ident
        if db.execute("SELECT 1 FROM recordings WHERE capture_id=? AND session_id=? AND status='recording'",(group,record['session_id'])).fetchone():return False
        records=[dict(r)for r in db.execute("SELECT * FROM recordings WHERE capture_id=? AND session_id=? AND transcription_mode='after_stop'",(group,record['session_id']))]
        with db:db.execute("UPDATE recordings SET transcription_released=1 WHERE capture_id=? AND session_id=?",(group,record['session_id']))
        for row in records:
            job=stop_recording(db,row['id'],interrupted=row['status']=='interrupted') if not row['stop_job_id'] else get_job(db,row['stop_job_id'])
            if job['status']=='interrupted':
                submit_job(db,row['session_id'],'transcribe',job['request'],job['id'])
                with db:db.execute("UPDATE transcript_ranges SET status='queued',error=NULL WHERE recording_id=? AND status='interrupted'",(row['id'],))
            if not row['transcription_released']:
                with db:db.execute("UPDATE jobs SET result=NULL WHERE id=? AND status='queued'",(job['id'],))
            if job['status'] in ('cancelled','failed'):continue
            plan_audio(row['id'],True)
        return True

    def conclude_audio(ident,defer=False):
        record=get_recording(db,ident)
        if record['transcription_mode']=='realtime' or record['transcription_released'] or not defer:
            release_capture(ident);return
        if record['stop_job_id']:
            with db:db.execute("UPDATE jobs SET result=? WHERE id=? AND status='queued'",(json.dumps({'paused_reason':'녹음 종료 후 전사'}),record['stop_job_id']))
        if (pending:=app.state.audio_releases.get(ident)) and not pending.done():return
        async def release_later():
            try:
                await asyncio.sleep(AUDIO_RELEASE_SECONDS)
                release_capture(ident)
            except KeyError:pass
            finally:app.state.audio_releases.pop(ident,None)
        task=asyncio.create_task(release_later());app.state.audio_releases[ident]=task;app.state.tasks.add(task);task.add_done_callback(app.state.tasks.discard)

    @app.post("/api/sessions/{ident}/recordings",status_code=201)
    async def connect_recordings(ident: str,request:Request):
        session(db,ident)
        async with app.state.file_selection:
            paths=await chosen_files(request.scope.get('native_selected_files'),'audio')
        result=[]
        for path in paths:
            rid=await register_audio(db,ident,path,config.runtime_dir)
            job=submit_job(db,ident,"transcribe",{"recording_id":rid,"final":True})
            with db: db.execute("UPDATE recordings SET stop_job_id=? WHERE id=?",(job["id"],rid))
            result.append(job)
        kick_transcription()
        return result

    @app.post("/api/recordings/{ident}/transcribe")
    async def retry_transcription(ident: str):
        record=get_recording(db,ident)
        if record["status"]=="recording": raise ValueError("녹음 종료 후 재시도하세요")
        job=stop_recording(db,ident) if record["kind"]=="live" and not record["stop_job_id"] else get_job(db,record["stop_job_id"])
        if job["status"] in ("failed","cancelled","interrupted"):
            job=submit_job(db,record["session_id"],"transcribe",job["request"],job["id"])
        with db: db.execute("UPDATE transcript_ranges SET status='queued',error=NULL WHERE recording_id=? AND status IN ('failed','interrupted','cancelled')",(ident,))
        release_capture(ident)
        return job

    class TranscriptionTerms(Input):
        terms: list[str] = Field(max_length=30)

    @app.get("/api/sessions/{ident}/transcription-terms")
    async def transcription_terms(ident: str):
        return {"terms":get_asr_terms(db,ident),"effective_prompt":asr_prompt(db,ident)}

    @app.put("/api/sessions/{ident}/transcription-terms")
    async def update_transcription_terms(ident: str,body: TranscriptionTerms):
        terms=save_asr_terms(db,ident,body.terms)
        return {"terms":terms,"effective_prompt":asr_prompt(db,ident)}

    class TranscriptEdit(Input):
        text: str = Field(min_length=1,max_length=10000)
        expected_revision: int | None = Field(default=None,ge=1,strict=True)

    class TranscriptBatchItem(Input):
        id: str = Field(min_length=1,max_length=100)
        expected_revision: int = Field(ge=1,strict=True)
        text: str = Field(min_length=1,max_length=10000)

    class TranscriptBatchEdit(Input):
        segments: list[TranscriptBatchItem] = Field(min_length=1,max_length=200)

    @app.patch('/api/sessions/{ident}/transcripts')
    async def update_transcripts(ident:str,body:TranscriptBatchEdit):
        return {'segments':edit_segments(db,ident,[item.model_dump() for item in body.segments])}

    @app.api_route('/api/sessions/{ident}/transcripts/export',methods=['GET','HEAD'])
    async def download_transcript(ident:str,request:Request,format:Literal['txt','md']='txt'):
        vault_id=db.execute("SELECT value FROM settings WHERE key='native_vault_id'").fetchone()[0] if config.embedded else None
        text=export_transcript(db,ident,format,str(request.base_url),vault_id=vault_id)
        return PlainTextResponse(text,media_type='text/markdown' if format=='md' else 'text/plain',headers={'Content-Disposition':f'attachment; filename="transcript-{ident}.{format}"'})

    @app.patch("/api/transcripts/{ident}")
    async def update_transcript(ident: str,body: TranscriptEdit):
        return edit_segment(db,ident,body.text,expected_revision=body.expected_revision)

    @app.post('/api/transcript-ranges/{ident}/review',status_code=202)
    async def request_review(ident:str):
        job=queue_review(db,ident,automatic=False,runtime=config.runtime_dir)
        kick_transcription()
        return job

    @app.post('/api/jobs/{ident}/apply-transcript')
    async def confirm_transcript(ident:str,body:TranscriptEdit):
        return apply_review(db,ident,body.text)

    def public_recording(ident):
        record=get_recording(db,ident)
        record.pop("external_path",None)
        record["transcription"]=transcription_status(db,ident)
        if record["stop_job_id"] and not sum(record["transcription"].values()):
            if get_job(db,record["stop_job_id"])["status"]=="interrupted": record["transcription"]["interrupted"]=1
        failed=db.execute("SELECT error FROM transcript_ranges WHERE recording_id=? AND status IN ('failed','interrupted') LIMIT 1",(ident,)).fetchone()
        if failed and failed[0]: record["error"]=failed[0]
        return record

    @app.get("/api/sessions/{ident}/events")
    async def session_events(ident: str):
        session(db,ident)
        return {"transcripts":list_transcripts(db,ident),"asr_reviews":public_reviews(db,ident),"empty_transcript_ranges":empty_ranges(db,ident),"recordings":[public_recording(r["id"]) for r in db.execute("SELECT id FROM recordings WHERE session_id=? ORDER BY started_at",(ident,))]}

    class AudioStart(Input):
        sample_rate: int = Field(ge=8000,le=192000,strict=True)
        transcription_mode:Literal['after_stop','realtime']='after_stop'
        resume_from:str|None=Field(default=None,pattern=r'^[0-9a-f]{32}$')

    @app.post("/api/sessions/{ident}/audio/start",status_code=201)
    async def begin_audio(ident: str,body: AudioStart):
        rid=start_recording(db,ident,body.sample_rate,body.transcription_mode,body.resume_from)
        async def expire_start():
            try:
                await asyncio.sleep(AUDIO_IDLE_SECONDS)
                if get_recording(db,rid)['status']=='recording' and rid not in app.state.audio_sockets:
                    stop_recording(db,rid,interrupted=True,error='오디오 연결 시간 초과')
                    conclude_audio(rid,defer=True)
            except KeyError:pass
            finally:app.state.audio_starts.pop(rid,None)
        task=asyncio.create_task(expire_start());app.state.audio_starts[rid]=task;app.state.tasks.add(task);task.add_done_callback(app.state.tasks.discard)
        return {'recording_id':rid}

    class AudioStop(Input):
        end_frame: int|None = Field(default=None,ge=0,strict=True)
        interrupted: bool = False
        reason: str|None = Field(default=None,max_length=300)
        defer_transcription:bool=Field(default=False,strict=True)

    @app.post("/api/recordings/{ident}/stop")
    async def end_audio(ident: str,body: AudioStop):
        if pending:=app.state.audio_starts.get(ident):pending.cancel()
        job=stop_recording(db,ident,body.end_frame,body.interrupted,body.reason if body.interrupted else None)
        conclude_audio(ident,defer=body.defer_transcription)
        return job

    @app.get("/api/sessions/{ident}/recordings")
    async def session_recordings(ident: str):
        session(db,ident)
        return [{k:v for k,v in get_recording(db,row["id"]).items() if k!="external_path"} for row in db.execute("SELECT id FROM recordings WHERE session_id=? ORDER BY started_at",(ident,))]

    class AudioInit(Input):
        recording_id: str = Field(pattern="^[a-f0-9]{32}$",strict=True)
        csrf_token: str = Field(pattern="^[A-Za-z0-9_-]{32,128}$",strict=True)
        sample_rate: int = Field(ge=8000,le=192000,strict=True)
        channels: int = Field(ge=1,le=1,strict=True)
        format: str = Field(pattern="^pcm_s16le$",strict=True)

    @app.websocket("/api/sessions/{ident}/audio")
    async def audio_socket(ws: WebSocket,ident: str):
        if ws.headers.get("host") not in hosts or ws.headers.get("origin") not in origins or not token_matches(ws.cookies.get(app.state.cookie_name,""),app.state.cookie):
            await ws.close(code=1008)
            return
        await ws.accept()
        recording_id = None;failure_reason="녹음 연결이 끊겼습니다"
        try:
            try:
                init = AudioInit.model_validate(await asyncio.wait_for(ws.receive_json(),5)).model_dump()
            except ValidationError:
                raise ValueError("녹음 연결 정보가 유효하지 않습니다") from None
            if not token_matches(init.get("csrf_token",""),app.state.csrf):
                raise ValueError("요청 토큰이 유효하지 않습니다")
            row = get_recording(db,init["recording_id"])
            if row["session_id"]!=ident or row["status"]!="recording" or init.get("sample_rate")!=row["sample_rate"] or init.get("channels")!=1 or init.get("format")!="pcm_s16le":
                raise ValueError("녹음 정보가 일치하지 않습니다")
            if row['id'] in app.state.audio_sockets:raise ValueError('이미 연결된 녹음입니다')
            recording_id = row["id"]
            if pending:=app.state.audio_starts.get(recording_id):pending.cancel()
            app.state.audio_sockets[recording_id]=ws
            await ws.send_json({"type":"ready"})
            while True:
                packet = await asyncio.wait_for(ws.receive_bytes(),AUDIO_IDLE_SECONDS)
                if len(packet)<20:
                    raise ValueError("PCM 헤더가 유효하지 않습니다")
                seq,first,count = struct.unpack_from("<QQI",packet)
                ack = append_pcm(db,recording_id,seq,first,count,packet[20:])
                await ws.send_json({"type":"ack",**ack})
                plan_audio(recording_id)
        except WebSocketDisconnect as exc:
            row=db.execute('SELECT status FROM recordings WHERE id=?',(recording_id,)).fetchone() if recording_id else None
            if row and row[0]=='recording':
                logging.getLogger(__name__).warning('Audio socket disconnected recording=%s code=%s reason_present=%s',recording_id,exc.code,bool(exc.reason))
        except (ValueError,KeyError,TimeoutError,OSError) as exc:
            failure_reason='오디오 입력 시간 초과' if isinstance(exc,TimeoutError) else '원음 저장 실패' if isinstance(exc,OSError) else str(exc)
            try:
                await ws.send_json({"type":"error","error":failure_reason,"recoverable":isinstance(exc,TimeoutError) and recording_id is not None})
                await ws.close(code=1008)
            except RuntimeError:
                pass
        finally:
            if recording_id and app.state.audio_sockets.get(recording_id) is ws:
                app.state.audio_sockets.pop(recording_id,None)
                try:
                    if get_recording(db,recording_id)['status']=='recording':
                        stop_recording(db,recording_id,interrupted=True,error=failure_reason)
                        conclude_audio(recording_id,defer=True)
                except (KeyError,OSError,ValueError):
                    try:interrupt_recording(db,recording_id)
                    except KeyError:pass

    frontend = Path(__file__).parent.parent / "frontend" / "dist"
    if frontend.is_dir():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return app
