import base64
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from lecture_study.db import open_db
from lecture_study.native_drafts import NativeDrafts, MAX_UPLOAD


def draft(key='["c","a","hash",1]', text='메모'):
    return dict(key=key, text=text, ink=[], revision=2, token='original-token',
                dirty=False, backup={'text': '버리면 안 되는 이전 메모', 'ink': []}, unknown={'keep': True})


class NativeDraftTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.db = open_db(self.root)
        self.addCleanup(self.db.close)
        self.store = NativeDrafts(self.db)

    def upload(self, value, **fields):
        raw = json.dumps(value, ensure_ascii=False).encode()
        handle = self.store.begin(len(raw), **fields)['id']
        for start in range(0, len(raw), 37):
            self.store.append(handle, start, base64.b64encode(raw[start:start+37]).decode())
        return handle, hashlib.sha256(raw).hexdigest()

    def test_atomic_main_journal_backup_and_restart(self):
        row = draft(); row['dirty'] = True
        handle, digest = self.upload(row, kind='write', journal_key=row['key']+'::writer')
        self.assertEqual(self.store.read(row['key']), [])
        self.assertEqual(self.store.commit(handle)['sha256'], digest)
        expected = [row, {**row, 'key': row['key']+'::writer'}]
        self.assertEqual(self.store.read(row['key']), expected)
        other = open_db(self.root)
        try:
            reopened = NativeDrafts(other)
            self.assertEqual(reopened.read(row['key']), expected)
            self.assertEqual(reopened.state()['vault_id'], self.store.state()['vault_id'])
        finally: other.close()
        row['dirty'] = False
        handle, _ = self.upload(row, kind='write', journal_key=row['key']+'::writer')
        self.store.commit(handle)
        self.assertEqual(self.store.read(row['key']), [row])

    def test_failed_or_incomplete_write_keeps_committed_content(self):
        row = draft()
        handle, _ = self.upload(row, kind='write', journal_key=row['key']+'::writer')
        self.store.commit(handle)
        handle = self.store.begin(20, kind='write', journal_key=row['key']+'::writer')['id']
        self.store.append(handle, 0, base64.b64encode(b'partial').decode())
        with self.assertRaises(ValueError): self.store.commit(handle)
        with self.assertRaises(ValueError): self.store.append(handle, 2, 'eA==')
        self.assertEqual(self.store.read(row['key']), [row])
        handle, _ = self.upload({**row, 'text':'new'}, kind='write', journal_key=row['key']+'::writer')
        self.db.execute("CREATE TRIGGER fail_draft BEFORE INSERT ON native_drafts BEGIN SELECT RAISE(FAIL,'disk unavailable'); END")
        with self.assertRaises(Exception): self.store.commit(handle)
        self.assertEqual(self.store.read(row['key']), [row])

    def test_full_raw_import_conflict_idempotence_and_wrong_vault(self):
        existing = draft()
        handle, _ = self.upload(existing, kind='write', journal_key=existing['key']+'::writer')
        self.store.commit(handle)
        changed = draft(text='다른 창의 메모')
        journal = {**changed, 'key':changed['key']+'::other', 'dirty':True}
        export = {'version':1, 'vault_id':self.store.state()['vault_id'], 'origin':'http://127.0.0.1:62434',
                  'theme':'dark', 'drafts':[changed,journal], 'unsaved_inputs':[{'kind':'note', 'text':'작성 중'}]}
        handle, digest = self.upload(export, kind='import')
        report = self.store.commit(handle)
        self.assertEqual(report['count'], 2)
        self.assertEqual(report['conflicts'], 1)
        rows = self.store.read(existing['key'])
        self.assertEqual(rows[0], existing)
        self.assertTrue(any(r['text']==changed['text'] for r in rows[1:]))
        self.assertIn(journal, rows)
        self.assertEqual(self.store.state()['theme'], 'dark')
        saved = self.db.execute('SELECT payload FROM native_migrations WHERE digest=?',(digest,)).fetchone()
        self.assertEqual(json.loads(saved[0]), export)
        handle, _ = self.upload(export, kind='import')
        self.assertEqual(self.store.commit(handle), report)
        self.assertEqual(self.store.read(existing['key']), rows)
        export['vault_id']='wrong-vault'
        handle, _ = self.upload(export, kind='import')
        with self.assertRaises(ValueError): self.store.commit(handle)
        self.assertEqual(self.store.read(existing['key']), rows)

    def test_limits_invalid_payload_and_journal_delete_boundary(self):
        for size in (True,0,MAX_UPLOAD+1):
            with self.assertRaises(ValueError): self.store.begin(size, kind='import')
        handle = self.store.begin(3,kind='import')['id']
        for offset, value in ((0,'not-base64'),(0,'YWJjZA=='),(-1,'eA==')):
            with self.assertRaises(ValueError): self.store.append(handle,offset,value)
        self.store.append(handle,0,'YWJj')
        with self.assertRaises(ValueError): self.store.commit(handle)
        with self.assertRaises(ValueError): self.store.delete(draft()['key'])
        with self.assertRaises(KeyError): self.store.append('../other',0,'eA==')
        self.assertEqual(self.store.read(draft()['key']), [])

    def test_restart_discards_only_abandoned_uploads(self):
        row=draft()
        handle,_=self.upload(row,kind='write',journal_key=row['key']+'::writer')
        self.store.commit(handle)
        for _ in range(4):
            handle=self.store.begin(10,kind='import')['id']
            self.store.append(handle,0,'eA==')
        with self.assertRaises(ValueError):self.store.begin(10,kind='import')
        other=open_db(self.root)
        try:
            reopened=NativeDrafts(other)
            reopened.discard_abandoned_uploads()
            self.assertEqual(reopened.read(row['key']),[row])
            self.assertEqual(other.execute('SELECT count(*) FROM native_upload_parts').fetchone()[0],0)
            self.assertTrue(reopened.begin(10,kind='import')['id'])
        finally:other.close()


