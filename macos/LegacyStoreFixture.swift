import AppKit
import WebKit

// Run only in a uniquely identified fixture bundle, never the product bundle.
@main
final class LegacyStoreFixture: NSObject, NSApplicationDelegate, WKScriptMessageHandler {
    private var webView: WKWebView!
    private var destination: URL!
    private var completed = false

    static func main() {
        let app = NSApplication.shared
        let delegate = LegacyStoreFixture()
        app.delegate = delegate
        app.setActivationPolicy(.prohibited)
        app.run()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        guard Bundle.main.bundleIdentifier?.hasPrefix("local.solasi.migration-fixture-") == true,
              CommandLine.arguments.count == 3, ["seed", "seed-large", "seed-undefined", "seed-invalid", "read"].contains(CommandLine.arguments[1]) else {
            finish(["error": "Use an isolated fixture bundle and seed/read output.json arguments"], success: false)
            return
        }
        destination = URL(fileURLWithPath: CommandLine.arguments[2])
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        configuration.userContentController.add(self, name: "fixture")
        webView = WKWebView(frame: NSRect(x: 0, y: 0, width: 680, height: 480), configuration: configuration)
        let seed = CommandLine.arguments[1].hasPrefix("seed")
        let large = CommandLine.arguments[1] == "seed-large"
        let invalid = CommandLine.arguments[1] == "seed-invalid"
        let undefined = CommandLine.arguments[1] == "seed-undefined"
        let script = """
        (async () => {
          const report = {phase:'\(seed ? "seed" : "read")',href:location.href,base:document.baseURI,origin:location.origin,secure:isSecureContext};
          try {
            const databases = await indexedDB.databases(); report.before=databases;
            const db=await new Promise((resolve,reject)=>{const r=indexedDB.open('solasi-page-drafts',1);r.onupgradeneeded=()=>r.result.createObjectStore('drafts',{keyPath:'key'});r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});
            if (\(seed ? "true" : "false")) {
              await new Promise((resolve,reject)=>{const t=db.transaction('drafts','readwrite'),s=t.objectStore('drafts');s.put({key:'fixture-main',text:'한국어 원문',ink:[],dirty:false,backup:{text:'이전 초안',ink:[]},custom:{preserve:true}});s.put({key:'fixture-main::writer',text:'미저장 필기',ink:[],dirty:true});t.oncomplete=resolve;t.onerror=()=>reject(t.error);});
              if (\(large ? "true" : "false")) await new Promise((resolve,reject)=>{const t=db.transaction('drafts','readwrite'),s=t.objectStore('drafts');for(let n=0;n<3;n++)s.put({key:'large-'+n,text:String(n).repeat(23*1024*1024),ink:[],dirty:true});t.oncomplete=resolve;t.onerror=()=>reject(t.error);});
              if (\(undefined ? "true" : "false")) await new Promise((resolve,reject)=>{const t=db.transaction('drafts','readwrite');t.objectStore('drafts').put({key:'fixture-undefined',text:'raw',ink:[],backup:undefined,nested:{optional:undefined},values:[undefined,null,{optional:undefined}]});t.oncomplete=resolve;t.onerror=()=>reject(t.error);});
              if (\(invalid ? "true" : "false")) await new Promise((resolve,reject)=>{const t=db.transaction('drafts','readwrite');t.objectStore('drafts').put({key:'fixture-invalid',text:'raw',ink:[],unsupported:new Date('2026-10-16T00:00:00Z')});t.oncomplete=resolve;t.onerror=()=>reject(t.error);});
              localStorage.setItem('solasi.theme','dark');
            }
            report.rows=await new Promise((resolve,reject)=>{const r=db.transaction('drafts','readonly').objectStore('drafts').getAll();r.onsuccess=()=>resolve(r.result.map(row=>row.key==='fixture-undefined'?{key:row.key,backupPresent:Object.prototype.hasOwnProperty.call(row,'backup'),backupUndefined:row.backup===undefined,nestedPresent:Object.prototype.hasOwnProperty.call(row.nested,'optional'),nestedUndefined:row.nested.optional===undefined,arrayFirstPresent:Object.prototype.hasOwnProperty.call(row.values,0),arrayFirstUndefined:row.values[0]===undefined,arraySecondNull:row.values[1]===null,arrayNestedUndefined:row.values[2].optional===undefined}:row.key==='fixture-invalid'?{key:row.key,unsupportedPresent:Object.prototype.hasOwnProperty.call(row,'unsupported'),unsupportedType:Object.prototype.toString.call(row.unsupported)}:row.text.length>1000?{key:row.key,textLength:row.text.length}:row));r.onerror=()=>reject(r.error);});
            report.theme=localStorage.getItem('solasi.theme'); db.close();
          } catch (e) { report.error=String(e); }
          window.webkit.messageHandlers.fixture.postMessage(report);
        })();
        """
        webView.loadHTMLString("<meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; script-src 'unsafe-inline'\"><script>\(script)</script>", baseURL: URL(string: "http://127.0.0.1:62434/")!)
        DispatchQueue.main.asyncAfter(deadline: .now() + 20) { self.finish(["error":"Fixture timed out"], success: false) }
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame, var report = message.body as? [String: Any] else { return }
        let origin = message.frameInfo.securityOrigin
        report["frameOrigin"] = "\(origin.protocol)://\(origin.host):\(origin.port)"
        WKWebsiteDataStore.default().fetchDataRecords(ofTypes: WKWebsiteDataStore.allWebsiteDataTypes()) { records in
            report["dataRecords"] = records.map { ["name": $0.displayName, "types": $0.dataTypes.sorted()] }
            let rows = report["rows"] as? [[String: Any]]
            self.finish(report, success: report["error"] == nil && (rows?.count ?? 0) >= 2 && report["theme"] as? String == "dark")
        }
    }

    private func finish(_ report: [String: Any], success: Bool) {
        guard !completed else { return }; completed = true
        do {
            let data = try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
            if let destination { try data.write(to: destination, options: .atomic) }
            print(String(decoding: data, as: UTF8.self))
        } catch { fputs("\(error)\n", stderr); exit(1) }
        exit(success ? 0 : 1)
    }
}
