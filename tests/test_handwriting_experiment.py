import unittest
import tempfile
from pathlib import Path
from PIL import Image
from experiments.compare_handwriting import prepare_images,record_run,native_prompt


class HandwritingPreprocessingTests(unittest.TestCase):
    def test_native_ocr_tasks_use_each_models_supported_prompt(self):
        self.assertEqual(native_prompt({'model_type':'glm_ocr'},'ocr'),'Text Recognition:')
        self.assertEqual(native_prompt({'model_type':'glm_ocr'},'formula'),'Formula Recognition:')
        self.assertEqual(native_prompt({'model_type':'paddleocr_vl'},'ocr'),'OCR:')
        self.assertEqual(native_prompt({'model_type':'paddleocr_vl'},'formula'),'Formula Recognition:')
        self.assertEqual(native_prompt({'model_type':'deepseekocr_2'},'ocr'),'Free OCR.')
        self.assertEqual(native_prompt({'model_type':'dots_ocr'},'ocr'),'Extract the text content from this image.')
        self.assertEqual(native_prompt({'model_type':'lighton_ocr'},'ocr'),'')
        self.assertEqual(native_prompt({'model_type':'qwen3_5'},'ocr'),'')

    def test_unsupported_native_model_or_task_is_not_silently_run(self):
        for model,task in [('deepseekocr_2','formula'),('dots_ocr','formula'),('unknown','ocr'),('glm_ocr','unknown')]:
            with self.subTest(model=model,task=task),self.assertRaises(ValueError):native_prompt({'model_type':model},task)

    def test_checkpoint_python_is_rejected_by_native_config_validation(self):
        with self.assertRaisesRegex(ValueError,'checkpoint Python'):
            native_prompt({'model_type':'glm_ocr','model_file':'custom.py'},'ocr')

    def test_invalid_native_configs_are_rejected_without_model_loading(self):
        for config in (None,[],{}, {'model_type':[]},{'model_type':True}):
            with self.subTest(config=config),self.assertRaises(ValueError):native_prompt(config,'ocr')

    def setUp(self):
        self.image=Image.new('RGB',(100,50),'white')
        self.image.putpixel((99,25),(0,0,0))

    def test_padding_preserves_edge_ink_and_original_image(self):
        result=prepare_images(self.image,'padding')[0]
        self.assertEqual(result.size,(116,66))
        self.assertEqual(result.getpixel((107,33)),(0,0,0))
        self.assertEqual(result.getpixel((115,33)),(255,255,255))
        self.assertEqual(self.image.size,(100,50))

    def test_upscale_bounds_long_edge_without_distorting_aspect(self):
        self.assertEqual(prepare_images(self.image,'upscale')[0].size,(300,150))
        large=Image.new('RGB',(1200,600),'white')
        self.assertEqual(prepare_images(large,'upscale')[0].size,(2048,1024))

    def test_tiles_keep_context_overlap_and_outer_edges(self):
        parts=prepare_images(self.image,'tiles')
        self.assertEqual([p.size for p in parts],[(100,37),(100,37)])
        self.assertEqual(parts[1].getpixel((99,12)),(0,0,0))

    def test_unknown_variant_is_rejected(self):
        with self.assertRaises(ValueError):prepare_images(self.image,'unknown')

    def test_changed_input_or_prompt_cannot_reuse_previous_response_cache(self):
        with tempfile.TemporaryDirectory()as folder:
            path=Path(folder)/'run.json'
            record_run(path,{'input':'abc','prompt':'literal'})
            record_run(path,{'input':'abc','prompt':'literal'})
            with self.assertRaises(ValueError):record_run(path,{'input':'changed','prompt':'literal'})
            with self.assertRaises(ValueError):record_run(path,{'input':'abc','prompt':'changed'})

    def test_unidentified_old_response_cache_is_not_adopted(self):
        with tempfile.TemporaryDirectory()as folder:
            path=Path(folder)/'run-config.json';(path.parent/'mixed-one-model.json').write_text('{}')
            with self.assertRaises(ValueError):record_run(path,{'prompt':'new'})
            self.assertFalse(path.exists())