def tool_preferences():
    return dict(tool='pen',penColor='#254f3f',penWidth=.0025,penOpacity=1,
                highlighterColor='#ffe066',highlighterWidth=.018,highlighterOpacity=.35,eraserSize=.014)


def view_preferences():
    return dict(zoomMode='fit',zoom=1,rotation=0,notesOpen=True)


VIEW_KEY='notebook-view:'+('a'*32)+':'+('b'*64)


class NativePreferenceTests(unittest.TestCase):
    setUp=NativeDraftTests.setUp

    def test_preferences_are_isolated_durable_and_do_not_add_tables_or_change_drafts(self):
        original=draft()
        with self.db:
            self.db.execute('INSERT INTO native_drafts VALUES (?,?)',(original['key'],json.dumps(original)))
            self.db.execute('INSERT INTO settings VALUES (?,?)',('unrelated-private-setting','private-value'))
        schema=[tuple(row)for row in self.db.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name')]
        settings=[tuple(row)for row in self.db.execute('SELECT key,value FROM settings ORDER BY key')]
        self.assertEqual(self.store.read_preference('notebook-tools'),{'value':None})
        self.assertEqual(self.store.read_preference(VIEW_KEY),{'value':None})
        self.assertEqual(self.store.write_preference('notebook-tools',tool_preferences()),{'value':tool_preferences()})
        self.assertEqual(self.store.write_preference(VIEW_KEY,view_preferences()),{'value':view_preferences()})
        self.assertEqual(self.store.read_preference(VIEW_KEY.replace('a'*32,'c'*32)),{'value':None})
        self.assertEqual(self.store.read_preference(VIEW_KEY.replace('b'*64,'d'*64)),{'value':None})
        other=open_db(self.root)
        try:
            reopened=NativeDrafts(other)
            self.assertEqual(reopened.read_preference('notebook-tools'),{'value':tool_preferences()})
            self.assertEqual(reopened.read_preference(VIEW_KEY),{'value':view_preferences()})
        finally:other.close()
        self.assertEqual([tuple(row)for row in self.db.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name')],schema)
        for key,value in settings:self.assertEqual(self.db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()[0],value)
        self.assertEqual(self.store.read(original['key']),[original])
        self.assertEqual(set(self.store.state()),{'vault_id','theme'})

    def test_eraser_mode_survives_restart_when_another_tool_is_selected(self):
        self.store.write_preference('notebook-tools', tool_preferences())
        for mode in ('stroke-eraser','partial-eraser'):
            value={**tool_preferences(),'tool':'highlighter','eraserMode':mode}
            self.store.write_preference('notebook-tools',value)
            other=open_db(self.root)
            try:self.assertEqual(NativeDrafts(other).read_preference('notebook-tools')['value'],value)
            finally:other.close()
            for invalid in (None,True,'pen','partial',{},[]):
                with self.assertRaises(ValueError):self.store.write_preference('notebook-tools',{**value,'eraserMode':invalid})
                self.assertEqual(self.store.read_preference('notebook-tools')['value'],value)

    def test_keys_cannot_access_arbitrary_settings_or_other_document_identifiers(self):
        for key in ('native_theme','native_vault_id','unrelated-private-setting','../notebook-tools','notebook-tools:other','notebook-view:a:'+'b'*64,'notebook-view:'+'a'*32+':hash',VIEW_KEY+'::copy',VIEW_KEY+'\x00',None):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):self.store.read_preference(key)
                with self.assertRaises(ValueError):self.store.write_preference(key,view_preferences())

    def test_invalid_values_leave_last_saved_tool_preferences_unchanged(self):
        valid=tool_preferences();self.store.write_preference('notebook-tools',valid)
        invalid=[None,[],{**valid,'extra':'unknown'},{k:v for k,v in valid.items()if k!='penColor'}]
        for field,value in (('tool','unknown'),('tool',True),('penColor','#fff'),('highlighterColor','red'),('penWidth',True),('penWidth',.00049),('highlighterWidth',.04001),('penOpacity',float('nan')),('highlighterOpacity',float('inf')),('penOpacity',.049),('eraserSize',.06001),('eraserSize','0.014'),('penColor','#'+'a'*5000)):
            invalid.append({**valid,field:value})
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):self.store.write_preference('notebook-tools',value)
                self.assertEqual(self.store.read_preference('notebook-tools'),{'value':valid})
        for tool in ('pen','highlighter','stroke-eraser','partial-eraser','lasso','pan'):
            self.assertEqual(self.store.write_preference('notebook-tools',{**valid,'tool':tool})['value']['tool'],tool)

    def test_view_limits_are_strict_and_do_not_coerce_types(self):
        valid=view_preferences();self.store.write_preference(VIEW_KEY,valid)
        for field,value in (('zoomMode','unknown'),('zoom',.099),('zoom',3.001),('zoom',True),('zoom','1'),('rotation',True),('rotation',90.0),('rotation',45),('notesOpen',1),('notesOpen','false')):
            with self.subTest(field=field,value=value):
                with self.assertRaises(ValueError):self.store.write_preference(VIEW_KEY,{**valid,field:value})
                self.assertEqual(self.store.read_preference(VIEW_KEY),{'value':valid})
        for rotation in (0,90,180,270):
            value={**valid,'zoomMode':'manual','zoom':3,'rotation':rotation,'notesOpen':False}
            self.assertEqual(self.store.write_preference(VIEW_KEY,value),{'value':value})

    def test_page_fit_mode_is_saved_and_restored(self):
        value={**view_preferences(),'zoomMode':'page'}
        self.assertEqual(self.store.write_preference(VIEW_KEY,value),{'value':value})
        self.assertEqual(self.store.read_preference(VIEW_KEY),{'value':value})

    def test_corrupt_saved_value_is_reported_without_rewriting_it(self):
        self.store.write_preference(VIEW_KEY,view_preferences())
        key=self.db.execute('SELECT key FROM settings WHERE key LIKE ?',('%'+VIEW_KEY,)).fetchone()[0]
        for raw in ('{bad json}',json.dumps({'notesOpen':True}),' '*5000+'{}'):
            with self.db:self.db.execute('UPDATE settings SET value=? WHERE key=?',(raw,key))
            with self.assertRaises(ValueError):self.store.read_preference(VIEW_KEY)
            self.assertEqual(self.db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()[0],raw)

    def test_failed_database_write_does_not_report_success_or_erase_previous_value(self):
        valid=tool_preferences();self.store.write_preference('notebook-tools',valid)
        with self.db:self.db.execute("CREATE TRIGGER fail_preference BEFORE INSERT ON settings BEGIN SELECT RAISE(FAIL,'disk unavailable'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.store.write_preference('notebook-tools',{**valid,'tool':'pan'})
        self.assertEqual(self.store.read_preference('notebook-tools'),{'value':valid})


class NativePreferenceApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse
        from fastapi.testclient import TestClient
        from lecture_study.native_drafts import attach_native_drafts
        NativeDraftTests.setUp(self)
        app=FastAPI()
        @app.exception_handler(ValueError)
        async def invalid(request,exc):return JSONResponse({'detail':str(exc)},status_code=422)
        attach_native_drafts(app,self.db)
        self.client=TestClient(app);self.addCleanup(self.client.close)

    def test_get_and_put_only_expose_the_requested_preference(self):
        from urllib.parse import quote
        for key,value in (('notebook-tools',tool_preferences()),(VIEW_KEY,view_preferences())):
            path='/api/native/preferences/'+quote(key,safe='')
            response=self.client.get(path);self.assertEqual(response.status_code,200);self.assertEqual(response.json(),{'value':None})
            response=self.client.put(path,json={'value':value});self.assertEqual(response.status_code,200);self.assertEqual(response.json(),{'value':value})
            self.assertEqual(self.client.get(path).json(),{'value':value})
        self.assertEqual(self.client.get('/api/native/preferences/native_vault_id').status_code,422)

    def test_invalid_or_oversized_requests_preserve_the_saved_value(self):
        path='/api/native/preferences/notebook-tools';value=tool_preferences()
        self.assertEqual(self.client.put(path,json={'value':value}).status_code,200)
        for body in ({},{'value':None},{'value':value,'extra':True},{'value':{**value,'penWidth':'0.0025'}},[]):
            with self.subTest(body=body):
                self.assertEqual(self.client.put(path,json=body).status_code,422)
                self.assertEqual(self.client.get(path).json(),{'value':value})
        raw=' '*4096+json.dumps({'value':value})
        self.assertEqual(self.client.put(path,content=raw,headers={'Content-Type':'application/json'}).status_code,422)
        self.assertEqual(self.client.get(path).json(),{'value':value})


if __name__=='__main__': unittest.main()
