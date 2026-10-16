import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from lecture_study.gemma_direct import remap_weights, quantization_from_header, render_prompt, parse_response, generate


class DirectGemmaTests(unittest.TestCase):
    def test_metadata_and_remapping_preserve_values(self):
        weight, scale, global_scale = object(), object(), object()
        mapped = remap_weights({'model.x.weight': weight, 'model.x.weight.scale': scale,
                                'model.x.weight.global_scale': global_scale, 'draft.x.weight': object()})
        self.assertEqual(mapped, {'model.x.weight': weight, 'model.x.scales': scale, 'model.x.weight_scale_2': global_scale})
        with self.assertRaises(ValueError): remap_weights({'x.weight.scale': scale, 'x.scales': scale})
        header = {'__metadata__': {'group_size': '32', 'quant_type': 'mxfp8'},
                  'model.language_model.embed_tokens.weight': {'dtype': 'U32'}}
        self.assertEqual(quantization_from_header(header), {'language_model.model.embed_tokens': {'group_size': 32, 'bits': 8, 'mode': 'mxfp8'}})
        header['__metadata__'] = {'quant_type': 'nvfp4'}
        self.assertEqual(quantization_from_header(header)['language_model.model.embed_tokens']['group_size'], 16)
        header['__metadata__']['group_size'] = '32'
        with self.assertRaises(ValueError): quantization_from_header(header)
        header['__metadata__']['quant_type'] = 'unknown'
        with self.assertRaises(ValueError): quantization_from_header(header)

    def test_source_backed_turn_format_and_image_placeholder(self):
        messages = [{'role': 'system', 'content': ' 규칙 '}, {'role': 'user', 'content': '첫째'},
                    {'role': 'assistant', 'content': '답'}, {'role': 'assistant', 'content': '변'},
                    {'role': 'user', 'content': ' 마지막 '}]
        self.assertEqual(render_prompt(messages, 1), '<bos><|turn>system\n규칙<turn|>\n<|turn>user\n첫째<turn|>\n<|turn>model\n답변<turn|>\n<|turn>user\n<|image|>\n마지막<turn|>\n<|turn>model\n')
        with self.assertRaises(ValueError): render_prompt([{'role': 'assistant', 'content': 'x'}], 1)

    def test_official_channels_leave_answer_and_ordinary_text_unchanged(self):
        self.assertEqual(parse_response('<|channel>thought\n<channel|>서울입니다.'), '서울입니다.')
        self.assertEqual(parse_response('앞<|channel>thought\n내부<channel|>뒤'), '앞뒤')
        self.assertEqual(parse_response('확인<|channel>thought\n미완료'), '확인')
        self.assertEqual(parse_response('가정: 돌아가신다면. - 원문 유지'), '가정: 돌아가신다면. - 원문 유지')
        self.assertEqual(parse_response('<|channel>thought\n미완료'), '')

    def test_invalid_requests_fail_without_model_import(self):
        base = dict(view=Path('/does-not-exist'), messages=[{'role': 'user', 'content': '질문'}],
                    images=[], schema=None, output_limit=64, context_limit=8192)
        for changes in ({'output_limit': 0}, {'output_limit': True}, {'context_limit': 128},
                        {'messages': []}, {'messages': [{'role': 'tool', 'content': '실행'}]},
                        {'schema': []}, {'images': [Path('/missing.png')]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): generate(**(base | changes))


@unittest.skipUnless(os.environ.get('SOLASI_GEMMA_MODEL_VIEW'), 'set SOLASI_GEMMA_MODEL_VIEW for actual-model contracts')
class GemmaModelTests(unittest.TestCase):
    def test_korean_json_vision_and_actual_token_budgets(self):
        from lecture_study import gemma_direct
        from PIL import Image
        view = Path(os.environ['SOLASI_GEMMA_MODEL_VIEW'])
        model, processor = gemma_direct.load(view)
        base = dict(view=view, messages=[{'role': 'user', 'content': '대한민국의 수도는 어디인가요? 한 문장으로 답하세요.'}],
                    images=[], schema=None, output_limit=96, context_limit=2048)
        with patch.object(gemma_direct, 'load', return_value=(model, processor)):
            result = generate(**base)
            self.assertIn('서울', result['text']); self.assertNotIn('<|channel>', result['text'])
            schema = {'type': 'object', 'properties': {'city': {'type': 'string'}},
                      'required': ['city'], 'additionalProperties': False}
            result = generate(**(base | {'schema': schema, 'messages': [{'role': 'user', 'content': '대한민국 수도를 city 필드에 한국어로 적어 JSON만 답하세요.'}]}))
            self.assertIn('서울', json.loads(result['text'])['city'])
            with tempfile.TemporaryDirectory() as folder:
                image = Path(folder)/'red.png'; Image.new('RGB', (128, 128), (255, 0, 0)).save(image)
                result = generate(**(base | {'images': [image], 'messages': [{'role': 'user', 'content': '이미지의 주된 색을 한국어로 한 단어로 답하세요.'}]}))
                self.assertTrue(any(word in result['text'] for word in ['빨간', '빨강', '붉은', '적색']))
                self.assertGreater(result['usage']['prompt_eval_count'], 200)
            result = generate(**(base | {'output_limit': 12, 'messages': [{'role': 'user', 'content': '한 문장보다 길게 한국어로 지구와 태양의 관계를 설명하세요.'}]}))
            self.assertLessEqual(result['usage']['eval_count'], 12)
            with self.assertRaisesRegex(ValueError, '문맥 예산'):
                generate(**(base | {'context_limit': 512, 'messages': [{'role': 'user', 'content': '한국어로 내용을 설명합니다. '*1000}]}))
