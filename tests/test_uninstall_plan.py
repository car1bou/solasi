import importlib.util,json,plistlib,tempfile,unittest
from pathlib import Path
from lecture_study.config import AppConfig
from lecture_study.db import open_db

class UninstallPlanTests(unittest.TestCase):
    def test_only_proven_owned_files_are_planned_and_backups_experiments_survive(self):
        self.assertIsNotNone(importlib.util.find_spec('lecture_study.uninstall_plan'),'owned deletion planner missing')
        from lecture_study.uninstall_plan import build_plan
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();cfg=AppConfig(root/'vault',root/'runtime',embedded=True)
            cfg.runtime_dir.mkdir();db=open_db(cfg.data_dir);self.addCleanup(db.close)
            (cfg.data_dir/'before-backup.sqlite3').write_bytes(b'backup')
            cache=cfg.data_dir/'model-cache'/('a'*64);cache.mkdir(parents=True)
            (cache/'independent-backup.sqlite3').write_bytes(b'backup inside cache')
            (cfg.runtime_dir/'experiment.wav').write_bytes(b'private experiment')
            models=cfg.runtime_dir/'ollama-models/blobs';models.mkdir(parents=True);(models/('sha256-'+'a'*64)).write_bytes(b'model')
            bundle=root/'Solasi.app';resources=bundle/'Contents/Resources';resources.mkdir(parents=True)
            (resources/'launch.json').write_text(json.dumps({'data':str(cfg.data_dir),'runtime':str(cfg.runtime_dir)}))
            (bundle/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'local.solasi.internal-validation','CFBundleExecutable':'Solasi'}))
            receipt={'id':'a'*32,'manifest':'/not-used','manifest_sha256':'b'*64,'directory':str(root/'exports'),'files':[],'selection':dict(documents=False,audio=False,results=False)}
            plan=build_plan(db,cfg,bundle,receipt)
            paths=[x['path'] for x in plan['targets']]
            self.assertIn(str(cfg.data_dir/'app.sqlite3'),paths)
            self.assertIn(str(models/('sha256-'+'a'*64)),paths)
            self.assertEqual(paths[-1],str(bundle))
            self.assertNotIn(str(cfg.data_dir),paths);self.assertNotIn(str(cfg.runtime_dir),paths)
            self.assertNotIn(str(cfg.data_dir/'model-cache'),paths)
            self.assertIn(str(cache/'independent-backup.sqlite3'),plan['preserved'])
            self.assertIn(str(cfg.data_dir/'before-backup.sqlite3'),plan['preserved'])
            self.assertIn(str(cfg.runtime_dir/'experiment.wav'),plan['preserved'])
            self.assertTrue((cfg.data_dir/'before-backup.sqlite3').exists())
            (resources/'launch.json').write_text(json.dumps({'data':str(root),'runtime':str(cfg.runtime_dir)}))
            with self.assertRaises(ValueError):build_plan(db,cfg,bundle,receipt)
