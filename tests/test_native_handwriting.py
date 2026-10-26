import shutil,subprocess,sys,tempfile,unittest
from pathlib import Path


@unittest.skipUnless(sys.platform=='darwin'and shutil.which('xcrun'),'macOS Swift compiler required')
class NativeHandwritingTests(unittest.TestCase):
    def test_vision_rounding_outside_image_keeps_valid_source_coordinates(self):
        root=Path(__file__).resolve().parents[1]
        source=(root/'macos/HandwritingRecognition.swift').read_text().split('\ndo {',1)[0]
        source+='''
let box = sourceBox(CGRect(x: 0.02, y: 0.828, width: 0.244, height: 0.173))
precondition(box[0] == 0.02 && box[1] == 0)
precondition(abs(box[2] - 0.244) < 0.000001 && abs(box[3] - 0.172) < 0.000001)
let right = sourceBox(CGRect(x: 0.9, y: 0.3, width: 0.101, height: 0.2))
precondition(right[0] + right[2] <= 1 && right[1] + right[3] <= 1)
print("source coordinates clipped to actual image")
'''
        with tempfile.TemporaryDirectory()as folder:
            path=Path(folder)/'fixture.swift';path.write_text(source);binary=Path(folder)/'fixture'
            built=subprocess.run(['xcrun','swiftc','-module-cache-path',str(root/'.local-state/swift-cache'),str(path),'-o',str(binary)],capture_output=True,text=True,timeout=90)
            self.assertEqual(built.returncode,0,built.stderr)
            result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)


@unittest.skipUnless(sys.platform=='darwin'and shutil.which('xcrun'),'macOS Swift compiler required')
class NativeRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.folder.cleanup)
        cls.root=Path(cls.folder.name);cls.binary=cls.root/'helper'
        project=Path(__file__).resolve().parents[1]
        built=subprocess.run(['xcrun','swiftc','-module-cache-path',str(project/'.local-state/swift-cache'),str(project/'macos/HandwritingRecognition.swift'),'-o',str(cls.binary)],capture_output=True,text=True,timeout=90)
        if built.returncode:raise RuntimeError(built.stderr)

    def run_helper(self,payload,*arguments):
        import json
        return subprocess.run([str(self.binary),'--render-only',*map(str,arguments)],input=json.dumps(payload).encode(),capture_output=True,timeout=90)

    def test_render_only_keeps_pen_geometry_and_omits_ocr(self):
        import json
        from PIL import Image
        payload={'page_width':100,'page_height':80,'strokes':[
            {'tool':'pen','width':.04,'points':[{'x':.25,'y':.2,'pressure':1}]},
            {'tool':'pen','width':.04,'points':[{'x':.6,'y':.2,'pressure':0}]},
            {'tool':'highlighter','width':.04,'points':[{'x':.8,'y':.75,'pressure':1}]}]}
        output=self.root/'ink.png';result=self.run_helper(payload,'--image',output)
        self.assertEqual(result.returncode,0,result.stderr.decode())
        metadata=json.loads(result.stdout)
        self.assertEqual(metadata,{'renderer':'macos-coregraphics-v1','width':300,'height':240})
        with Image.open(output)as image:
            rgb=image.convert('RGB');self.assertEqual(rgb.size,(300,240))
            self.assertEqual(rgb.getpixel((75,48)),(0,0,0));self.assertEqual(rgb.getpixel((75,192)),(255,255,255))
            self.assertEqual(rgb.getpixel((240,180)),(255,255,255))
            self.assertLess(rgb.getpixel((79,48))[0],30);self.assertGreater(rgb.getpixel((184,48))[0],240)

    def test_render_only_requires_output_and_validates_strokes(self):
        payload={'page_width':100,'page_height':80,'strokes':[]}
        self.assertNotEqual(self.run_helper(payload).returncode,0)
        bad={**payload,'strokes':[{'tool':'pen','width':.02,'points':[{'x':-1,'y':.2,'pressure':1}]}]}
        self.assertNotEqual(self.run_helper(bad,'--image',self.root/'invalid.png').returncode,0)

    def test_render_only_composites_original_image_without_flipping_it(self):
        from PIL import Image
        original=self.root/'page.png';image=Image.new('RGB',(100,80),'white')
        image.paste((255,0,0),(0,0,40,20));image.save(original)
        output=self.root/'page-render.png'
        result=self.run_helper({'page_width':100,'page_height':80,'strokes':[]},'--image',output,'--page-source',original,'1')
        self.assertEqual(result.returncode,0,result.stderr.decode())
        with Image.open(output)as image:
            self.assertEqual(image.convert('RGB').getpixel((30,15)),(255,0,0))
            self.assertEqual(image.convert('RGB').getpixel((30,225)),(255,255,255))
