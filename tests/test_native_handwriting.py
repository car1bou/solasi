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
