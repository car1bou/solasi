import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(sys.platform == 'darwin' and shutil.which('xcrun'), 'macOS Swift compiler required')
class NativeWindowTests(unittest.TestCase):
    def test_native_titlebar_stays_outside_web_content_and_minimum_size_fits(self):
        root=Path(__file__).resolve().parents[1]
        source=(root/'macos/Solasi.swift').read_text().split('final class SolasiApp:',1)[0]
        source+='''
let app = NSApplication.shared
private let page = AppWindow(configuration: WKWebViewConfiguration())
precondition(!page.window.styleMask.contains(.fullSizeContentView), "web content covers native drag region")
precondition(page.window.isMovable && page.window.styleMask.contains(.resizable))
page.window.setFrame(NSRect(x: 100, y: 100, width: 680, height: 480), display: false)
page.window.contentView?.layoutSubtreeIfNeeded()
precondition(page.window.frame.size == NSSize(width: 680, height: 480))
precondition(page.window.minSize == NSSize(width: 680, height: 480))
precondition(page.resizeHandle.frame.width >= 32 && page.resizeHandle.frame.height >= 28)
let resized = WindowResizeHandle.resizedFrame(NSRect(x: 100,y: 100,width: 1200,height: 820), delta: NSPoint(x: -900,y: 700), minimum: NSSize(width: 680,height: 480))
precondition(resized == NSRect(x: 100,y: 440,width: 680,height: 480))
print("native drag region reserved; 680x480 frame accepted")
'''
        with tempfile.TemporaryDirectory(prefix='solasi-window-') as folder:
            path=Path(folder)/'window.swift';path.write_text(source);binary=Path(folder)/'window'
            compiled=subprocess.run(['xcrun','swiftc','-module-cache-path',str(root/'.local-state/swift-cache'),str(path),'-o',str(binary)],capture_output=True,text=True,timeout=90)
            self.assertEqual(compiled.returncode,0,compiled.stdout+compiled.stderr)
            result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('native drag region reserved; 680x480 frame accepted',result.stdout)
