import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from lecture_study.db import open_db
from lecture_study.legacy_drafts import import_backup, verify_import
from tests.test_native_drafts import draft


class LegacyDraftTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.backup=self.root/'backup';self.backup.mkdir()
        self.db=open_db(self.root/'vault');self.addCleanup(self.db.close)
        self.origin='http://127.0.0.1:62434'

    def export(self, rows):
        body=b'';index=[]
        for row in rows:
            raw=json.dumps(row,ensure_ascii=False).encode()
            index.append({'key':row['key'],'offset':len(body),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
                          'undefined_paths':[],'undefined_paths_sha256':hashlib.sha256(b'[]').hexdigest()});body+=raw+b'\n'
        value={'version':1,'format':'solasi-legacy-drafts-jsonl','vault_id':'1'*32,'origin':self.origin,'source_bundle_id':'local.solasi.launcher',
               'theme':'dark','verified':True,'unsaved_inputs':[],'rows':index,'row_count':len(rows),'total_bytes':len(body),'rows_sha256':hashlib.sha256(body).hexdigest()}
        (self.backup/'drafts.jsonl').write_bytes(body);(self.backup/'manifest.json').write_text(json.dumps(value))
        return value

    def test_all_raw_rows_idempotence_and_reopen_verification(self):
        rows=[draft(),draft(key=draft()['key']+'::writer',text='복구할 초안')]
        self.export(rows);report=import_backup(self.db,self.backup,self.origin)
        self.assertEqual(report['count'],2)
        self.assertEqual(import_backup(self.db,self.backup,self.origin),report)
        other=open_db(self.root/'vault')
        try:self.assertEqual(verify_import(other,self.backup,self.origin),report['sha256'])
        finally:other.close()
        self.assertEqual([json.loads(r[0])for r in self.db.execute('SELECT value FROM native_drafts ORDER BY key')],rows)

    def test_wrong_origin_corruption_duplicate_and_symlink_rejected(self):
        self.export([draft()])
        with self.assertRaises(ValueError):import_backup(self.db,self.backup,'http://127.0.0.1:1')
        path=self.backup/'drafts.jsonl';path.write_bytes(path.read_bytes()+b'x')
        with self.assertRaises(ValueError):import_backup(self.db,self.backup,self.origin)
        self.export([draft(),draft()])
        with self.assertRaises(ValueError):import_backup(self.db,self.backup,self.origin)
        self.export([draft()]);outside=self.root/'raw';path.rename(outside);path.symlink_to(outside)
        with self.assertRaises(ValueError):import_backup(self.db,self.backup,self.origin)

    def test_mid_import_failure_rolls_back_every_row(self):
        from lecture_study.native_drafts import NativeDrafts
        NativeDrafts(self.db,initial_id='1'*32)
        self.export([draft('a'),draft('b')])
        self.db.execute("CREATE TRIGGER fail BEFORE INSERT ON native_drafts WHEN NEW.key='b' BEGIN SELECT RAISE(FAIL,'full'); END")
        with self.assertRaises(Exception):import_backup(self.db,self.backup,self.origin)
        self.assertEqual(self.db.execute('SELECT count(*) FROM native_drafts').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM native_migrations').fetchone()[0],0)

    def test_undefined_metadata_preserves_optional_property_distinction(self):
        row=draft();row.pop('backup');row['unknown']={'array':[None]}
        value=self.export([row]);value['rows'][0]['undefined_paths']=[['backup'],['unknown','array',0]]
        value['rows'][0]['undefined_paths_sha256']=hashlib.sha256(json.dumps(value['rows'][0]['undefined_paths'],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        (self.backup/'manifest.json').write_text(json.dumps(value))
        report=import_backup(self.db,self.backup,self.origin)
        saved=json.loads(self.db.execute('SELECT payload FROM native_migrations WHERE digest=?',(report['sha256'],)).fetchone()[0])
        self.assertEqual(saved['rows'][0]['undefined_paths'],value['rows'][0]['undefined_paths'])
        value['rows'][0]['undefined_paths']=[['text']]
        (self.backup/'manifest.json').write_text(json.dumps(value))
        with self.assertRaises(ValueError):import_backup(self.db,self.backup,self.origin)

    def test_changed_valid_undefined_paths_rejected_before_import(self):
        row=draft();row.pop('backup');row['unknown']={'array':[None]}
        value=self.export([row]);item=value['rows'][0]
        item['undefined_paths']=[['backup']]
        item['undefined_paths_sha256']=hashlib.sha256(b'[["backup"]]').hexdigest()
        # Both paths are structurally valid and the JSON row is unchanged, but their meanings differ.
        item['undefined_paths']=[['unknown','array',0]]
        (self.backup/'manifest.json').write_text(json.dumps(value))
        before=self.db.total_changes
        with self.assertRaisesRegex(ValueError,'undefined.*해시'):import_backup(self.db,self.backup,self.origin)
        self.assertEqual(self.db.total_changes,before)

    def test_missing_or_incorrect_undefined_hash_rejected(self):
        for digest in (None,'',True,'0'*64):
            with self.subTest(digest=digest):
                value=self.export([draft()]);item=value['rows'][0]
                if digest is None:item.pop('undefined_paths_sha256')
                else:item['undefined_paths_sha256']=digest
                (self.backup/'manifest.json').write_text(json.dumps(value))
                with self.assertRaisesRegex(ValueError,'undefined.*해시'):import_backup(self.db,self.backup,self.origin)

    def test_unicode_undefined_path_hash_uses_compact_utf8(self):
        row=draft();row['extra']={'설정/메모':[None]}
        value=self.export([row]);item=value['rows'][0];item['undefined_paths']=[['extra','설정/메모',0]]
        item['undefined_paths_sha256']=hashlib.sha256('[["extra","설정/메모",0]]'.encode()).hexdigest()
        (self.backup/'manifest.json').write_text(json.dumps(value))
        report=import_backup(self.db,self.backup,self.origin)
        self.assertEqual(report['count'],1)


if __name__=='__main__':unittest.main()
