import json,struct,tempfile,unittest
from pathlib import Path
import httpx
from lecture_study.db import open_db,create_session
from lecture_study.materials import save_note
from lecture_study.retrieval import sync_embeddings,index_status

class SyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_incremental_idempotent_and_model_change(self):
        with tempfile.TemporaryDirectory() as folder:
            db=open_db(Path(folder));self.addCleanup(db.close);sid=create_session(db,'lecture','과목',None,None).id
            calls=[];digest=['a'*64]
            def respond(r):
                if r.url.path=='/api/tags':return httpx.Response(200,json={'models':[{'name':'embeddinggemma','digest':digest[0]}]})
                if r.url.path=='/api/show':return httpx.Response(200,json={'capabilities':['embedding']})
                calls.append(json.loads(r.content));return httpx.Response(200,json={'embeddings':[[1,0]]})
            async with httpx.AsyncClient(base_url='http://127.0.0.1:11434',transport=httpx.MockTransport(respond)) as client:
                save_note(db,sid,'교착 상태 mutex')
                await sync_embeddings(db,'embeddinggemma',client);first=index_status(db);self.assertEqual(len(calls),1)
                await sync_embeddings(db,'embeddinggemma',client);self.assertEqual(len(calls),1)
                save_note(db,sid,'새로운 교착 상태')
                await sync_embeddings(db,'embeddinggemma',client);self.assertEqual(len(calls),2);self.assertEqual(index_status(db)['index_id'],first['index_id'])
                self.assertEqual(index_status(db)['unindexed_chunks'],0)
                digest[0]='b'*64
                await sync_embeddings(db,'embeddinggemma',client);self.assertNotEqual(index_status(db)['index_id'],first['index_id']);self.assertEqual(len(calls),3)

    async def test_new_index_pause_resumes_without_reembedding_completed_chunks(self):
        with tempfile.TemporaryDirectory() as folder:
            db=open_db(Path(folder));self.addCleanup(db.close);sid=create_session(db,'lecture','재개',None,None).id
            save_note(db,sid,'가'*600)
            calls=[]
            def respond(r):
                if r.url.path=='/api/tags':return httpx.Response(200,json={'models':[{'name':'embeddinggemma','digest':'c'*64}]})
                calls.append(1);return httpx.Response(200,json={'embeddings':[[1,0]]})
            async with httpx.AsyncClient(base_url='http://127.0.0.1:11434',transport=httpx.MockTransport(respond)) as client:
                paused=await sync_embeddings(db,'embeddinggemma',client,batch_limit=1)
                self.assertTrue(paused['paused']);self.assertFalse(index_status(db)['ready']);self.assertEqual(len(calls),1)
                await sync_embeddings(db,'embeddinggemma',client,can_continue=lambda:False)
                self.assertEqual(len(calls),1)
                await sync_embeddings(db,'embeddinggemma',client)
                self.assertEqual(len(calls),2);self.assertTrue(index_status(db)['ready'])

    async def test_process_restart_preserves_complete_chunks_for_incremental_resume(self):
        from lecture_study.server import create_app
        from lecture_study.config import AppConfig
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);db=open_db(root/'vault');sid=create_session(db,'lecture','재시작',None,None).id
            save_note(db,sid,'가'*600);calls=[]
            def respond(r):
                if r.url.path=='/api/tags':return httpx.Response(200,json={'models':[{'name':'embeddinggemma','digest':'d'*64}]})
                calls.append(1);return httpx.Response(200,json={'embeddings':[[1,0]]})
            async with httpx.AsyncClient(base_url='http://127.0.0.1:11434',transport=httpx.MockTransport(respond)) as client:
                await sync_embeddings(db,'embeddinggemma',client,batch_limit=1)
                original=db.execute("SELECT id FROM embedding_sets WHERE status='building'").fetchone()[0]
                db.close()
                app=create_app(AppConfig(root/'vault',root/'runtime',embedded=True))
                self.addCleanup(app.state.instance_lock.close);self.addCleanup(app.state.db.close)
                await sync_embeddings(app.state.db,'embeddinggemma',client)
                self.assertEqual(index_status(app.state.db)['index_id'],original)
                self.assertEqual(len(calls),2,'completed chunk was embedded again after restart')

    def test_build_progress_counts_current_chunks_without_activating_partial_index(self):
        from lecture_study.second_brain import embedding_progress
        with tempfile.TemporaryDirectory() as folder:
            db=open_db(Path(folder));self.addCleanup(db.close)
            sid=create_session(db,'lecture','진행',None,None).id;save_note(db,sid,'가'*600)
            chunk=db.execute('SELECT id FROM searchable_chunks LIMIT 1').fetchone()[0]
            with db:
                db.execute("INSERT INTO embedding_sets VALUES ('partial','embeddinggemma',?,2,'fixture','building','now')",('a'*64,))
                for part in range(2):db.execute('INSERT INTO embeddings VALUES (?,?,?,?)',('partial',chunk,part,struct.pack('<ff',1,0)))
            self.assertEqual(embedding_progress(db),{'model':'embeddinggemma','completed_chunks':1,'total_chunks':2})
            self.assertFalse(index_status(db)['ready'])
