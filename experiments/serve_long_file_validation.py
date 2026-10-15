"""Disposable production file import + real ASR/summary overlap; no UI or microphone.

Run with the prepared app Python and cached runtime. The server stays available for
export checks after the automated run. Only the native file picker is substituted.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

import httpx
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def overlap_seconds(left, right):
    return max(0, min(left['ended'], right['ended']) - max(left['request_started'], right['started']))


def public_report(trace):
    """Allowlist measurements; auth, paths, IDs and source text stay private."""
    from lecture_study.transcription import MODEL_NAME, MODEL_SHA, VAD_SHA
    def measured_call(item, start):
        return {key: item[key] for key in ('status', 'usage', 'provider_elapsed_ms', 'digest', 'exception_type', 'start_frame', 'end_frame', 'final', 'revision') if key in item} | {
            'started_seconds': item[start] - trace['started'],
            'ended_seconds': item['ended'] - trace['started'],
            'elapsed_seconds': item['ended'] - item[start]}
    transcription = {key: value for key, value in trace['transcription'].items() if key != 'recording_id'}
    summary = {key: value for key, value in trace['final_summary'].items() if key != 'artifact_id'}
    report = {key: trace[key] for key in ('ready', 'route', 'limitations', 'input', 'model', 'context_limit', 'overlap_seconds', 'total_seconds')}
    report.update(started_utc=datetime.fromtimestamp(trace['started'], timezone.utc).isoformat(),
                  model_digest=trace['model_check']['digest'],
                  asr_model={'name': MODEL_NAME, 'sha256': MODEL_SHA, 'vad_sha256': VAD_SHA},
                  readiness=[{'label': row['label'], 'ready': row['ready']} for row in trace['runtime_status']],
                  transcription=transcription, final_summary=summary,
                  jobs={name: {key: job[key] for key in ('kind', 'status', 'error')} for name, job in trace['jobs'].items()},
                  asr_calls=[measured_call(row, 'started') for row in trace['asr']],
                  generation_calls=[measured_call(row, 'request_started') for row in trace['generation']])
    if 'post_run' in trace:
        report['post_run'] = trace['post_run']
    encoded = json.dumps(report, ensure_ascii=False)
    assert all(value not in encoded for value in ('/Users/', '127.0.0.1', 'localhost', 'csrf_token', 'cookie', 'bootstrap_token'))
    assert all(trace[key] not in encoded for key in ('session_id', 'initial_summary_job_id', 'transcription_job_id', 'final_summary_job_id'))
    return report


def create_validation(args):
    from lecture_study import answers, outputs, server
    from lecture_study.config import AppConfig
    from lecture_study.launcher import bind_listener
    from lecture_study.transcription import file_hash

    folder = args.folder.resolve()
    if folder.exists():
        raise ValueError('Use a new disposable output folder')
    source = args.audio.resolve(strict=True)
    provenance = json.loads(source.with_suffix('.json').read_text())
    assert file_hash(source) == provenance['sha256']
    assert overlap_seconds({'request_started': 1, 'ended': 4}, {'started': 3, 'ended': 5}) == 1
    listener = bind_listener(args.port, strict=True)
    folder.mkdir(parents=True, mode=0o700)
    (folder / '.long-file-validation').touch(mode=0o600)
    runtime = folder / 'runtime'
    runtime.mkdir(mode=0o700)
    for name in ('asr', 'ffmpeg', 'models', 'ollama', 'ollama-models', 'tessdata'):
        original = args.runtime.resolve(strict=True) / name
        if original.exists():
            (runtime / name).symlink_to(original, target_is_directory=original.is_dir())
    trace = {'ready': False, 'route': 'Real TCP production APIs; cached MP3 import via fixed-path file-picker substitute; native Whisper large-v3-turbo and owned Ollama Qwen3.5:4b MLX',
             'limitations': ['No physical microphone, WKWebView, browser capture or AudioWorklet validation.', 'Single-speaker literary narration; no meeting, lecture, diarization or transcript accuracy benchmark.', 'Initial overlapping summary uses an explanatory note; final summary uses the completed transcript.', 'Host load and memory are uncontrolled; one validation run, no performance ranking.'],
             'input': {key: provenance[key] for key in ('title', 'author', 'reader', 'source', 'catalog', 'license', 'bytes', 'sha256', 'reference_limit')},
             'model': 'qwen3.5:4b', 'context_limit': 8192, 'asr': [], 'generation': [], 'jobs': {}, 'started': time.time()}

    def save():
        target = folder / 'trace.json'
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(trace, ensure_ascii=False, indent=2))
        temporary.replace(target)

    original_asr = server.process_chunk

    async def traced_asr(db, chunk, selected_runtime):
        item = {key: chunk[key] for key in ('id', 'recording_id', 'start_frame', 'end_frame', 'final', 'revision')}
        item['started'] = time.time()
        trace['asr'].append(item)
        save()
        try:
            return await original_asr(db, chunk, selected_runtime)
        except BaseException as exc:
            item['exception_type'] = type(exc).__name__
            raise
        finally:
            item['ended'] = time.time()
            row = db.execute('SELECT status,error FROM transcript_ranges WHERE id=?', (chunk['id'],)).fetchone()
            item.update(status=row['status'], error=row['error'])
            save()

    server.process_chunk = traced_asr
    original_generate = answers.generate
    admitted = asyncio.Event()

    async def traced_generate(*call_args, **kwargs):
        item = {'submitted': time.time(), 'model': call_args[0].model}
        trace['generation'].append(item)
        before = kwargs.get('before_local')

        async def gate():
            if before:
                await before()
            item['request_started'] = time.time()
            admitted.set()
            save()

        kwargs['before_local'] = gate
        try:
            result = await original_generate(*call_args, **kwargs)
            item.update(usage=result.usage, provider_elapsed_ms=result.elapsed_ms, digest=result.digest)
            return result
        except BaseException as exc:
            item.update(exception_type=type(exc).__name__, error=str(exc)[:500])
            raise
        finally:
            item['ended'] = time.time()
            save()

    answers.generate = outputs.generate = traced_generate

    async def selected_file(_runtime, kind='material'):
        assert kind == 'audio'
        trace['file_picker'] = {'substitute': True, 'kind': kind, 'selected_cached_sha256': provenance['sha256'], 'at': time.time()}
        save()
        return [source]

    server.select_files = selected_file
    app = server.create_app(AppConfig(folder / 'data', runtime, port=args.port))
    save()
    return app, listener, trace, save, admitted


async def run_validation(app, args, trace, save, admitted):
    base = 'http://127.0.0.1:' + str(args.port)
    folder = args.folder.resolve()
    async with httpx.AsyncClient(base_url=base, timeout=120, trust_env=False) as client:
        async def request(method, path, body=None):
            response = await client.request(method, '/api' + path, json=body, headers=headers)
            response.raise_for_status()
            return response.json()

        headers = {'Origin': base}
        login = await request('POST', '/bootstrap', {'token': app.state.bootstrap_token})
        headers['X-Session-Token'] = login['csrf_token']
        auth = {'base_url': base, 'cookie_name': app.state.cookie_name, 'cookie': app.state.cookie, 'csrf_token': login['csrf_token'], 'pid': os.getpid()}
        (folder / 'auth-info.json').write_text(json.dumps(auth))
        (folder / 'auth-info.json').chmod(0o600)
        trace['local_connection'] = await request('POST', '/local/connect', {'mode': 'managed'})
        await request('PUT', '/settings', {'provider': 'ollama', 'model': trace['model'], 'context_limit': 8192})
        trace['model_check'] = await request('POST', '/models/check')
        trace['runtime_status'] = await request('GET', '/runtime/status')
        assert trace['model_check']['accessible']
        assert all(item['ready'] for item in trace['runtime_status'] if item['label'].startswith(('전사', '로컬')))
        session = await request('POST', '/sessions', {'kind': 'lecture', 'title': '긴 한국어 파일 전사·요약 검증'})
        sid = trace['session_id'] = auth['session_id'] = session['id']
        (folder / 'auth-info.json').write_text(json.dumps(auth))
        await request('PUT', '/sessions/' + sid + '/note', {'text': '프로세스는 실행 중인 프로그램이며 독립된 주소 공간을 갖습니다. 스레드는 프로세스의 메모리를 공유합니다. 공유 자원 접근에는 동기화가 필요합니다. 이 메모는 긴 음성 전사와 동시에 실행할 실제 요약 요청의 입력입니다.'})

        async def summary():
            return await request('POST', '/ai/jobs', {'session_id': sid, 'kind': 'summary', 'prompt': '근거의 내용을 한국어로 요약하세요.', 'scope': {'session_id': sid, 'mode': 'current'}, 'web': False})

        async def wait_job(job_id, name, limit=3600):
            deadline = time.monotonic() + limit
            previous = None
            while True:
                job = await request('GET', '/jobs/' + job_id)
                state = (job['status'], json.dumps(job['result'], ensure_ascii=False))
                if state != previous:
                    trace['jobs'][name] = {key: job[key] for key in ('id', 'kind', 'status', 'result', 'error', 'created_at', 'updated_at')}
                    save()
                    print(json.dumps({'stage': name, 'status': job['status'], 'progress': job['result'], 'asr_calls': len(trace['asr']), 'generation_calls': len(trace['generation'])}, ensure_ascii=False), flush=True)
                    previous = state
                if job['status'] not in ('queued', 'running'):
                    return job
                assert time.monotonic() < deadline, name + ' timeout'
                await asyncio.sleep(1)

        started = time.time()
        initial = await summary()
        trace['initial_summary_job_id'] = initial['id']
        await asyncio.wait_for(admitted.wait(), 120)
        assert trace['generation'][0].get('request_started')
        assert 'ended' not in trace['generation'][0], 'Initial generation finished before file import'
        trace['import_started'] = time.time()
        imported = await request('POST', '/sessions/' + sid + '/recordings')
        assert len(imported) == 1
        trace['import_returned'] = time.time()
        trace['transcription_job_id'] = imported[0]['id']
        first, transcription = await asyncio.gather(wait_job(initial['id'], 'initial_summary'), wait_job(imported[0]['id'], 'transcription'))
        trace['asr_finished'] = time.time()
        events = await request('GET', '/sessions/' + sid + '/events')
        assert transcription['status'] == 'done', transcription['error']
        recording = events['recordings'][0]
        segments = [item for item in events['transcripts'] if item['recording_id'] == recording['id']]
        ranges = [dict(row) for row in app.state.db.execute('SELECT start_frame,end_frame,status FROM transcript_ranges WHERE recording_id=? ORDER BY start_frame', (recording['id'],))]
        assert ranges and ranges[0]['start_frame'] == 0 and ranges[-1]['end_frame'] == recording['source_frames']
        assert all(left['end_frame'] == right['start_frame'] for left, right in zip(ranges, ranges[1:]))
        assert all(item['status'] == 'done' for item in ranges)
        assert segments and all(item['final'] for item in segments)
        duration_ms = round(recording['source_frames'] * 1000 / recording['sample_rate'])
        assert all(0 <= item['start_ms'] < item['end_ms'] <= duration_ms + 1 for item in segments)
        overlaps = [overlap_seconds(generation, chunk) for generation in trace['generation'] if 'request_started' in generation for chunk in trace['asr']]
        trace['overlap_seconds'] = sum(overlaps)
        assert trace['overlap_seconds'] > 0, 'Actual admitted generation and ASR did not overlap'
        trace['transcription'] = {'recording_id': recording['id'], 'sample_rate': recording['sample_rate'], 'source_frames': recording['source_frames'], 'duration_seconds': recording['source_frames'] / recording['sample_rate'], 'range_count': len(ranges), 'all_ranges_done': True, 'continuous_source_coverage': True, 'segment_count': len(segments), 'first_segment_start_ms': min(item['start_ms'] for item in segments), 'last_segment_end_ms': max(item['end_ms'] for item in segments), 'recognized_characters': sum(len(item['text']) for item in segments), 'recording_status': recording['status'], 'gaps': recording['gaps'], 'error': recording['error'], 'elapsed_seconds_from_import': trace['asr_finished'] - trace['import_started']}
        assert trace['transcription']['duration_seconds'] > 878
        assert first['status'] == 'done', first['error']
        # Remove the seed note so the final snapshot contains only real ASR text.
        await request('PUT', '/sessions/' + sid + '/note', {'text': ''})
        trace['final_summary_submitted'] = time.time()
        final = await summary()
        trace['final_summary_job_id'] = auth['final_summary_job_id'] = final['id']
        (folder / 'auth-info.json').write_text(json.dumps(auth))
        final = await wait_job(final['id'], 'final_summary')
        assert final['status'] == 'done', final['error']
        artifact = await request('GET', '/artifacts/' + final['result']['id'])
        assert artifact['metadata']['digest'] == trace['model_check']['digest']
        evidence = artifact['evidence']
        assert evidence and all(item['ref']['kind'] == 'transcript' for item in evidence)
        assert {item['ref']['id'] for item in evidence} == {item['id'] + ':v' + str(item['revision']) for item in segments}
        body = artifact['body']
        trace['final_summary'] = {'artifact_id': artifact['id'], 'section_count': len(body['sections']), 'completed_parts': body['completed_parts'], 'covered_source_count': len(body['covered_source_ids']), 'cited_source_count': len(body['cited_source_ids']), 'source_count': len(evidence), 'full_transcript_snapshot': True, 'covered_range_count': len(body['covered_ranges']), 'unquoted_source_count': len(body.get('unquoted_sources', [])), 'review_required_section_count': sum(bool(item.get('review_required')) for item in body['sections']), 'selection_incomplete_parts': body.get('selection_incomplete_parts', []), 'metadata': {key: artifact['metadata'].get(key) for key in ('provider', 'model', 'digest', 'elapsed_ms', 'warning', 'content_warnings', 'excerpted')}, 'elapsed_seconds': time.time() - trace['final_summary_submitted']}
        auth['artifact_id'] = artifact['id']
        (folder / 'auth-info.json').write_text(json.dumps(auth))
        assert all(job['status'] == 'done' for job in await request('GET', '/sessions/' + sid + '/jobs'))
        from lecture_study.transcription import file_hash
        assert await asyncio.to_thread(file_hash, args.audio) == trace['input']['sha256']
        await request('POST', '/local/disconnect')
        assert not (await request('GET', '/settings'))['local_connected']
        trace['post_run'] = {'all_jobs_done': True, 'original_audio_sha256_unchanged': True, 'owned_runtime_disconnected': True, 'api_server_kept_running_for_export': True, 'summary_model_digest_verified': True, 'no_model_retry': True, 'no_model_change': True}
        trace.update(ready=True, ended=time.time(), total_seconds=time.time() - started)
        save()
        public = ROOT / 'docs/mac-long-file-validation.json'
        public.write_text(json.dumps(public_report(trace), ensure_ascii=False, indent=2))
        print(json.dumps({'ready': True, 'duration_seconds': trace['transcription']['duration_seconds'], 'overlap_seconds': trace['overlap_seconds'], 'summary': trace['final_summary'], 'public_report': str(public)}, ensure_ascii=False), flush=True)


async def main(args):
    app, listener, trace, save, admitted = create_validation(args)
    host = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=args.port, access_log=False))
    server_task = asyncio.create_task(host.serve(sockets=[listener]))
    while not host.started:
        if server_task.done():
            await server_task
            raise RuntimeError('Server failed before startup')
        await asyncio.sleep(.05)
    print(json.dumps({'server': 'http://127.0.0.1:' + str(args.port), 'pid': os.getpid(), 'state': str(args.folder), 'models': 'real cached engines; no downloads'}), flush=True)
    try:
        await run_validation(app, args, trace, save, admitted)
    except Exception as exc:
        trace.update(ready=False, failure={'type': type(exc).__name__, 'error': str(exc)[:1000], 'at': time.time()})
        save()
        print(json.dumps({'ready': False, 'failure': trace['failure']}, ensure_ascii=False), flush=True)
    print('Validation ended; isolated server remains running for inspection/export.', flush=True)
    await server_task


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--port', type=int, default=62437)
    asyncio.run(main(parser.parse_args()))
