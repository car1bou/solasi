import hashlib
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from lecture_study.model_assets import installed_asset, prepare_mlx_view


class ModelAssetsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'models'
        (self.root / 'blobs').mkdir(parents=True)
        self.manifest = self.root / 'manifests/registry.ollama.ai/library/example/latest'
        self.manifest.parent.mkdir(parents=True)
        self.layers = [self.blob(b'{"model_type":"example"}', 'json', 'config.json'),
                       self.blob(self.tensor(), 'tensor', 'layer.weight')]
        self.write_manifest()

    def tensor(self):
        header = json.dumps({'layer.weight': {'dtype': 'U32', 'shape': [1, 1],
                                             'data_offsets': [0, 4]}}).encode()
        return struct.pack('<Q', len(header)) + header + b'\0' * 4

    def blob(self, data, kind, name):
        digest = hashlib.sha256(data).hexdigest()
        (self.root / 'blobs' / ('sha256-' + digest)).write_bytes(data)
        return {'mediaType': 'application/vnd.ollama.image.' + kind, 'name': name,
                'size': len(data), 'digest': 'sha256:' + digest}

    def write_manifest(self):
        self.manifest.write_text(json.dumps({'schemaVersion': 2, 'layers': self.layers,
                                            'config': self.blob(b'{}', 'config', None)}))

    def test_view_reuses_weights_and_preserves_source(self):
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (self.root/'blobs').iterdir()}
        asset = installed_asset(self.root, 'example')
        self.assertEqual(asset['format'], 'safetensors')
        view = prepare_mlx_view(asset, Path(self.temp.name)/'view')
        self.assertEqual(json.loads((view/'config.json').read_text()), {'model_type': 'example'})
        index = json.loads((view/'model.safetensors.index.json').read_text())['weight_map']
        weight = view/index['layer.weight']
        self.assertTrue(weight.is_symlink())
        self.assertEqual(weight.read_bytes(), self.tensor())
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before})
        with self.assertRaises(FileExistsError): prepare_mlx_view(asset, view)

    def test_interrupted_creation_does_not_publish_partial_view_and_retry_succeeds(self):
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (self.root/'blobs').iterdir()}
        destination=Path(self.temp.name)/'view'
        script = """
import os,sys
from pathlib import Path
from lecture_study.model_assets import installed_asset,prepare_mlx_view
original=Path.write_text
def stop_before_index(path,*args,**kwargs):
    if path.name=='model.safetensors.index.json':os._exit(23)
    return original(path,*args,**kwargs)
Path.write_text=stop_before_index
prepare_mlx_view(installed_asset(Path(sys.argv[1]),'example'),Path(sys.argv[2]))
"""
        result=subprocess.run([sys.executable,'-B','-c',script,str(self.root),str(destination)],capture_output=True)
        self.assertEqual(result.returncode,23,result.stderr)
        self.assertFalse(destination.exists())
        asset=installed_asset(self.root,'example')
        view=prepare_mlx_view(asset,destination)
        self.assertTrue((view/'model.safetensors.index.json').is_file())
        self.assertEqual(before,{p:(p.read_bytes(),p.stat().st_mtime_ns) for p in before})

    def test_publish_never_replaces_a_racing_empty_directory(self):
        import lecture_study.model_assets as assets
        destination=Path(self.temp.name)/'view'
        original=assets._rename_exclusive
        def race(source,target):
            target.mkdir()
            inode=target.stat().st_ino
            try:return original(source,target)
            finally:self.assertEqual(target.stat().st_ino,inode)
        with patch.object(assets,'_rename_exclusive',side_effect=race),self.assertRaises(FileExistsError):
            prepare_mlx_view(installed_asset(self.root,'example'),destination)
        self.assertEqual(list(destination.iterdir()),[])

    def test_missing_size_and_digest_fail_closed(self):
        for change in ('missing', 'size', 'hash'):
            with self.subTest(change=change):
                original = self.layers[1].copy()
                path = self.root/'blobs'/original['digest'].replace(':', '-')
                content = path.read_bytes()
                if change == 'missing': path.unlink()
                elif change == 'size': self.layers[1]['size'] += 1; self.write_manifest()
                else: path.write_bytes(b'x' * len(content))
                with self.assertRaises(ValueError): installed_asset(self.root, 'example')
                path.write_bytes(content); self.layers[1] = original; self.write_manifest()

    def test_unsafe_model_or_layer_path_rejected(self):
        for name in ('../example', 'example:../latest', '/example', 'example@remote'):
            with self.subTest(name=name), self.assertRaises(ValueError): installed_asset(self.root, name)
        self.layers[0]['name'] = '../config.json'; self.write_manifest()
        with self.assertRaises(ValueError): installed_asset(self.root, 'example')

    def test_duplicate_tensor_key_rejected(self):
        self.layers.append(self.layers[1].copy()); self.write_manifest()
        with self.assertRaises(ValueError): installed_asset(self.root, 'example')

    def test_oversized_tensor_header_rejected(self):
        self.layers[1] = self.blob(struct.pack('<Q', 2**40), 'tensor', 'layer.weight')
        self.write_manifest()
        with self.assertRaises(ValueError): installed_asset(self.root, 'example')

    def test_blob_symlink_outside_models_rejected(self):
        path = self.root/'blobs'/self.layers[1]['digest'].replace(':', '-')
        other = Path(self.temp.name)/'outside'; other.write_bytes(path.read_bytes())
        path.unlink(); path.symlink_to(other)
        with self.assertRaises(ValueError): installed_asset(self.root, 'example')

    def test_gguf_preserves_readonly_original_path(self):
        self.layers = [self.blob(b'GGUF' + struct.pack('<I', 3), 'model', None)]
        self.write_manifest()
        asset = installed_asset(self.root, 'example')
        self.assertEqual(asset['format'], 'gguf')
        self.assertEqual(asset['files'][0]['path'].read_bytes(), b'GGUF' + struct.pack('<I', 3))
        with self.assertRaises(ValueError): prepare_mlx_view(asset, Path(self.temp.name)/'view')
