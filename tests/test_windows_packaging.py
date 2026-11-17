import hashlib,io,json,subprocess,tempfile,unittest,zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from scripts.build_windows_runtime import extract_zip, write_receipt, webview_installer
from scripts.freeze_windows_app import copy_engine, freeze


class WindowsPackagingTests(unittest.TestCase):
    def test_freeze_normalizes_destination_before_staging(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();source=root/'source';source.mkdir()
            (root/'frontend/dist').mkdir(parents=True);(root/'frontend/dist/index.html').write_text('fixture')
            with patch('scripts.freeze_windows_app.os',SimpleNamespace(name='nt')), patch(
                    'scripts.freeze_windows_app.platform.machine',return_value='AMD64'), patch(
                    'scripts.freeze_windows_app.sys.version_info',(3,12,0)), patch(
                    'scripts.freeze_windows_app.importlib.metadata.version',return_value='6.22.3'), patch(
                    'scripts.freeze_windows_app.ROOT',root), patch(
                    'scripts.freeze_windows_app.tempfile.TemporaryDirectory',side_effect=RuntimeError('stop before build')) as stage:
                with self.assertRaisesRegex(RuntimeError,'stop before build'):
                    freeze(root/'runtime',root/'models',source/'..'/'Solasi')
                self.assertEqual(stage.call_args.kwargs['dir'],root)

    def test_freeze_refuses_dangling_output_symlink_before_normalizing(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);output=root/'Solasi'
            try:output.symlink_to(root/'missing',target_is_directory=True)
            except OSError as error:self.skipTest('Symlinks unavailable: '+str(error))
            with patch('scripts.freeze_windows_app.os',SimpleNamespace(name='nt')), patch(
                    'scripts.freeze_windows_app.platform.machine',return_value='AMD64'), patch(
                    'scripts.freeze_windows_app.sys.version_info',(3,12,0)), patch(
                    'scripts.freeze_windows_app.importlib.metadata.version',return_value='6.22.3'):
                with self.assertRaises(FileExistsError):freeze(root/'runtime',root/'models',output)
            self.assertTrue(output.is_symlink());self.assertFalse((root/'missing').exists())

    def test_webview_installer_requires_vendor_signature(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'webview/setup.exe'
            with patch('scripts.build_windows_runtime.urlopen',return_value=io.BytesIO(b'installer')), patch(
                    'scripts.build_windows_runtime.subprocess.run',side_effect=subprocess.CalledProcessError(1,'powershell')) as verify:
                with self.assertRaises(subprocess.CalledProcessError):webview_installer(target)
            self.assertEqual(target.read_bytes(),b'installer')
            self.assertTrue(verify.call_args.kwargs['check'])
            self.assertEqual(verify.call_args.kwargs['env']['SOLASI_WEBVIEW_INSTALLER'],str(target))
            self.assertIn('O=Microsoft Corporation',verify.call_args.args[0][-1])

    def test_zip_rejects_traversal_and_duplicate_paths_before_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name in ('../outside','C:/outside','root\\outside'):
                archive=root/'bad.zip'
                item=zipfile.ZipInfo(name);item.filename=name
                with zipfile.ZipFile(archive,'w') as z:z.writestr(item,b'bad')
                with self.assertRaises(ValueError):extract_zip(archive,root/'out')
                self.assertFalse((root/'outside').exists())

    def test_zip_validates_original_name_before_windows_normalization(self):
        item=zipfile.ZipInfo('root/outside');item.orig_filename='root\\outside'
        with patch('scripts.build_windows_runtime.zipfile.ZipFile') as archive:
            archive.return_value.__enter__.return_value.infolist.return_value=[item]
            with self.assertRaises(ValueError):extract_zip('unused.zip',Path('unused'))

    def test_bundle_copies_only_receipted_files_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source';(source/'bin').mkdir(parents=True)
            (source/'bin/tool.exe').write_bytes(b'executable');(source/'LICENSE').write_text('license')
            write_receipt(source,'fixture')
            copy_engine(source,root/'app')
            self.assertEqual((root/'app/bin/tool.exe').read_bytes(),b'executable')
            (source/'bin/tool.exe').write_bytes(b'tampered')
            with self.assertRaises(ValueError):copy_engine(source,root/'other')
            self.assertFalse((root/'other').exists())

    def test_bundle_rejects_unlisted_libraries_and_external_receipt_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source';source.mkdir();(source/'tool.exe').write_bytes(b'tool')
            write_receipt(source,'fixture');(source/'evil.dll').write_bytes(b'evil')
            with self.assertRaises(ValueError):copy_engine(source,root/'app')
            item={'bytes':4,'sha256':hashlib.sha256(b'tool').hexdigest()}
            (source/'receipt.json').write_text(json.dumps({'files':{'../outside':item}}))
            with self.assertRaises(ValueError):copy_engine(source,root/'app')


if __name__=='__main__':unittest.main()
