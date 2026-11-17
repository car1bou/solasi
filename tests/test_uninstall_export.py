import hashlib
import importlib.util
import itertools
import json
from pathlib import Path
import tempfile
import unittest

from lecture_study.config import AppConfig
from lecture_study.db import open_db, create_session, new_id, now
from lecture_study.materials import inspect_file, register_file
from lecture_study.audio import start_recording, append_pcm


class UninstallExportTests(unittest.IsolatedAsyncioTestCase):
    async def test_results_preserve_conversation_and_learning_memory_with_exact_counts(self):
        from lecture_study import study_memory
        owned=study_memory.owner(self.db,session_id=self.sid)
        thread=study_memory.create_thread(self.db,owned)
        study_memory.add_user(self.db,thread['id'],owned,'보존할 학습 대화',{'session_id':self.sid})
        module=self.module()
        receipt=await module.prepare_export(self.db,self.config,self.root,module.ExportSelection(False,False,True))
        self.assertIn('study',receipt)
        saved=json.loads((Path(receipt['directory'])/receipt['study']['path']).read_text())
        self.assertEqual(saved,study_memory.export_records(self.db))
        self.assertEqual(receipt['study']['counts']['messages'],1)
        module.verify_export(receipt,self.db)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.config=AppConfig(self.root/'vault',self.root/'runtime',embedded=True)
        self.config.runtime_dir.mkdir();self.db=open_db(self.config.data_dir);self.addCleanup(self.db.close)
        self.sid=create_session(self.db,'meeting','회의',None,None).id
        self.source=self.root/'원본.txt';self.source.write_text('문서 원문',encoding='utf-8')
        self.asset=register_file(self.db,self.sid,inspect_file(self.source))
        self.rid=start_recording(self.db,self.sid,16000)
        append_pcm(self.db,self.rid,0,0,16,b'\0\0'*16)
        with self.db:
            self.db.execute("UPDATE recordings SET status='done' WHERE id=?",(self.rid,))
            self.db.execute("UPDATE sessions SET recording_status='idle' WHERE id=?",(self.sid,))
            job=new_id();self.db.execute("INSERT INTO jobs(id,session_id,kind,status,request,created_at,updated_at) VALUES (?,?,'ai','done','{}',?,?)",(job,self.sid,now(),now()))
            self.aid=new_id();self.db.execute("INSERT INTO artifacts(id,job_id,session_id,kind,body,evidence,metadata,created_at) VALUES (?,?,?,'quiz',?,'[]','{}',?)",(self.aid,job,self.sid,json.dumps({'questions':[{'prompt':'문제 내용','answer':'정답'}]}),now()))
            self.db.execute("INSERT INTO attempts(id,quiz_id,question_id,submitted_answer,explanation,evidence_ids,metadata,status,created_at) VALUES (?,?,?,'내 답','해설','[]','{}','done',?)",(new_id(),self.aid,'q1',now()))

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('lecture_study.uninstall_export'),'independent preservation service is missing')
        from lecture_study import uninstall_export
        return uninstall_export

    async def test_all_category_combinations_keep_expected_content_and_never_modify_originals(self):
        m=self.module();before=self.source.read_bytes()
        for docs,audio,results in itertools.product((False,True),repeat=3):
            receipt=await m.prepare_export(self.db,self.config,self.root,m.ExportSelection(docs,audio,results))
            m.verify_export(receipt,self.db)
            files=receipt['files'];categories={f['category'] for f in files}
            self.assertEqual(categories,{name for name,flag in [('documents',docs),('audio',audio),('results',results)] if flag})
            text='\n'.join((Path(receipt['directory'])/f['path']).read_text() for f in files if f['path'].endswith(('.txt','.md')))
            self.assertEqual('문서 원문' in text,docs)
            self.assertEqual('문제 내용' in text,results);self.assertEqual('내 답' in text,results)
            self.assertEqual(self.source.read_bytes(),before)
            self.assertTrue((self.config.data_dir/'app.sqlite3').exists())
            self.assertTrue(all(f['sha256']==hashlib.sha256((Path(receipt['directory'])/f['path']).read_bytes()).hexdigest() for f in files))

    async def test_export_keeps_latest_edited_result_and_overridden_grade_and_partial_summary(self):
        m=self.module()
        with self.db:
            self.db.execute('INSERT INTO artifact_revisions VALUES (?,?,?,?,?)',(self.aid,1,json.dumps({'questions':[{'prompt':'편집한 최신 문제','answer':'새 정답'}]}),1,now()))
            attempt=self.db.execute('SELECT id FROM attempts WHERE quiz_id=?',(self.aid,)).fetchone()[0]
            self.db.execute('INSERT INTO attempt_revisions VALUES (?,1,?,?,?)',(attempt,'correct','사용자가 정정한 최신 평가',now()))
            job=new_id();self.db.execute("INSERT INTO jobs(id,session_id,kind,status,request,created_at,updated_at) VALUES (?,?,'ai','failed','{}',?,?)",(job,self.sid,now(),now()))
            self.db.execute('INSERT INTO artifact_parts VALUES (?,0,?,?)',(job,json.dumps({'sections':[{'text':'중단 전 완료된 구간 요약'}]}),'{}'))
        r=await m.prepare_export(self.db,self.config,self.root,m.ExportSelection(False,False,True))
        text='\n'.join((Path(r['directory'])/f['path']).read_text() for f in r['files'])
        self.assertIn('편집한 최신 문제',text);self.assertNotIn('문제 내용',text)
        self.assertIn('사용자가 정정한 최신 평가',text);self.assertIn('correct',text)
        self.assertIn('중단 전 완료된 구간 요약',text);self.assertIn('미완료',text)

    async def test_terminal_job_partial_results_are_preserved_without_final_artifact(self):
        m=self.module()
        with self.db:
            job=new_id();self.db.execute("INSERT INTO jobs(id,session_id,kind,status,request,created_at,updated_at) VALUES (?,?,'ai','interrupted','{}',?,?)",(job,self.sid,now(),now()))
            self.db.execute('INSERT INTO artifact_parts VALUES (?,0,?,?)',(job,json.dumps({'sections':[{'text':'독립 부분 요약 검증'}]}),'{}'))
        r=await m.prepare_export(self.db,self.config,self.root,m.ExportSelection(False,False,True))
        text='\n'.join((Path(r['directory'])/f['path']).read_text() for f in r['files'])
        self.assertIn('독립 부분 요약 검증',text)

    async def test_empty_dirty_draft_is_an_unresolved_clear_not_safe_to_discard(self):
        m=self.module()
        from lecture_study.native_drafts import NativeDrafts
        NativeDrafts(self.db)
        with self.db:self.db.execute('INSERT INTO native_drafts VALUES (?,?)',('clear',json.dumps({'dirty':True,'text':'','ink':[]})))
        with self.assertRaises(ValueError):await m.prepare_export(self.db,self.config,self.root,m.ExportSelection())

    async def test_transcript_includes_recording_relative_time_after_session_offset(self):
        m=self.module()
        from lecture_study.materials import save_note
        # Existing transcript accessors consume versioned rows, so use a literal valid schema fixture.
        with self.db:
            self.db.execute('UPDATE recordings SET offset_ms=60000 WHERE id=?',(self.rid,))
            self.db.execute("INSERT INTO transcript_ranges(id,recording_id,start_frame,end_frame,stored_start,stored_end,final,revision,status) VALUES (?,?,0,16,0,16,1,1,'done')",(self.rid+':0',self.rid))
            self.db.execute("INSERT INTO transcripts(id,session_id,recording_id,chunk_id,start_ms,end_ms,text,original_text,revision,final,created_at) VALUES (?,?,?,?,60000,60001,'시간 검증','시간 검증',1,1,?)",(new_id(),self.sid,self.rid,self.rid+':0',now()))
        r=await m.prepare_export(self.db,self.config,self.root,m.ExportSelection(False,True,True))
        text='\n'.join((Path(r['directory'])/f['path']).read_text() for f in r['files'] if f['kind']=='text')
        self.assertIn('파일 0.000',text);self.assertIn('회차 60.000',text)

    async def test_space_preflight_rejects_before_creating_partial_export(self):
        from unittest.mock import patch
        import shutil
        m=self.module();before=set(self.root.iterdir())
        with patch.object(m.shutil,'disk_usage',return_value=shutil._ntuple_diskusage(100,100,0)):
            with self.assertRaisesRegex(ValueError,'공간'):
                await m.prepare_export(self.db,self.config,self.root,m.ExportSelection())
        self.assertEqual(set(self.root.iterdir()),before)

    async def test_missing_source_and_overlapping_destination_cannot_produce_verified_receipt(self):
        m=self.module()
        with self.assertRaises(ValueError):await m.prepare_export(self.db,self.config,self.config.data_dir,m.ExportSelection())
        self.source.unlink()
        with self.assertRaises((ValueError,OSError)):await m.prepare_export(self.db,self.config,self.root,m.ExportSelection())
        self.assertTrue((self.config.data_dir/'app.sqlite3').exists())

    async def test_changed_export_or_database_and_symlink_replacement_block_verification(self):
        m=self.module();r=await m.prepare_export(self.db,self.config,self.root,m.ExportSelection())
        f=Path(r['directory'])/r['files'][0]['path'];old=f.read_bytes();f.write_bytes(b'corrupt')
        with self.assertRaises(ValueError):m.verify_export(r,self.db)
        f.write_bytes(old);m.verify_export(r,self.db)
        f.unlink();f.symlink_to(self.source)
        with self.assertRaises(ValueError):m.verify_export(r,self.db)
        f.unlink();f.write_bytes(old)
        with self.db:self.db.execute("UPDATE sessions SET title='changed' WHERE id=?",(self.sid,))
        with self.assertRaises(ValueError):m.verify_export(r,self.db)

    async def test_dirty_drafts_block_preservation_and_invalid_selection_is_rejected(self):
        m=self.module()
        with self.assertRaises(ValueError):m.ExportSelection(documents=1)
        from lecture_study.native_drafts import NativeDrafts
        NativeDrafts(self.db)
        with self.db:self.db.execute('INSERT INTO native_drafts VALUES (?,?)',('draft',json.dumps({'dirty':True,'text':'unsaved'})))
        with self.assertRaises(ValueError):await m.prepare_export(self.db,self.config,self.root,m.ExportSelection())
