import shutil,subprocess,sys,tempfile,unittest
from pathlib import Path

@unittest.skipUnless(sys.platform=='darwin' and shutil.which('xcrun'),'Mac AppKit required')
class NativeUninstallChoiceTests(unittest.TestCase):
    def test_native_dialog_offers_preserve_or_delete_for_each_category(self):
        root=Path(__file__).resolve().parents[1];source=root/'macos/UninstallChoice.swift'
        self.assertTrue(source.exists(),'the uninstall dialog must contain its own editable category choices')
        with tempfile.TemporaryDirectory(prefix='solasi-uninstall-ui-') as directory:
            path=Path(directory);fixture=path/'Fixture.swift';binary=path/'fixture'
            fixture.write_text('''import AppKit
@main enum Fixture { static func main() {
 _ = NSApplication.shared
 let choice=UninstallChoiceView(selection:["documents":true,"audio":true,"results":true])
 precondition(choice.selection == ["documents":true,"audio":true,"results":true])
 let grid=choice.arrangedSubviews.compactMap{$0 as? NSGridView}.first!
 let controls=(0..<3).map{grid.cell(atColumnIndex:1,rowIndex:$0).contentView as! NSSegmentedControl}
 for flags in 0..<8 {
  for i in 0..<3 { controls[i].selectedSegment = flags & (1<<i) != 0 ? 0 : 1 }
  precondition(choice.selection["documents"] == (flags & 1 != 0))
  precondition(choice.selection["audio"] == (flags & 2 != 0))
  precondition(choice.selection["results"] == (flags & 4 != 0))
 }
 print("all eight explicit preserve/delete combinations work")
} }
''')
            built=subprocess.run(['xcrun','swiftc','-module-cache-path',str(root/'.local-state/swift-cache'),str(source),str(fixture),'-o',str(binary)],capture_output=True,text=True,timeout=90)
            self.assertEqual(built.returncode,0,built.stderr)
            result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr);self.assertIn('eight explicit',result.stdout)

    def test_missing_helper_returns_to_normal_state_instead_of_blocking_retry_and_quit(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='solasi-uninstall-missing-') as directory:
            path=Path(directory);fixture=path/'Host.swift';binary=path/'host'
            source=(root/'macos/Solasi.swift').read_text().split('@main\nenum SolasiMain',1)[0]
            fixture.write_text(source+'''
extension SolasiApp {
 func checkMissingHelper() {
  for reset in [false,true] {
  uninstalling=true
  let page=AppWindow(configuration:WKWebViewConfiguration())
  var returned=false
  beginUninstall(page:page,selection:["documents":true,"audio":true,"results":true],reset:reset) { _,error in precondition(error != nil);returned=true }
  precondition(returned && !uninstalling,"missing helper must release uninstall state for retry and normal quit")
  }
 }
}
@main enum Fixture { static func main() { _ = NSApplication.shared; SolasiApp().checkMissingHelper(); print("retry and quit unblocked") } }
''')
            files=['WorkerBridge.swift','AppResources.swift','AudioCapture.swift','AudioPlayback.swift','UninstallPlan.swift','UninstallChoice.swift']
            built=subprocess.run(['xcrun','swiftc','-module-cache-path',str(root/'.local-state/swift-cache'),*[str(root/'macos'/name) for name in files],str(fixture),'-o',str(binary)],capture_output=True,text=True,timeout=90)
            self.assertEqual(built.returncode,0,built.stderr)
            result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
