"""Recheck real local summary against an unchanged, disposable ASR snapshot."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sqlite3
import time

import httpx

from lecture_study import answers, outputs, providers, server
from lecture_study.config import AppConfig


def text_digest(evidence):
    return hashlib.sha256(json.dumps([e['text'] for e in evidence], ensure_ascii=False).encode()).hexdigest()


async def main(source, target):
    if not (source / '.long-file-validation').is_file() or target.exists():
        raise ValueError('완료된 긴 음성 검증 폴더와 새 출력 폴더가 필요합니다')
    previous = json.loads((source / 'trace.json').read_text())
    assert previous['ready'] and previous['post_run']['all_jobs_done']
    target.mkdir(parents=True, mode=0o700)
    data, runtime = target / 'data', target / 'runtime'
    data.mkdir(mode=0o700)
    runtime.mkdir(mode=0o700)
    with sqlite3.connect((source / 'data/app.sqlite3').resolve().as_uri() + '?mode=ro', uri=True) as old:
        frozen = json.loads(old.execute('SELECT request FROM jobs WHERE id=?', (previous['final_summary_job_id'],)).fetchone()[0])
        with sqlite3.connect(data / 'app.sqlite3') as copied:
            old.backup(copied)
    expected = text_digest(frozen['evidence'])
    for name in ('asr', 'ffmpeg', 'models', 'ollama', 'ollama-models', 'tessdata'):
        origin = source / 'runtime' / name
        if origin.exists():
            (runtime / name).symlink_to(origin.resolve(), target_is_directory=origin.is_dir())
    calls = []
    original = answers.generate
    checked_body = providers.checked_body
    responses = []

    def recorded_response(response):
        body = checked_body(response)
        if isinstance(body, dict) and 'message' in body and 'done' in body:
            responses.append({k: body[k] for k in ('done', 'done_reason', 'message', 'prompt_eval_count', 'eval_count') if k in body})
            (target / 'private-provider-responses.json').write_text(json.dumps(responses, ensure_ascii=False, indent=2))
        return body

    providers.checked_body = recorded_response

    async def measured(*args, **kwargs):
        started = time.monotonic()
        result = await original(*args, **kwargs)
        calls.append({'seconds': time.monotonic() - started, 'digest': result.digest, 'usage': result.usage})
        return result

    answers.generate = outputs.generate = measured
    app = server.create_app(AppConfig(data, runtime, port=62439))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:62439', headers={'Origin': 'http://127.0.0.1:62439'}) as client:
            async def request(method, path, body=None):
                response = await client.request(method, '/api' + path, json=body)
                response.raise_for_status()
                return response.json()

            login = await request('POST', '/bootstrap', {'token': app.state.bootstrap_token})
            client.headers['X-Session-Token'] = login['csrf_token']
            try:
                await request('POST', '/local/connect', {'mode': 'managed'})
                checked = await request('POST', '/models/check')
                assert checked['accessible'] and checked['digest'] == previous['model_check']['digest']
                started = time.monotonic()
                job = await request('POST', '/ai/jobs', {'session_id': previous['session_id'], 'kind': 'summary', 'prompt': frozen['request']['prompt'], 'scope': frozen['request']['scope'], 'web': False})
                while job['status'] in ('queued', 'running'):
                    assert time.monotonic() - started < 1800, '요약 재검증 시간 초과'
                    await asyncio.sleep(.5)
                    job = await request('GET', '/jobs/' + job['id'])
                assert job['status'] == 'done', job.get('error')
                elapsed = time.monotonic() - started
                artifact = await request('GET', '/artifacts/' + job['result']['id'])
                assert text_digest(artifact['evidence']) == expected
                assert artifact['metadata']['digest'] == checked['digest']
                body = artifact['body']
                exact_quotes = None
                if body.get('summary_format') == 'excerpts-v1':
                    sources = {e['ref']['id']: e['text'] for e in artifact['evidence']}
                    exact_quotes = 0
                    for section in body['sections']:
                        assert not {'subject', 'event_type'} & section.keys()
                        assert section['title'] == '핵심 원문'
                        assert section['text'] == '\n'.join(q['text'] for q in section['quotes'])
                        for quote in section['quotes']:
                            assert len(quote['evidence_ids']) == 1 and quote['text']
                            assert quote['text'] in sources[quote['evidence_ids'][0]]
                            exact_quotes += 1
                    response = await client.get('/api/artifacts/' + artifact['id'] + '/export')
                    response.raise_for_status()
                    assert any(line in ('원문 발췌', '원문 발췌 · 구간 선택 확인 필요') for line in response.text.splitlines())
                    assert not any(line.startswith('주어: ') or line == '원문 발췌 · 생성 해석 확인 필요' for line in response.text.splitlines())
                    (target / 'private-export.md').write_text(response.text)
                report = {'route': 'ASGI production APIs on SQLite backup; real owned Ollama, no ASR rerun or UI', 'same_asr_text_sha256': expected, 'model_digest': checked['digest'], 'model': previous['model'], 'elapsed_seconds': elapsed, 'source_count': len(artifact['evidence']), 'completed_parts': body['completed_parts'], 'covered_source_count': len(body['covered_source_ids']), 'cited_source_count': len(body['cited_source_ids']), 'unquoted_source_count': len(body['unquoted_sources']), 'section_count': len(body['sections']), 'review_required_section_count': sum(bool(s.get('review_required')) for s in body['sections']), 'selection_incomplete_parts': body.get('selection_incomplete_parts', []), 'generation_calls': calls}
                report.update(summary_format=body.get('summary_format'), exact_source_quote_count=exact_quotes)
                encoded = json.dumps(report, ensure_ascii=False, indent=2)
                assert all(secret not in encoded for secret in (job['id'], artifact['id'], previous['session_id'], login['csrf_token'], '/Users/', '127.0.0.1'))
                (target / 'report.json').write_text(encoded)
                (target / 'private-result.json').write_text(json.dumps({'job_id': job['id'], 'artifact_id': artifact['id']}))
                print(encoded, flush=True)
            finally:
                try:
                    await request('POST', '/local/disconnect')
                finally:
                    answers.generate = outputs.generate = original
                    providers.checked_body = checked_body


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('target', type=Path)
    args = parser.parse_args()
    asyncio.run(main(args.source.resolve(), args.target.resolve()))
