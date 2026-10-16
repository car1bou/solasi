import hashlib,json,tempfile,unittest
from pathlib import Path
from experiments.evaluate_sentence_asr import load_clips

class AsrManifestTests(unittest.TestCase):
    def test_custom_preselected_manifest_keeps_references_and_records_its_hash(self):
        with tempfile.TemporaryDirectory()as root:
            path=Path(root)/'selection.json';clip={'path':'/local/voice.wav','sha256':'a'*64,'group':'original','reference':'실제 정답'};path.write_text(json.dumps({'clips':[clip]},ensure_ascii=False))
            clips,proof=load_clips(path)
            self.assertEqual(clips,[clip]);self.assertEqual(proof,{str(path):hashlib.sha256(path.read_bytes()).hexdigest()})
            for rows in ([],[clip,clip]):
                path.write_text(json.dumps({'clips':rows}))
                with self.assertRaises(ValueError):load_clips(path)
