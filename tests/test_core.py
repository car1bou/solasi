import tempfile
import unittest
from pathlib import Path

import httpx
from lecture_study.config import AppConfig
from lecture_study.server import create_app


class CoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = AppConfig(data_dir=Path(self.temp.name), runtime_dir=Path(self.temp.name)/"runtime", port=8765)
        self.app = create_app(self.config)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://127.0.0.1:8765")
        self.origin = {"Origin": "http://127.0.0.1:8765"}

    async def asyncTearDown(self):
        await self.client.aclose()
        self.app.state.db.close()
        self.app.state.instance_lock.close()

    async def login(self):
        response = await self.client.post("/api/bootstrap", json={"token": self.app.state.bootstrap_token}, headers=self.origin)
        self.assertEqual(response.status_code, 200, response.text)
        self.headers = {**self.origin, "X-Session-Token": response.json()["csrf_token"]}
        return response

    async def test_session_persists_and_foreign_origin_denied(self):
        await self.login()
        course = await self.client.post("/api/courses", json={"title": "운영체제"}, headers=self.headers)
        self.assertEqual(course.status_code, 201, course.text)
        other = await self.client.post("/api/courses", json={"title": "운영체제"}, headers=self.headers)
        self.assertNotEqual(course.json()["id"], other.json()["id"])
        response = await self.client.post("/api/sessions", json={"kind": "lecture", "title": "프로세스", "course_id": course.json()["id"], "lecture_no": 1}, headers=self.headers)
        self.assertEqual(response.status_code, 201, response.text)
        session = response.json()
        self.app.state.instance_lock.close()
        new_app = create_app(self.config)
        self.addCleanup(new_app.state.instance_lock.close)
        self.addCleanup(new_app.state.db.close)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=new_app), base_url="http://127.0.0.1:8765") as client:
            token = (await client.post("/api/bootstrap", json={"token": new_app.state.bootstrap_token}, headers=self.origin)).json()["csrf_token"]
            saved = (await client.get(f'/api/sessions/{session["id"]}')).json()
            self.assertEqual(saved["id"], session["id"])
            self.assertEqual(saved["course_id"], course.json()["id"])
            denied = await client.get("/api/sessions", headers={"Origin": "https://attacker.example"})
            self.assertEqual(denied.status_code, 403)
            denied = await client.get("/api/sessions", headers={"Host": "attacker.example"})
            self.assertEqual(denied.status_code, 403)
            self.assertNotEqual((await client.get("/app.sqlite3")).status_code, 200)

    async def test_readiness_checks_managed_transcription_model(self):
        from unittest.mock import patch
        await self.login()
        runtime=self.config.runtime_dir
        for name in ('ffmpeg/bin/ffmpeg','build/whisper/bin/whisper-cli','models/ggml-large-v3-turbo.bin','models/ggml-silero-v6.2.0.bin'):
            path=runtime/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixture')
        with patch('lecture_study.transcription.verify_model') as verify,patch('lecture_study.server.verify_model',new=verify):
            result=(await self.client.get('/api/runtime/status')).json()
        asr=next(r for r in result if '전사' in r['label'])
        self.assertIn('large-v3-turbo',asr['label'])
        self.assertTrue(asr['ready'])
        self.assertEqual(verify.call_count,2)
        (runtime/'models/ggml-large-v3-turbo.bin').unlink()
        self.assertFalse(next(r for r in (await self.client.get('/api/runtime/status')).json() if '전사' in r['label'])['ready'])

    async def test_bootstrap_is_one_use_and_mutations_need_token(self):
        login_response = await self.login()
        again = await self.client.post("/api/bootstrap", json={"token": self.app.state.bootstrap_token}, headers=self.origin)
        self.assertEqual(again.status_code, 403)
        self.assertEqual((await self.client.post("/api/courses", json={"title": "x"}, headers=self.origin)).status_code, 403)
        self.assertIn("httponly", login_response.headers["set-cookie"].lower())
        self.assertIn("samesite=strict", login_response.headers["set-cookie"].lower())

    async def test_invalid_course_and_missing_auth_rejected(self):
        self.assertEqual((await self.client.get("/api/sessions")).status_code, 403)
        await self.login()
        response = await self.client.post("/api/sessions", json={"kind": "lecture", "title": "x", "course_id": "missing"}, headers=self.headers)
        self.assertEqual(response.status_code, 404)
        response = await self.client.post("/api/courses", json={"title": " "}, headers=self.headers)
        self.assertEqual(response.status_code, 422)

    async def test_partial_old_schema_migrates_without_losing_asset(self):
        import sqlite3
        from lecture_study.db import open_db
        root=Path(self.temp.name)/"migration";root.mkdir()
        old=sqlite3.connect(root/"app.sqlite3")
        old.executescript("""CREATE TABLE assets(id TEXT PRIMARY KEY,filename TEXT NOT NULL,kind TEXT NOT NULL,sha256 TEXT NOT NULL,size INTEGER NOT NULL,
           status TEXT NOT NULL,extraction TEXT,error TEXT,created_at TEXT NOT NULL,external_path TEXT);
           INSERT INTO assets(id,filename,kind,sha256,size,status,created_at,external_path) VALUES ('kept','old.txt','txt','abc',3,'ready','2026-10-13','/tmp/old.txt');
           PRAGMA user_version=2;""")
        old.close()
        try: db=open_db(root)
        except Exception as exc: self.fail("기존 자료 마이그레이션 실패: "+str(exc))
        self.assertEqual(db.execute("SELECT external_path,version FROM assets WHERE id='kept'").fetchone()["external_path"],"/tmp/old.txt")
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0],19)
        db.close()

    async def test_v13_note_versions_migrate_with_unknown_anchor(self):
        from lecture_study.db import open_db,create_session
        from lecture_study.materials import save_note,list_materials
        root=Path(self.temp.name)/'v13';db=open_db(root)
        sid=create_session(db,'lecture','과거 메모',None,None).id
        save_note(db,sid,'원래 메모');second=save_note(db,sid,'두 번째 메모')
        from tests.legacy import legacy_fixture
        legacy_fixture(db,13)
        db.close();db=open_db(root)
        try:
            note=list_materials(db,sid)['note'];self.assertEqual(note['source_id'],second.id);self.assertEqual(note['text'],'두 번째 메모');self.assertIsNone(note['anchor_ms'])
            self.assertEqual(db.execute('SELECT count(*) FROM notes').fetchone()[0],2);self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],19)
            self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall())
        finally:db.close()

    async def test_two_ports_keep_independent_browser_cookies(self):
        await self.login()
        other=create_app(AppConfig(Path(self.temp.name)/'other',Path(self.temp.name)/'other/runtime',port=8766))
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=other),base_url='http://127.0.0.1:8766',cookies=self.client.cookies) as client:
                login=await client.post('/api/bootstrap',json={'token':other.state.bootstrap_token},headers={'Origin':'http://127.0.0.1:8766'})
                self.assertEqual(login.status_code,200);self.client.cookies.update(client.cookies)
                self.assertNotEqual(self.app.state.cookie_name,other.state.cookie_name)
                self.assertEqual((await self.client.get('/api/sessions')).status_code,200)
                self.assertEqual((await client.get('/api/sessions')).status_code,200)
        finally:other.state.db.close();other.state.instance_lock.close()

    async def test_v16_migration_preserves_extraction_and_backfills_course_membership(self):
        from lecture_study.db import open_db,create_session,now
        from tests.legacy import legacy_fixture
        root=Path(self.temp.name)/'v16';db=open_db(root)
        with db:db.execute('INSERT INTO courses VALUES (?,?,?,?)',('legacy-course','기존 과목','',now()))
        sid=create_session(db,'lecture','기존 수업','legacy-course',1).id
        with db:
            db.execute("INSERT INTO assets(id,filename,kind,sha256,size,status,extraction,created_at) VALUES ('legacy-asset','기존.txt','txt',?,3,'ready',?,?)",('a'*64,'{"pages":[]}',now()))
            db.execute('INSERT INTO session_assets VALUES (?,?)',(sid,'legacy-asset'))
        legacy_fixture(db,16)
        before=dict(db.execute("SELECT * FROM assets WHERE id='legacy-asset'").fetchone())
        db.close();db=open_db(root)
        try:
            after=dict(db.execute("SELECT * FROM assets WHERE id='legacy-asset'").fetchone())
            self.assertEqual({key:after[key] for key in before},before)
            self.assertEqual(after['extraction_sha256'],'a'*64)
            self.assertEqual([tuple(row) for row in db.execute('SELECT * FROM course_assets')],[('legacy-course','legacy-asset')])
            self.assertEqual([tuple(row) for row in db.execute('SELECT * FROM session_assets')],[(sid,'legacy-asset')])
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],19)
            self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall())
        finally:db.close()


if __name__ == "__main__":
    unittest.main()
