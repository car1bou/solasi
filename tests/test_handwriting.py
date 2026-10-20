import json,tempfile,unittest
from pathlib import Path
from fastapi import HTTPException
from lecture_study.db import open_db,new_id,now
from lecture_study.materials import inspect_file,register_file
from lecture_study.course_materials import save_page_document
from lecture_study.models import PageDocumentInput,Scope
from lecture_study.retrieval import eligible_chunks
from fixtures import png_fixture
from lecture_study.handwriting import capture_ink,save_recognition,approve_recognition,reject_recognition,ink_payload

class HandwritingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);self.db=open_db(root/'vault');self.addCleanup(self.db.close)
        self.cid=new_id()
        with self.db:self.db.execute('INSERT INTO courses VALUES (?,?,?,?)',(self.cid,'과목','',now()))
        path=root/'original.png';path.write_bytes(png_fixture())
        a=register_file(self.db,None,inspect_file(path),course_id=self.cid);self.aid=a['id'];self.digest=a['sha256']
        with self.db:self.db.execute('INSERT INTO asset_documents VALUES (?,?,?,?)',(self.aid,self.digest,json.dumps({'total_pages':1,'pages':[{'page':1,'width':80,'height':40}]}),now()))
        self.ink=[{'id':'s','tool':'pen','color':'#123456','width':.01,'opacity':1.,'input':'pen','points':[{'x':.1,'y':.2,'pressure':.5},{'x':.5,'y':.3,'pressure':.7}]}]
        self.save(self.ink,0)
    def save(self,ink,revision,text=''):
        return save_page_document(self.db,self.cid,self.aid,1,PageDocumentInput(document_sha256=self.digest,expected_revision=revision,text=text,ink=ink))
    def snapshot(self):return capture_ink(self.db,self.cid,self.aid,1,self.digest)
    def candidate(self):return save_recognition(self.db,self.snapshot(),{'engine':'fixture','regions':[{'bbox':[.1,.1,.5,.4],'text':'교착 상태 mutex','candidates':[]}]})
    def ids(self):return {r['source_id'] for r in eligible_chunks(self.db,[],None,None,Scope(course_id=self.cid))}
    def test_approval_only_and_stale_keeps_old_source(self):
        c=self.candidate();self.assertFalse(self.ids())
        ref=approve_recognition(self.db,c['id'],'교착 상태 mutex',c['ink_hash'])
        self.assertIn(ref.id,self.ids())
        self.save([],1)
        self.assertNotIn(ref.id,self.ids())
        self.assertEqual(self.db.execute('SELECT text_snapshot FROM sources WHERE id=?',(ref.id,)).fetchone()[0],'교착 상태 mutex')
    def test_edited_ink_rejects_old_candidate_but_text_only_does_not(self):
        c=self.candidate();self.save(self.ink,1,'문자 메모')
        self.assertEqual(self.snapshot()['ink_hash'],c['ink_hash'])
        self.save([],2)
        with self.assertRaises(HTTPException) as caught:approve_recognition(self.db,c['id'],'교착 상태',c['ink_hash'])
        self.assertEqual(caught.exception.status_code,409)
    def test_rejection_and_same_input_are_idempotent(self):
        c=self.candidate();reject_recognition(self.db,c['id'])
        self.assertEqual(self.candidate()['id'],c['id']);self.assertFalse(self.ids())
    def test_invalid_region_and_highlighter_only(self):
        with self.assertRaises(ValueError):save_recognition(self.db,self.snapshot(),{'engine':'fixture','regions':[{'bbox':[-1,0,1,1],'text':'x'}]})
        self.save([dict(self.ink[0],tool='highlighter')],1)
        self.assertEqual(ink_payload(self.snapshot())['strokes'],[])

    def mark_imported_handwriting(self):
        row=self.db.execute('SELECT external_path FROM assets WHERE id=?',(self.aid,)).fetchone()
        return register_file(self.db,None,inspect_file(Path(row[0])),course_id=self.cid,handwritten=True)

    def test_imported_note_requires_review_and_blocks_old_raw_snapshots(self):
        from lecture_study.models import SourceRef,AIRequest,ProviderConfig,Evidence
        from lecture_study.retrieval import index_source,capture_search,snapshot_rows
        from lecture_study.answers import checked_evidence
        from lecture_study.outputs import image_evidence
        raw=SourceRef(id=self.aid+':v1:page:1',kind='material',asset_id=self.aid,version=1,page=1)
        wrong='CDF F(x)=P(X<x)'
        with self.db:
            self.db.execute("UPDATE assets SET status='ready',extraction_sha256=sha256 WHERE id=?",(self.aid,))
            self.db.execute('INSERT INTO sources(id,ref,text_snapshot) VALUES (?,?,?)',(raw.id,raw.model_dump_json(),wrong));index_source(self.db,raw,wrong)
        scope=Scope(course_id=self.cid);frozen=capture_search(self.db,scope,None)
        self.assertIn(raw.id,self.ids())
        self.mark_imported_handwriting();self.assertNotIn(raw.id,self.ids())
        with self.assertRaisesRegex(ValueError,'승인'):snapshot_rows(self.db,frozen)
        request=AIRequest(course_id=self.cid,kind='summary',scope=scope,provider=ProviderConfig(provider='local'),prompt='CDF 요약')
        with self.assertRaisesRegex(ValueError,'승인'):
            checked_evidence(self.db,{'request':request.model_dump(),'evidence':[Evidence(ref=raw,text=wrong,label='OCR').model_dump()]})
        vision=request.model_copy(update={'kind':'vision','image_id':raw.id})
        with self.assertRaisesRegex(ValueError,'승인'):image_evidence(self.db,vision)
        c=save_recognition(self.db,self.snapshot(),{'engine':'fixture/page','regions':[{'bbox':[0,0,1,1],'text':wrong}]})
        self.assertFalse(self.ids())
        approved=approve_recognition(self.db,c['id'],'CDF F(x)=P(X≤x)',c['ink_hash'])
        self.assertEqual(self.ids(),{approved.id})
        self.assertEqual(self.db.execute('SELECT text_snapshot FROM sources WHERE id=?',(raw.id,)).fetchone()[0],wrong)
        path=Path(self.db.execute('SELECT external_path FROM assets WHERE id=?',(self.aid,)).fetchone()[0]);path.write_bytes(path.read_bytes()+b'changed')
        self.assertFalse(self.ids())

    def test_imported_note_recognizes_original_without_pen_strokes(self):
        from lecture_study.second_brain import reconcile,next_background_work
        self.mark_imported_handwriting();self.save([],1)
        snapshot=self.snapshot()
        self.assertTrue(snapshot['page_source'])
        self.assertFalse(snapshot['ink'])
        reconcile(self.db);self.assertEqual(next_background_work(self.db)['kind'],'ink')
        row=self.db.execute('SELECT external_path FROM assets WHERE id=?',(self.aid,)).fetchone()
        register_file(self.db,None,inspect_file(Path(row[0])),course_id=self.cid)
        self.assertTrue(self.snapshot()['page_source'])

    def test_mixed_note_only_reviewed_text_reaches_summary_and_previous_lecture(self):
        import asyncio
        from lecture_study.db import create_session
        from lecture_study.materials import save_note
        from lecture_study.answers import snapshot_evidence
        from lecture_study.second_brain import related_sources
        from lecture_study.models import AIRequest,ProviderConfig
        old=create_session(self.db,'lecture','이전 강의',self.cid,1).id
        previous=save_note(self.db,old,'누적분포함수 CDF 확률변수 X 오른쪽 연속 성질')
        self.mark_imported_handwriting()
        wrong='누적분포함수 CDF F(x)=P(X≤x) 오목과 편평성 없음'
        candidate=save_recognition(self.db,self.snapshot(),{'engine':'fixture/page','regions':[{'bbox':[0,0,1,1],'text':wrong}]})
        scope=Scope(session_id=old)
        request=AIRequest(session_id=old,kind='summary',scope=scope,provider=ProviderConfig(provider='local'),prompt='CDF 요약')
        self.assertEqual([e.ref.id for e in snapshot_evidence(self.db,request,None)],[previous.id])
        self.assertFalse(asyncio.run(related_sources(self.db,scope,previous.id,None)).evidence)
        corrected='누적분포함수 CDF F(x)=P(X≤x). 오른쪽 연속 성질'
        approved=approve_recognition(self.db,candidate['id'],corrected,candidate['ink_hash'])
        evidence=snapshot_evidence(self.db,request,None)
        self.assertEqual({e.ref.id for e in evidence},{previous.id,approved.id})
        self.assertNotIn('편평성',' '.join(e.text for e in evidence))
        linked=asyncio.run(related_sources(self.db,scope,approved.id,None))
        self.assertEqual([e.ref.id for e in linked.evidence],[previous.id])
        rejected=save_recognition(self.db,self.snapshot(),{'engine':'other/page','regions':[{'bbox':[0,0,1,1],'text':'π-system 잘못 읽음'}]})
        reject_recognition(self.db,rejected['id'])
        self.assertEqual({e.ref.id for e in snapshot_evidence(self.db,request,None)},{previous.id,approved.id})

    def test_returning_to_old_ink_can_be_reviewed_again(self):
        first=self.candidate();ref=approve_recognition(self.db,first['id'],'교착 상태 mutex',first['ink_hash'])
        self.save([],1);self.save(self.ink,2)
        again=self.candidate()
        self.assertNotEqual(again['id'],first['id'])
        self.assertEqual(again['status'],'candidate')
        new=approve_recognition(self.db,again['id'],'교착 상태 mutex',again['ink_hash'])
        self.assertNotEqual(new.id,ref.id)

    def test_explicit_retry_preserves_previous_proposal(self):
        first=self.candidate()
        with self.db:self.db.execute("UPDATE ink_recognitions SET status='stale' WHERE id=?",(first['id'],))
        again=self.candidate()
        self.assertNotEqual(first['id'],again['id'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM ink_recognitions').fetchone()[0],2)

    def test_explicit_local_model_recognition_keeps_real_ink_bounds(self):
        import asyncio
        from unittest.mock import AsyncMock,patch
        from lecture_study.handwriting import recognize_local_ink
        async def render(snapshot,image_path=None):
            image_path.write_bytes(png_fixture());return {'engine':'vision','regions':[]}
        manager=type('Manager',(),{})();manager.status=AsyncMock(return_value={'digest':'a'*64});manager.generate=AsyncMock(return_value={'text':'교착 상태','usage':{}})
        with patch('lecture_study.handwriting.recognize_ink',side_effect=render):
            result=asyncio.run(recognize_local_ink(self.snapshot(),manager))
        self.assertEqual(result['regions'][0]['text'],'교착 상태')
        self.assertGreaterEqual(result['regions'][0]['bbox'][0],0)
        self.assertEqual(manager.generate.call_args.args[0].provider,'local')

    def test_local_recognition_with_no_pen_does_not_start_a_model(self):
        import asyncio
        from unittest.mock import AsyncMock
        from lecture_study.handwriting import recognize_local_ink
        self.save([],1)
        manager=type('Manager',(),{})();manager.status=AsyncMock();manager.generate=AsyncMock()
        result=asyncio.run(recognize_local_ink(self.snapshot(),manager))
        self.assertEqual(result['regions'],[])
        manager.status.assert_not_called();manager.generate.assert_not_called()
