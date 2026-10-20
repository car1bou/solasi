import unittest
from lecture_study.asr_hints import validate_hotwords


class HotwordValidationTests(unittest.TestCase):
    def test_names_are_normalized_deduplicated_and_not_split(self):
        self.assertEqual(validate_hotwords([' 자그로스산맥 ','자그로스산맥','Dijkstra   algorithm','']),['자그로스산맥','Dijkstra algorithm'])
    def test_unsafe_or_oversized_words_are_rejected_before_model_input(self):
        for words in ('이름',[1],['줄\n바꿈'],['제어\x7f문자'],['<|im_end|>'],['가'*67]):
            with self.subTest(words=words),self.assertRaises(ValueError):validate_hotwords(words)

import json,os,tempfile
from pathlib import Path
from unittest.mock import patch
from lecture_study.db import open_db,create_session,new_id,now
from lecture_study.materials import save_note,inspect_file,register_file
from lecture_study.retrieval import save_term,index_source
from lecture_study.models import Scope,SourceRef,PageDocumentInput
from lecture_study.course_materials import save_page_document
from lecture_study.handwriting import capture_ink,save_recognition,approve_recognition
from fixtures import png_fixture


class HintCurrentnessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.db=open_db(self.root/'vault');self.addCleanup(self.db.close);self.cid=new_id()
        with self.db:self.db.execute('INSERT INTO courses VALUES (?,?,?,?)',(self.cid,'지리','',now()))
        self.sid=create_session(self.db,'lecture','현재',self.cid,2).id
        self.previous=create_session(self.db,'lecture','이전',self.cid,1).id
    def snapshot(self):
        from lecture_study.asr_hints import hint_snapshot
        return hint_snapshot(self.db,self.sid)
    def term(self,name,refs):return save_term(self.db,self.sid,name,[],'',refs)
    def asset(self):
        p=self.root/'original.png';p.write_bytes(png_fixture());a=register_file(self.db,None,inspect_file(p),course_id=self.cid)
        with self.db:self.db.execute('INSERT INTO asset_documents VALUES (?,?,?,?)',(a['id'],a['sha256'],json.dumps({'total_pages':1,'pages':[{'page':1,'width':80,'height':40}]}),now()))
        return p,a
    def test_old_note_evidence_is_excluded_without_deleting_manual_terms_or_history(self):
        from lecture_study.transcription import save_asr_terms
        save_asr_terms(self.db,self.sid,['직접 입력']);self.term('근거 없는 용어',[])
        ref=save_note(self.db,self.previous,'자그로스산맥');ident=self.term('자그로스산맥',[ref])
        first=self.snapshot();self.assertIn('자그로스산맥',first['prompt'])
        save_note(self.db,self.previous,'바뀐 메모')
        current=self.snapshot();self.assertNotIn('자그로스산맥',current['prompt'])
        from lecture_study.transcription import asr_prompt
        self.assertNotIn('자그로스산맥',asr_prompt(self.db,self.sid))
        self.assertIn('직접 입력',current['prompt']);self.assertIn('근거 없는 용어',current['prompt'])
        self.assertEqual(current['excluded'][0]['reason'],'근거 재검토 필요')
        self.assertEqual(self.db.execute('SELECT text_snapshot FROM sources WHERE id=?',(ref.id,)).fetchone()[0],'자그로스산맥')
        self.assertTrue(self.db.execute('SELECT 1 FROM terms WHERE id=?',(ident,)).fetchone())
        self.assertIn('자그로스산맥',first['prompt'])
    def test_any_changed_evidence_excludes_term_even_if_another_is_current(self):
        a=save_note(self.db,self.previous,'이란');b=save_note(self.db,self.sid,'이란')
        self.term('이란',[a,b]);self.assertIn('이란',self.snapshot()['prompt'])
        save_note(self.db,self.previous,'수정');self.assertNotIn('이란',self.snapshot()['prompt'])
    def test_approved_ink_survives_text_only_edit_but_not_changed_strokes(self):
        p,a=self.asset();ink=[{'id':'s','tool':'pen','color':'#123456','width':.01,'opacity':1.,'input':'pen','points':[{'x':.1,'y':.2,'pressure':.5},{'x':.5,'y':.3,'pressure':.7}]}]
        def save(rev,strokes,text=''):return save_page_document(self.db,self.cid,a['id'],1,PageDocumentInput(document_sha256=a['sha256'],expected_revision=rev,text=text,ink=strokes))
        save(0,ink);snap=capture_ink(self.db,self.cid,a['id'],1,a['sha256'])
        candidate=save_recognition(self.db,snap,{'engine':'fixture','regions':[{'bbox':[0,0,1,1],'text':'이란'}]})
        ref=approve_recognition(self.db,candidate['id'],'이란',candidate['ink_hash']);self.term('이란',[ref])
        self.assertIn('이란',self.snapshot()['prompt']);save(1,ink,'글자만 수정')
        self.assertIn('이란',self.snapshot()['prompt']);save(2,[])
        self.assertNotIn('이란',self.snapshot()['prompt'])
        self.assertEqual(self.db.execute('SELECT text_snapshot FROM sources WHERE id=?',(ref.id,)).fetchone()[0],'이란')
    def test_changed_external_file_is_detected_even_when_size_and_mtime_are_preserved(self):
        p,a=self.asset();ref=SourceRef(id='page',kind='material',asset_id=a['id'],version=1,page=1)
        with self.db:
            self.db.execute("UPDATE assets SET status='ready',extraction_sha256=sha256 WHERE id=?",(a['id'],))
            self.db.execute('INSERT INTO sources(id,ref,text_snapshot)VALUES(?,?,?)',(ref.id,ref.model_dump_json(),'이란'))
            index_source(self.db,ref,'이란')
        self.term('이란',[ref]);self.assertIn('이란',self.snapshot()['prompt'])
        stat=p.stat();raw=p.read_bytes();p.write_bytes(raw[:-1]+bytes([raw[-1]^1]));os.utime(p,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        self.assertNotIn('이란',self.snapshot()['prompt'])
    def test_same_asset_is_hashed_once_per_snapshot_and_detached_asset_is_excluded(self):
        p,a=self.asset();ref=SourceRef(id='page',kind='material',asset_id=a['id'],version=1,page=1)
        with self.db:
            self.db.execute("UPDATE assets SET status='ready',extraction_sha256=sha256 WHERE id=?",(a['id'],))
            self.db.execute('INSERT INTO sources(id,ref,text_snapshot)VALUES(?,?,?)',(ref.id,ref.model_dump_json(),'이란 자그로스산맥'))
            index_source(self.db,ref,'이란 자그로스산맥')
        self.term('이란',[ref]);self.term('자그로스산맥',[ref])
        from lecture_study.course_materials import current_document
        with patch('lecture_study.course_materials.current_document',wraps=current_document)as checked:self.snapshot();self.assertEqual(checked.call_count,1)
        with self.db:self.db.execute('DELETE FROM course_assets WHERE asset_id=?',(a['id'],))
        self.assertEqual(self.snapshot()['prompt'],'')

    def while_hashing(self,change):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event,current_thread,main_thread
        from lecture_study.course_materials import current_document
        entered=Event();release=Event()
        def paused(*args):
            result=current_document(*args)
            if current_thread()is main_thread():return result
            entered.set()
            if not release.wait(5):raise TimeoutError('hash release')
            return result
        with ThreadPoolExecutor(max_workers=1)as pool,patch('lecture_study.course_materials.current_document',side_effect=paused):
            future=pool.submit(self.snapshot)
            try:
                self.assertTrue(entered.wait(5));change()
            finally:release.set()
            return future.result(5)

    def test_detach_while_hashing_excludes_term_from_finished_snapshot(self):
        p,a=self.asset();ref=SourceRef(id='page',kind='material',asset_id=a['id'],version=1,page=1)
        with self.db:
            self.db.execute("UPDATE assets SET status='ready',extraction_sha256=sha256 WHERE id=?",(a['id'],))
            self.db.execute('INSERT INTO sources(id,ref,text_snapshot)VALUES(?,?,?)',(ref.id,ref.model_dump_json(),'이란'))
            index_source(self.db,ref,'이란')
        self.term('이란',[ref])
        def detach():
            with self.db:self.db.execute('DELETE FROM course_assets WHERE asset_id=?',(a['id'],))
        result=self.while_hashing(detach)
        self.assertEqual(result['prompt'],'');self.assertEqual(result['excluded'][0]['reason'],'근거 재검토 필요')

    def test_stroke_edit_while_hashing_excludes_approved_term(self):
        p,a=self.asset();ink=[{'id':'s','tool':'pen','color':'#123456','width':.01,'opacity':1.,'input':'pen','points':[{'x':.1,'y':.2,'pressure':.5},{'x':.5,'y':.3,'pressure':.7}]}]
        save_page_document(self.db,self.cid,a['id'],1,PageDocumentInput(document_sha256=a['sha256'],expected_revision=0,text='',ink=ink))
        snap=capture_ink(self.db,self.cid,a['id'],1,a['sha256'])
        candidate=save_recognition(self.db,snap,{'engine':'fixture','regions':[{'bbox':[0,0,1,1],'text':'이란'}]})
        ref=approve_recognition(self.db,candidate['id'],'이란',candidate['ink_hash']);self.term('이란',[ref])
        def edit():save_page_document(self.db,self.cid,a['id'],1,PageDocumentInput(document_sha256=a['sha256'],expected_revision=1,text='',ink=[]))
        self.assertEqual(self.while_hashing(edit)['prompt'],'')

    def test_failed_asset_check_is_shared_by_all_terms_in_one_snapshot(self):
        p,a=self.asset();ref=SourceRef(id='page',kind='material',asset_id=a['id'],version=1,page=1)
        with self.db:
            self.db.execute("UPDATE assets SET status='ready',extraction_sha256=sha256 WHERE id=?",(a['id'],))
            self.db.execute('INSERT INTO sources(id,ref,text_snapshot)VALUES(?,?,?)',(ref.id,ref.model_dump_json(),'이란 자그로스산맥'))
            index_source(self.db,ref,'이란 자그로스산맥')
        self.term('이란',[ref]);self.term('자그로스산맥',[ref])
        with patch('lecture_study.course_materials.current_document',side_effect=OSError('unreadable'))as checked:
            self.assertEqual(self.snapshot()['prompt'],'')
            self.assertEqual(checked.call_count,1)

    def test_unreviewed_imported_handwriting_and_forged_reference_are_excluded(self):
        p,a=self.asset();ref=SourceRef(id='page',kind='material',asset_id=a['id'],version=1,page=1)
        with self.db:
            self.db.execute("UPDATE assets SET status='ready',extraction_sha256=sha256 WHERE id=?",(a['id'],))
            self.db.execute('INSERT INTO sources(id,ref,text_snapshot)VALUES(?,?,?)',(ref.id,ref.model_dump_json(),'이란'))
            index_source(self.db,ref,'이란')
        ident=self.term('이란',[ref]);self.assertIn('이란',self.snapshot()['prompt'])
        with self.db:self.db.execute('INSERT INTO handwritten_assets VALUES (?)',(a['id'],))
        self.assertEqual(self.snapshot()['prompt'],'')
        with self.db:
            self.db.execute('DELETE FROM handwritten_assets WHERE asset_id=?',(a['id'],))
            self.db.execute('UPDATE term_versions SET evidence=? WHERE term_id=?',(json.dumps([ref.model_copy(update={'version':2}).model_dump()]),ident))
        self.assertEqual(self.snapshot()['prompt'],'')
