import asyncio
import json
import unittest
from unittest.mock import patch
from tests import test_materials as fixture


class MaterialRecoveryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.MaterialsTests.asyncSetUp
    asyncTearDown = fixture.MaterialsTests.asyncTearDown
    select = fixture.MaterialsTests.select

    async def original(self):
        response = await self.select('original.txt', '강의 원문'.encode())
        await asyncio.gather(*self.app.state.tasks, return_exceptions=True)
        return response.json()[0]['asset']

    async def reconnect(self, asset, paths, owner=None):
        with patch('lecture_study.server.select_files', return_value=paths):
            return await self.client.post(f'/api/sessions/{owner or self.session_id}/files/select', json={'reconnect_asset_id': asset['id']}, headers=self.headers)

    async def test_moved_identical_original_retains_id_sources_and_page_ink(self):
        asset = await self.original()
        course = (await self.client.post('/api/courses', json={'title':'보존'}, headers=self.headers)).json()['id']
        digest = asset['sha256']
        with self.db:
            self.db.execute('INSERT INTO asset_documents VALUES (?,?,?,?)', (asset['id'],digest,'{}','before'))
            self.db.execute('INSERT INTO page_documents VALUES (?,?,?,?,?,?)', ('doc',course,asset['id'],digest,1,1))
            self.db.execute('INSERT INTO page_document_revisions VALUES (?,?,?,?,?,?)', ('doc',1,'메모','[{"tool":"pen","points":[{"x":0.1,"y":0.2}]}]',self.db.execute('SELECT id FROM sources LIMIT 1').fetchone()[0],'before'))
        before = {t:[tuple(r) for r in self.db.execute('SELECT * FROM '+t)] for t in ('sources','page_documents','page_document_revisions','session_assets','course_assets')}
        moved = self.sources/'renamed.txt'
        (self.sources/'original.txt').rename(moved)
        response = await self.reconnect(asset,[moved])
        self.assertEqual(response.status_code,201,response.text)
        restored = response.json()[0]['asset']
        self.assertEqual((restored['id'],restored['sha256'],restored['version'],restored['source_status']), (asset['id'],digest,asset['version'],'current'))
        self.assertIsNone(response.json()[0]['job'])
        for table,rows in before.items(): self.assertEqual([tuple(r)for r in self.db.execute('SELECT * FROM '+table)],rows,table)
        self.assertEqual((await self.client.get(f'/api/assets/{asset["id"]}/original')).text,'강의 원문')
        self.assertEqual(self.db.execute('SELECT count(*) FROM assets').fetchone()[0],1)

    async def test_different_content_managed_path_and_multiple_files_do_not_mutate_asset(self):
        asset = await self.original()
        before = tuple(self.db.execute('SELECT * FROM assets').fetchone())
        different = self.sources/'other.txt';different.write_text('다른 강의')
        cached = self.root/'copy.txt';cached.write_text('강의 원문')
        for paths in ([different],[cached],[different,self.sources/'original.txt']):
            response = await self.reconnect(asset,paths)
            self.assertEqual(response.status_code,422,response.text)
            self.assertEqual(tuple(self.db.execute('SELECT * FROM assets').fetchone()),before)
        self.assertEqual((await self.reconnect(asset,[])).json(),[])
        self.assertEqual(tuple(self.db.execute('SELECT * FROM assets').fetchone()),before)

    async def test_unlinked_owner_and_other_asset_path_are_rejected(self):
        asset=await self.original()
        owner=(await self.client.post('/api/sessions',json={'kind':'meeting','title':'다른 회차'},headers=self.headers)).json()['id']
        response=await self.reconnect(asset,[self.sources/'original.txt'],owner)
        self.assertEqual(response.status_code,404,response.text)
        other=await self.select('duplicate.txt','강의 원문'.encode())
        await asyncio.gather(*self.app.state.tasks,return_exceptions=True)
        self.assertEqual(other.status_code,201)
        before=[tuple(r) for r in self.db.execute('SELECT * FROM assets')]
        response=await self.reconnect(asset,[self.sources/'duplicate.txt'])
        self.assertEqual(response.status_code,422,response.text)
        self.assertEqual([tuple(r)for r in self.db.execute('SELECT * FROM assets')],before)

    async def test_course_reconnect_and_active_extraction_guard(self):
        asset=await self.original()
        course=(await self.client.post('/api/courses',json={'title':'과목'},headers=self.headers)).json()['id']
        with self.db:self.db.execute('INSERT INTO course_assets VALUES (?,?)',(course,asset['id']))
        from lecture_study.jobs import submit_job
        job=submit_job(self.db,self.session_id,'parse',{'asset_id':asset['id']})
        response=await self.reconnect(asset,[self.sources/'original.txt'])
        self.assertEqual(response.status_code,422,response.text)
        with self.db:self.db.execute("UPDATE jobs SET status='cancelled' WHERE id=?",(job['id'],))
        with patch('lecture_study.server.select_files',return_value=[self.sources/'original.txt']):
            response=await self.client.post(f'/api/courses/{course}/files/select',json={'reconnect_asset_id':asset['id']},headers=self.headers)
        self.assertEqual(response.status_code,201,response.text)
