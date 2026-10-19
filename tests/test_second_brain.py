import tempfile,unittest,json
from pathlib import Path
from lecture_study.db import open_db,create_session,new_id,now
from lecture_study.materials import save_note
from lecture_study.second_brain import reconcile,next_background_work,background_idle,related_sources
from lecture_study.models import Scope

class BrainTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.db=open_db(Path(self.temp.name));self.addCleanup(self.db.close)
        self.cid=new_id()
        with self.db:self.db.execute('INSERT INTO courses VALUES (?,?,?,?)',(self.cid,'과목','',now()))
        self.old=create_session(self.db,'lecture','이전',self.cid,1).id;self.sid=create_session(self.db,'lecture','현재',self.cid,2).id
    async def test_latest_sources_dedup_and_same_course(self):
        old=save_note(self.db,self.old,'교착 상태 mutex 조건')
        stale=save_note(self.db,self.sid,'교착 상태 수정 전');current=save_note(self.db,self.sid,'교착 상태 mutex 학습')
        other=create_session(self.db,'meeting','외부',None,None).id;save_note(self.db,other,'교착 상태 mutex')
        reconcile(self.db);reconcile(self.db)
        ids={r[0] for r in self.db.execute("SELECT source_id FROM brain_work WHERE kind='source' AND state='pending'")}
        self.assertIn(current.id,ids);self.assertNotIn(stale.id,ids)
        found=await related_sources(self.db,Scope(session_id=self.sid),current.id,None)
        self.assertEqual([x.ref.id for x in found.evidence],[old.id])
        self.assertTrue(background_idle(self.db))
        with self.db:self.db.execute("INSERT INTO settings VALUES ('second_brain_auto','false')")
        self.assertIsNone(next_background_work(self.db))
    def test_user_request_priority(self):
        from lecture_study.jobs import submit_job
        save_note(self.db,self.sid,'교착 상태');reconcile(self.db)
        submit_job(self.db,self.sid,'ai',{})
        self.assertFalse(background_idle(self.db));self.assertIsNone(next_background_work(self.db))

    async def test_external_calls_require_explicit_and_invalid_quotes_are_rejected(self):
        from unittest.mock import patch,AsyncMock
        from lecture_study.second_brain import propose_concepts
        from lecture_study.models import ProviderConfig,ProviderResult
        ref=save_note(self.db,self.sid,'교착 상태는 조건이다.')
        api=ProviderConfig(provider='openai',model='gpt-test')
        with patch('lecture_study.providers.generate',new=AsyncMock()) as generate:
            with self.assertRaises(ValueError):await propose_concepts(self.db,ref.id,api)
            generate.assert_not_called()
        result=ProviderResult(text=json.dumps({'concepts':[{'canonical':'교착','quote':'원문에 없는 문장'}]}),model='test',usage={},elapsed_ms=1)
        with patch('lecture_study.providers.generate',new=AsyncMock(return_value=result)):
            with self.assertRaises(ValueError):await propose_concepts(self.db,ref.id,api,True)
        self.assertEqual(self.db.execute('SELECT count(*) FROM concept_proposals').fetchone()[0],0)

    async def test_rejected_candidate_is_not_resurrected(self):
        from unittest.mock import patch,AsyncMock
        from lecture_study.second_brain import propose_concepts
        from lecture_study.models import ProviderConfig,ProviderResult
        ref=save_note(self.db,self.sid,'교착 상태는 조건이다.')
        result=ProviderResult(text=json.dumps({'concepts':[{'canonical':'교착 상태','quote':'교착 상태는 조건이다.'}]}),model='test',usage={},elapsed_ms=1)
        with patch('lecture_study.providers.generate',new=AsyncMock(return_value=result)):
            await propose_concepts(self.db,ref.id,ProviderConfig(provider='local'))
            with self.db:self.db.execute("UPDATE concept_proposals SET status='rejected'")
            await propose_concepts(self.db,ref.id,ProviderConfig(provider='local'))
        self.assertEqual(self.db.execute('SELECT status FROM concept_proposals').fetchone()[0],'rejected')

    async def test_corpus_change_requeues_previous_neighbors(self):
        a=save_note(self.db,self.old,'교착 상태');reconcile(self.db)
        with self.db:self.db.execute("UPDATE brain_work SET state='done',result='{}'")
        save_note(self.db,self.sid,'교착 상태 조건');reconcile(self.db)
        states={r[0] for r in self.db.execute('SELECT state FROM brain_work WHERE source_id=?',(a.id,))}
        self.assertEqual(states,{'pending'})

    async def test_background_admission_rechecks_user_priority(self):
        from lecture_study.second_brain import admit_background,BackgroundDeferred
        from lecture_study.jobs import submit_job
        await admit_background(self.db)
        submit_job(self.db,self.sid,'ai',{})
        with self.assertRaises(BackgroundDeferred):await admit_background(self.db)

    async def test_shared_material_has_separate_course_work_and_lecture_scope(self):
        from lecture_study.second_brain import source_scopes
        from lecture_study.retrieval import index_source,scope_key,scope_ids
        from lecture_study.models import SourceRef
        other=new_id();asset=new_id()
        with self.db:
            self.db.execute('INSERT INTO courses VALUES (?,?,?,?)',(other,'다른 과목','',now()))
        other_sid=create_session(self.db,'lecture','다른 회차',other,1).id
        with self.db:
            self.db.execute("INSERT INTO assets(id,filename,kind,sha256,size,status,created_at,extraction_sha256) VALUES (?,'shared.txt','txt',?,1,'ready',?,?)",(asset,'a'*64,now(),'a'*64))
            for cid in (self.cid,other):self.db.execute('INSERT INTO course_assets VALUES (?,?)',(cid,asset))
            ref=SourceRef(id=asset+':v1',kind='material',asset_id=asset,page=1)
            self.db.execute('INSERT INTO sources(id,ref,text_snapshot) VALUES (?,?,?)',(ref.id,ref.model_dump_json(),'교착 상태 공유 자료'))
            index_source(self.db,ref,'교착 상태 공유 자료')
        scopes=source_scopes(self.db,ref.id)
        self.assertEqual({scope_key(self.db,s) for s in scopes},{'course:'+self.cid,'course:'+other})
        self.assertTrue(any(other_sid in scope_ids(self.db,s) for s in scopes))
        reconcile(self.db)
        work=list(self.db.execute("SELECT key,request FROM brain_work WHERE source_id=? AND kind='source'",(ref.id,)))
        self.assertEqual(len(work),2)

    def test_deleted_record_does_not_block_reconciliation(self):
        from lecture_study.lifecycle import delete_session
        ref=save_note(self.db,self.old,'교착 상태');reconcile(self.db)
        with self.db:self.db.execute("UPDATE brain_work SET state='done'")
        delete_session(self.db,self.old,True)
        reconcile(self.db)
        self.assertEqual(self.db.execute('SELECT state FROM brain_work WHERE source_id=?',(ref.id,)).fetchone()[0],'obsolete')
