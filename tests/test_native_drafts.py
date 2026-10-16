import base64
import hashlib
import json
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


if __name__=='__main__': unittest.main()
