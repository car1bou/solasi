import hashlib
import json
from pathlib import Path
import plistlib
import tempfile
import unittest

from scripts.install_macos_app import BUNDLE_ID, read_existing_settings, verify_engine, validate_draft_migration


class MacInstallTests(unittest.TestCase):
    def test_old_and_new_launch_settings_keep_storage_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            app=Path(folder)/'Solasi.app';resources=app/'Contents/Resources';resources.mkdir(parents=True)
            with (app/'Contents/Info.plist').open('wb') as handle:plistlib.dump({'CFBundleIdentifier':BUNDLE_ID,'CFBundleExecutable':'Solasi'},handle)
            for settings in ({'data':'/vault','runtime':'/models'}, {'data':'/vault','runtime':'/models','python':'/python','source':'/source','port':62434}):
                (resources/'launch.json').write_text(json.dumps(settings))
                self.assertEqual(read_existing_settings(app),settings)
            (resources/'launch.json').write_text('{"data":"relative","runtime":"/models"}')
            with self.assertRaises(ValueError):read_existing_settings(app)

    def test_engine_corruption_and_missing_draft_proof_prevent_replace(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);engine=root/'solasi-engine';engine.write_bytes(b'bin')
            (root/'bundle-manifest.json').write_text(json.dumps({'format':1,'files':{'solasi-engine':{'bytes':3,'sha256':hashlib.sha256(b'bin').hexdigest()}}}))
            verify_engine(root)
            engine.write_bytes(b'bad')
            with self.assertRaises(ValueError):verify_engine(root)
            with self.assertRaises(ValueError):validate_draft_migration(root,None)


if __name__=='__main__':unittest.main()
