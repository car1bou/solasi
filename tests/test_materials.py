import asyncio
import base64
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from lecture_study.config import AppConfig
from lecture_study.server import create_app


class MaterialsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/"app"
        self.sources = Path(self.temp.name)/"chosen"
        self.config = AppConfig(self.root,self.root/"runtime",port=8765)
        self.app = create_app(self.config)
        self.db = self.app.state.db
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://127.0.0.1:8765")
        origin = {"Origin": "http://127.0.0.1:8765"}
        login = await self.client.post("/api/bootstrap", json={"token": self.app.state.bootstrap_token}, headers=origin)
        self.headers = {**origin, "X-Session-Token": login.json()["csrf_token"]}
        created = await self.client.post("/api/sessions", json={"kind":"lecture","title":"자료"}, headers=self.headers)
        self.session_id = created.json()["id"]

    async def asyncTearDown(self):
        if hasattr(self.app.state, "tasks"):
            await asyncio.gather(*self.app.state.tasks, return_exceptions=True)
        await self.client.aclose()
        self.db.close()
        self.app.state.instance_lock.close()

    async def select(self, filename, content):
        path = self.sources/filename
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(content)
        with patch("lecture_study.server.select_files",return_value=[path]):
            return await self.client.post(f"/api/sessions/{self.session_id}/files/select",headers=self.headers)

    async def test_partial_pdf_has_original_page_refs(self):
        from lecture_study.materials import normalize_result
        page = lambda n: SimpleNamespace(page_num=n,width=600,height=800,text=f"page {n}",text_items=[])
        raw = SimpleNamespace(total_pages=3,pages=[page(1),page(3)],images=[],page_errors=[])
        result = normalize_result(raw,"asset",self.root,True)
        self.assertEqual(result.status,"partial")
        self.assertEqual(result.total_pages,3)
        self.assertEqual([p.page for p in result.pages],[1,3])
        self.assertTrue(any(e["page"]==2 for e in result.page_errors))

    async def test_official_markdown_layout_preserves_ocr_reading_order(self):
        from lecture_study.materials import normalize_result
        raw = SimpleNamespace(total_pages=1,pages=[SimpleNamespace(page_num=1,width=600,height=800,text="세스와 스레드\n프 로",markdown="프로세스와 스레드",text_items=[])],images=[],page_errors=[])
        result = normalize_result(raw,"asset",self.root,True)
        self.assertEqual(result.pages[0].text,"프로세스와 스레드")

    async def test_file_access_boundary_without_copy(self):
        response = await self.select("x.md","전문용어와 노트".encode())
        self.assertEqual(response.status_code,201,response.text)
        asset = response.json()[0]["asset"]
        self.assertFalse((self.root/"assets"/asset["id"]/"original.md").exists())
        self.assertTrue((self.sources/"x.md").exists())
        self.assertEqual(asset["filename"],"x.md")
        self.assertNotIn("external_path",asset)
        self.assertNotIn("/",asset["id"])
        original = await self.client.get(f'/api/assets/{asset["id"]}/original')
        self.assertTrue(original.headers["content-disposition"].startswith("inline"))
        self.assertTrue(original.headers["content-type"].startswith("text/plain"))
        arbitrary = await self.client.post("/api/assets",json={"path":"/etc/passwd"},headers=self.headers)
        self.assertNotIn(arbitrary.status_code,(200,201))
        disguised = await self.select("image.pdf",base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9WQAAAAASUVORK5CYII="))
        self.assertEqual(disguised.status_code,201,disguised.text)
        self.assertEqual(disguised.json()[0]["asset"]["kind"],"png")
        from lecture_study import materials
        with patch.object(materials,"MAX_MATERIAL_BYTES",3):
            self.assertEqual((await self.select("x.txt",b"long")).status_code,413)
        self.assertEqual((await self.select("x.txt",b"\xff\xfe")).status_code,422)
        with patch("lecture_study.server.select_files",return_value=[]):
            cancelled = await self.client.post(f"/api/sessions/{self.session_id}/files/select",headers=self.headers)
        self.assertEqual(cancelled.json(),[])

    async def test_app_cache_cannot_become_external_original(self):
        path = self.root/"cache.txt"
        path.write_text("cached",encoding="utf-8")
        with patch("lecture_study.server.select_files",return_value=[path]):
            response = await self.client.post(f"/api/sessions/{self.session_id}/files/select",headers=self.headers)
        self.assertEqual(response.status_code,422,response.text)
        self.assertTrue(path.exists())

    async def test_missing_or_changed_file_does_not_show_stale_page(self):
        response = await self.select("mutable.txt",b"first")
        self.assertEqual(response.status_code,201,response.text)
        await asyncio.gather(*self.app.state.tasks,return_exceptions=True)
        asset_id = response.json()[0]["asset"]["id"]
        original = self.sources/"mutable.txt"
        original.write_text("changed",encoding="utf-8")
        state = (await self.client.get(f"/api/sessions/{self.session_id}/materials")).json()
        self.assertEqual(state["assets"][0]["source_status"],"changed")
        old_id = state["assets"][0]["extraction"]["pages"][0]["ref"]["id"]
        retry = await self.client.post(f"/api/sessions/{self.session_id}/assets/{asset_id}/extract",headers=self.headers)
        self.assertEqual(retry.status_code,201,retry.text)
        await asyncio.gather(*self.app.state.tasks,return_exceptions=True)
        updated = (await self.client.get(f"/api/sessions/{self.session_id}/materials")).json()["assets"][0]
        self.assertEqual(updated["source_status"],"current")
        self.assertEqual(updated["version"],2)
        self.assertEqual(updated["extraction"]["pages"][0]["text"],"changed")
        self.assertEqual(self.db.execute("SELECT text_snapshot FROM sources WHERE id=?",(old_id,)).fetchone()[0],"first")
        again = await self.client.post(f"/api/sessions/{self.session_id}/assets/{asset_id}/extract",headers=self.headers)
        self.assertEqual(again.status_code,201,again.text)
        await asyncio.gather(*self.app.state.tasks,return_exceptions=True)
        latest = (await self.client.get(f"/api/sessions/{self.session_id}/materials")).json()["assets"][0]
        self.assertEqual(latest["version"],3)
        original.unlink()
        state = (await self.client.get(f"/api/sessions/{self.session_id}/materials")).json()
        self.assertEqual(state["assets"][0]["source_status"],"missing")
        self.assertEqual((await self.client.get(f"/api/assets/{asset_id}/original")).status_code,409)

    async def test_restart_marks_pending_parse_retryable(self):
        response = await self.select("restart.txt",b"saved")
        await asyncio.gather(*self.app.state.tasks,return_exceptions=True)
        asset = response.json()[0]["asset"]
        job_id = response.json()[0]["job"]["id"]
        with self.db:
            self.db.execute("UPDATE assets SET status='running' WHERE id=?",(asset["id"],))
            self.db.execute("UPDATE jobs SET status='running' WHERE id=?",(job_id,))
        self.app.state.instance_lock.close()
        restarted = create_app(self.config)
        self.addCleanup(restarted.state.instance_lock.close)
        try:
            row = restarted.state.db.execute("SELECT status FROM assets WHERE id=?",(asset["id"],)).fetchone()
            self.assertEqual(row[0],"failed")
            self.assertEqual(restarted.state.db.execute("SELECT status FROM jobs WHERE id=?",(job_id,)).fetchone()[0],"interrupted")
        finally:
            restarted.state.db.close()

    async def test_cache_budget_never_touches_original(self):
        from lecture_study import materials
        from tests.fixtures import pdf_fixture
        response = await self.select("cache.pdf",pdf_fixture())
        await asyncio.gather(*self.app.state.tasks,return_exceptions=True)
        ident = response.json()[0]["asset"]["id"]
        with patch.object(materials,"MAX_CACHE_BYTES",1):
            image = await self.client.get(f"/api/assets/{ident}/pages/1")
            self.assertEqual(image.status_code,200)
            self.assertTrue(image.content.startswith(b"\x89PNG"))
            self.assertFalse((self.root/"assets"/ident/"v1-page-1.png").exists())
        self.assertTrue((self.sources/"cache.pdf").exists())

    async def test_real_pdf_png_and_utf8_extraction(self):
        from tests.fixtures import pdf_fixture,png_fixture
        from lecture_study.materials import render_page
        for filename,content in [("fixture.pdf",pdf_fixture()),("fixture.png",png_fixture()),("fixture.txt","메모리 관리와 프로세스".encode())]:
            response = await self.select(filename,content)
            self.assertEqual(response.status_code,201,response.text)
            body = response.json()[0]
            await asyncio.gather(*self.app.state.tasks,return_exceptions=True)
            job = (await self.client.get(f'/api/jobs/{body["job"]["id"]}')).json()
            self.assertEqual(job["status"],"done",job)
            result = job["result"]
            if filename.endswith("pdf"):
                self.assertEqual([p["page"] for p in result["pages"]],[1,2,3])
                self.assertIn("Lecture page 3",result["pages"][2]["text"])
                self.assertGreater(result["pages"][0]["items"][0]["bbox"][2],0)
                self.assertGreater(len(result["images"]),0)
                self.assertFalse((self.root/"assets"/body["asset"]["id"]/result["images"][0]["path"]).exists())
                image = await self.client.get(f'/api/assets/{body["asset"]["id"]}/images/0')
                self.assertEqual(image.status_code,200,image.text)

                path = await render_page(self.db,body["asset"]["id"],3,self.root/"runtime")
                self.assertTrue(path.read_bytes().startswith(b"\x89PNG"))
            elif filename.endswith("txt"):
                self.assertIn("메모리",result["pages"][0]["text"])
            else:
                self.assertEqual(result["total_pages"],1)

    async def test_failed_parse_preserves_original_and_note_versions(self):
        response = await self.select("broken.pdf",b"%PDF-1.7\nbroken")
        self.assertEqual(response.status_code,201,response.text)
        await asyncio.gather(*self.app.state.tasks,return_exceptions=True)
        body = response.json()[0]
        job = (await self.client.get(f'/api/jobs/{body["job"]["id"]}')).json()
        self.assertEqual(job["status"],"failed")
        self.assertTrue((self.sources/"broken.pdf").is_file())
        first = await self.client.put(f"/api/sessions/{self.session_id}/note",json={"text":"첫 내용"},headers=self.headers)
        second = await self.client.put(f"/api/sessions/{self.session_id}/note",json={"text":"수정 내용"},headers=self.headers)
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(second.json()["version"],2)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM notes").fetchone()[0],2)
        saved = (await self.client.get(f"/api/sessions/{self.session_id}/materials")).json()
        self.assertEqual(saved["note"]["text"],"수정 내용")


if __name__=="__main__":
    unittest.main()
