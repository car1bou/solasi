import unittest
import asyncio,contextlib,io,json,sys,tempfile
from pathlib import Path
from unittest.mock import AsyncMock,patch
from PIL import Image
from experiments.retry_handwriting import select_suspect,retry_inputs,main


class HandwritingRetryTests(unittest.TestCase):
    def test_selection_uses_only_observed_disagreement_or_edge_not_answer_key(self):
        regions=[{'text':'맞는 문장','bbox':[0.1,0.1,0.8,0.2]},
                 {'text':'다른 글','bbox':[0.1,0.5,0.8,0.2],'edge_touching':True}]
        chosen=select_suspect('맞는 문장',regions,(100,100))
        self.assertEqual(chosen['region_index'],1)
        self.assertEqual(chosen['bbox'],[0,48,100,72])
        self.assertTrue(chosen['edge_touching'])
        self.assertIsNone(select_suspect('맞는 문장',regions[:1],(100,100)))

    def test_invalid_detector_bounds_are_not_repaired_into_evidence(self):
        for bbox in ([-.1,0,.5,.3],[0,0,2,1],[0,0,0,.3],[0,0,float('nan'),.2],[0,0,True,.2]):
            self.assertIsNone(select_suspect('다른 문장',[{'text':'확인','bbox':bbox}],(100,100)))

    def test_whole_original_is_always_first_and_context_crop_is_additive(self):
        image=Image.new('RGB',(100,80),'white');image.putpixel((0,0),(1,2,3))
        inputs,messages=retry_inputs(image,[10,20,90,40],'context')
        self.assertEqual(len(inputs),2)
        self.assertEqual(inputs[0].size,(300,240))
        self.assertEqual(inputs[1].size,(300,120))
        self.assertEqual(image.getpixel((0,0)),(1,2,3))
        self.assertIn('[30, 60, 270, 120]',messages[-1]['content'])
        self.assertNotIn('맞는 문장',str(messages))
        self.assertEqual(len(retry_inputs(image,[10,20,90,40],'locate')[0]),1)

    def test_context_expansion_keeps_neighboring_lines_and_source_edges(self):
        image=Image.new('RGB',(100,80),'white')
        inputs,_=retry_inputs(image,[0,0,100,10],'context')
        self.assertEqual(inputs[1].size,(300,54))
        with self.assertRaises(ValueError):retry_inputs(image,[-1,0,20,10],'context')
        with self.assertRaises(ValueError):retry_inputs(image,[0,0,20,10],'unknown')

    def test_runner_passes_whole_and_crop_without_reference_and_stops_worker(self):
        from experiments.compare_handwriting import file_hash
        with tempfile.TemporaryDirectory()as folder:
            root=Path(folder);image=root/'one.png';Image.new('RGB',(100,80),'white').save(image)
            manifest=root/'manifest.json';manifest.write_text(json.dumps({'cases':[{'id':'test','image':str(image),'source_sha256':file_hash(image),'bbox':[10,20,90,40],'reference':'정답 누출 금지'}]}))
            argv=['retry_handwriting.py','--manifest',str(manifest),'--runtime',str(root/'runtime'),'--output',str(root/'results'),'--mode','context']
            manager=type('Manager',(),{'generate':AsyncMock(return_value={'text':'후보','finish_reason':'stop'}),'stop':AsyncMock()})()
            with patch.object(sys,'argv',argv),patch('lecture_study.direct_models.DirectModels',return_value=manager),patch('lecture_study.model_assets.installed_asset',return_value={'digest':'test'}),contextlib.redirect_stdout(io.StringIO()):
                asyncio.run(main())
            args=manager.generate.await_args.args
            self.assertEqual(len(args[2]),2);self.assertNotIn('정답 누출 금지',str(args[1]))
            self.assertEqual(json.loads((root/'results/00.json').read_text())['source_sha256'],file_hash(image))
            manager.stop.assert_awaited_once()
