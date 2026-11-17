from pathlib import Path
import tempfile
import unittest

from lecture_study import mobile_documents
from lecture_study.materials import source_status


class MobileDocumentsTests(unittest.TestCase):
    def tearDown(self):mobile_documents.install(None)

    def test_registered_provider_detects_change_or_revoked_access_despite_unchanged_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'한글 원본.txt';path.write_text('fixture')
            info=path.stat();asset={'external_path':str(path),'size':info.st_size,'mtime_ns':info.st_mtime_ns}
            for state in ('changed','denied','missing'):
                mobile_documents.install(lambda candidate,state=state:state)
                self.assertEqual(source_status(None,asset),state)
            mobile_documents.install(lambda candidate:'current')
            self.assertEqual(source_status(None,asset),'current')
            path.unlink()
            self.assertEqual(source_status(None,asset),'missing')

    def test_unknown_paths_and_desktop_keep_existing_file_checks(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'fixture.txt';path.write_text('fixture')
            info=path.stat();asset={'external_path':str(path),'size':info.st_size,'mtime_ns':info.st_mtime_ns}
            self.assertEqual(source_status(None,asset),'current')
            mobile_documents.install(lambda candidate:None)
            self.assertEqual(source_status(None,asset),'current')
            path.write_text('changed fixture')
            self.assertEqual(source_status(None,asset),'changed')

    def test_invalid_or_failed_provider_never_claims_current(self):
        mobile_documents.install(lambda path:'unexpected')
        with self.assertRaises(ValueError):mobile_documents.status('/private/native-snapshot')
        def failed(path):raise OSError('provider is unavailable')
        mobile_documents.install(failed)
        self.assertEqual(mobile_documents.status('/private/native-snapshot'),'denied')
        with self.assertRaises(TypeError):mobile_documents.install('not callable')


if __name__=='__main__':unittest.main()
