import AppKit
import WebKit

@main
final class WebViewFixture: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    var webView: WKWebView!
    var root: URL!
    var lastResult=""
    static func main() {
        let app = NSApplication.shared
        let delegate = WebViewFixture()
        app.delegate = delegate
        app.run()
    }
    func applicationDidFinishLaunching(_ notification: Notification) {
        do {
            root = FileManager.default.temporaryDirectory.appendingPathComponent("solasi-webview-" + UUID().uuidString)
            try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
            try Data("<html><body><div id='result'>waiting</div><script type='module' src='/fixture.js'></script></body></html>".utf8).write(to: root.appendingPathComponent("index.html"))
            try Data("document.getElementById('result').textContent = 'module-ready';".utf8).write(to: root.appendingPathComponent("fixture.js"))
            let configuration = WKWebViewConfiguration()
            configuration.userContentController.addUserScript(WKUserScript(source:"window.fixtureErrors=[];window.addEventListener('error',e=>window.fixtureErrors.push(e.message||e.target.src),true);", injectionTime:.atDocumentStart, forMainFrameOnly:true))
            configuration.setURLSchemeHandler(AppResources(root: root, worker: WorkerBridge()), forURLScheme: "solasi-app")
            configuration.websiteDataStore = .nonPersistent()
            webView = WKWebView(frame: NSRect(x:0,y:0,width:680,height:480), configuration: configuration)
            webView.navigationDelegate = self
            webView.load(URLRequest(url: URL(string:"solasi-app://app/")!))
            DispatchQueue.main.asyncAfter(deadline:.now()+20) { self.finish("WebKit fixture timeout: "+self.lastResult, success:false) }
        } catch { finish(error.localizedDescription, success:false) }
    }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        check()
    }
    func check() {
        DispatchQueue.main.asyncAfter(deadline:.now()+0.2) {
        self.webView.evaluateJavaScript("JSON.stringify({url:location.href,module:document.getElementById('result').textContent,errors:window.fixtureErrors,random:typeof crypto.getRandomValues,uuid:typeof crypto.randomUUID,subtle:typeof crypto.subtle,secure:isSecureContext})") { result, error in
            guard let result = result as? String, error == nil else { self.finish(error?.localizedDescription ?? String(describing:result),success:false); return }
            self.lastResult=result
            if !result.contains("module-ready") { self.check(); return }
            self.finish(result,success:true)
        }
        }
    }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { finish(error.localizedDescription,success:false) }
    func finish(_ message: String, success: Bool) {
        print(message)
        if let root = root { try? FileManager.default.removeItem(at: root) }
        exit(success ? 0 : 1)
    }
}
