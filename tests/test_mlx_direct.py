import unittest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch
from lecture_study.mlx_direct import remap_qwen_weights, generate, SUPPORTED_MODELS


class DirectMLXTests(unittest.TestCase):
    def test_verified_gemma_dispatch_and_context_profiles(self):
        self.assertEqual(SUPPORTED_MODELS['gemma4:e2b']['context_tokens'],131072)
        self.assertEqual(SUPPORTED_MODELS['gemma4:12b']['context_tokens'],262144)
        with tempfile.TemporaryDirectory() as directory:
            view=Path(directory);(view/'config.json').write_text(json.dumps({'model_type':'gemma4'}))
            with patch('lecture_study.gemma_direct.generate',return_value={'text':'서울'}) as direct:
                result=generate(view,[{'role':'user','content':'대한민국 수도'}],[],None,16,8192)
                self.assertEqual(result,{'text':'서울'});direct.assert_called_once()
    def test_nvfp4_names_keep_values_and_reject_collisions(self):
        weight, scale = object(), object()
        mapped = remap_qwen_weights({'layer.weight': weight, 'layer.weight.scale': scale})
        self.assertIs(mapped['layer.weight'], weight)
        self.assertIs(mapped['layer.scales'], scale)
        with self.assertRaises(ValueError):
            remap_qwen_weights({'layer.scales': scale, 'layer.weight.scale': scale})
        with self.assertRaises(ValueError):
            remap_qwen_weights({'layer.weight.global_scale': scale})

    def test_invalid_requests_fail_before_model_import_or_read(self):
        base = dict(view=Path('/does-not-exist'), messages=[{'role': 'user', 'content': '질문'}],
                    images=[], schema=None, output_limit=64, context_limit=8192)
        for changes in ({'output_limit': 0}, {'output_limit': True}, {'output_limit': 4097},
                        {'context_limit': 128}, {'messages': []},
                        {'messages': [{'role': 'tool', 'content': '실행'}]},
                        {'images': [Path('/missing.png')]}, {'schema': []}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                generate(**(base | changes))
