"""Focused checks for the disposable native QA server; no model or UI starts."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

from fastapi.testclient import TestClient

try:
    from experiments.serve_native_validation import create_validation_app
except ModuleNotFoundError:
    create_validation_app = None


class NativeValidationTests(unittest.TestCase):
    def test_qa_navigation_serves_staged_ui_and_storage_fixture_assets(self):
        self.assertIsNotNone(create_validation_app)
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            frontend = folder / 'staging';frontend.mkdir();(frontend / 'index.html').write_text('<body><div id="root">staged UI</div></body>')
            fixture = folder / 'storage';(fixture / 'tests').mkdir(parents=True);(fixture / 'assets').mkdir()
            (fixture / 'tests/ink-storage-fixture.html').write_text('<body>storage test<script src="/assets/ink.js"></script></body>')
            (fixture / 'assets/ink.js').write_text('globalThis.fixtureAsset=true;')
            app, _ = create_validation_app(folder, folder / 'runtime', 62435, frontend=frontend, storage_fixture=fixture)
            with TestClient(app, base_url='http://127.0.0.1:62435') as client:
                index = client.get('/')
                self.assertIn('staged UI', index.text)
                self.assertIn('href="/fixture"', index.text)
                self.assertIn('src="/fixture-assets/ink.js"', client.get('/tests/ink-storage-fixture.html').text)
                self.assertEqual(client.get('/fixture-assets/ink.js').text, 'globalThis.fixtureAsset=true;')
                self.assertIn('저장 실패 켜기', client.get('/fixture').text)
                self.assertEqual(client.get('/fixture-controls.js').status_code, 200)

    def test_compiled_shim_enters_tmp_and_executes_exact_python_command(self):
        from experiments import serve_native_validation as validation
        self.assertTrue(hasattr(validation, 'build_exec_shim'), 'Native QA needs a shell-free executable shim')
        with tempfile.TemporaryDirectory(prefix='solasi shim ') as directory:
            folder = Path(directory)
            probe = folder / 'probe.py'
            probe.write_text('import json,os,sys; print(json.dumps({"cwd":os.getcwd(),"args":sys.argv[1:]})); sys.exit(23)')
            manifest = folder / 'settings with spaces.json'
            shim = validation.build_exec_shim(folder, sys.executable, probe, manifest)
            result = subprocess.run([str(shim), '-m', 'ignored-native-launcher'], cwd=folder, capture_output=True, text=True, timeout=1)
            self.assertEqual(result.returncode, 23, result.stderr)
            self.assertEqual(json.loads(result.stdout), {'cwd': '/private/tmp', 'args': ['serve', str(manifest)]})

    def test_build_refuses_existing_output_without_touching_it(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            kept = folder / 'existing-export.json'
            kept.write_text('preserve me')
            result = subprocess.run([sys.executable, str(Path(__file__).with_name('serve_native_validation.py')), 'build', str(folder), '--runtime', str(folder)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Use a new disposable output folder', result.stderr)
            self.assertEqual(kept.read_text(), 'preserve me')
            self.assertEqual([p.name for p in folder.iterdir()], ['existing-export.json'])

    def test_serve_rejects_unmarked_data_before_starting_any_server(self):
        from experiments.serve_native_validation import serve
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            manifest = folder / 'validation.json'
            manifest.write_text(json.dumps({'folder': str(folder)}))
            with self.assertRaisesRegex(ValueError, 'marker is missing'):
                serve(manifest)
            self.assertEqual([p.name for p in folder.iterdir()], ['validation.json'])

    def test_injected_failure_preserves_the_last_saved_page_and_keeps_auth(self):
        self.assertIsNotNone(create_validation_app, 'Disposable native QA server is missing')
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            app, info = create_validation_app(folder, folder / 'runtime', 62435)
            with TestClient(app, base_url='http://127.0.0.1:62435', headers={'Origin': 'http://127.0.0.1:62435'}) as client:
                self.assertEqual(client.get('/api/fixture/fail-page-writes').status_code, 403)
                bootstrap = client.post('/api/bootstrap', json={'token': app.state.bootstrap_token})
                headers = {'X-Session-Token': bootstrap.json()['csrf_token']}
                flag = '/api/fixture/fail-page-writes'
                self.assertEqual(client.post(flag, json={'enabled': True}).status_code, 403)
                self.assertEqual(client.get(flag).json(), {'enabled': False, 'failures': 0})
                path = f"/api/courses/{info['course_id']}/assets/{info['asset_id']}/pages/1/document"
                body = {'document_sha256': info['document_sha256'], 'expected_revision': 0, 'text': 'kept note', 'ink': []}
                saved = client.put(path, headers=headers, json=body)
                self.assertEqual(saved.status_code, 200, saved.text)
                self.assertEqual(saved.json()['revision'], 1)
                self.assertEqual(client.post(flag, headers=headers, json={'enabled': True}).status_code, 200)
                body.update(expected_revision=1, text='unsaved draft')
                failed = client.put(path, headers=headers, json=body)
                self.assertEqual(failed.status_code, 503, failed.text)
                current = client.get(path, params={'document_sha256': info['document_sha256']}).json()
                self.assertEqual((current['revision'], current['text']), (1, 'kept note'))
                self.assertEqual(client.get(flag).json(), {'enabled': True, 'failures': 1})
                self.assertEqual(client.post(flag, headers=headers, json={'enabled': False}).status_code, 200)
                retry = client.put(path, headers=headers, json=body)
                self.assertEqual(retry.status_code, 200, retry.text)
                self.assertEqual((retry.json()['revision'], retry.json()['text']), (2, 'unsaved draft'))
                self.assertEqual(client.get('/').status_code, 200)
            self.assertTrue((folder / 'data/app.sqlite3').is_file())
            self.assertFalse((folder / 'runtime').exists())


if __name__ == '__main__':
    unittest.main()
