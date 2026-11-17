import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.stage_mobile_app import stage


class MobilePackagingTests(unittest.TestCase):
    def fixture(self, root):
        source = root/'lecture_study'
        source.mkdir()
        (source/'__init__.py').write_text('')
        (source/'schema.sql').write_text('CREATE TABLE sample(id);')
        (source/'credentials.py').write_text('# code only')
        (source/'.env').write_text('not for app')
        (source/'private.sqlite3').write_bytes(b'private')
        (source/'__pycache__').mkdir()
        (source/'__pycache__/file.pyc').write_bytes(b'cache')
        frontend = root/'frontend'
        frontend.mkdir()
        (frontend/'index.html').write_text('<script src="/assets/app.js"></script>')
        (frontend/'assets').mkdir()
        (frontend/'assets/app.js').write_text('export const fixture=true;')
        return source, frontend

    def test_stages_only_app_code_and_frontend_with_verified_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source,frontend=self.fixture(root)
            result=stage(source,frontend,root/'output','android')
            output=root/'output'
            self.assertEqual(result['platform'],'android')
            self.assertFalse((output/'python/lecture_study/.env').exists())
            self.assertFalse((output/'python/lecture_study/private.sqlite3').exists())
            self.assertFalse((output/'python/lecture_study/__pycache__').exists())
            self.assertEqual(json.loads((output/'manifest.json').read_text()),result)
            self.assertEqual(len(result['files']),5)
            for row in result['files']:
                data=(output/row['path']).read_bytes()
                self.assertEqual(len(data),row['bytes'])
                self.assertEqual(hashlib.sha256(data).hexdigest(),row['sha256'])

    def test_existing_destination_and_symlinked_inputs_are_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source,frontend=self.fixture(root)
            destination=root/'existing';destination.mkdir()
            marker=destination/'keep';marker.write_text('keep')
            with self.assertRaises(FileExistsError):stage(source,frontend,destination,'ios')
            self.assertEqual(marker.read_text(),'keep')
            (frontend/'assets/outside.js').symlink_to(marker)
            with self.assertRaises(ValueError):stage(source,frontend,root/'output','ios')
            self.assertFalse((root/'output').exists())

    def test_incomplete_frontend_or_unknown_platform_cannot_publish(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source,frontend=self.fixture(root)
            with self.assertRaises(ValueError):stage(source,frontend,root/'output','desktop')
            (frontend/'index.html').unlink()
            with self.assertRaises(ValueError):stage(source,frontend,root/'output','android')
            self.assertFalse((root/'output').exists())


if __name__=='__main__':unittest.main()
