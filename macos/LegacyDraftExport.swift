import AppKit
import CryptoKit
import WebKit

// Separate migration executable. The caller must first preserve live editor inputs and quiesce all old windows.
@main
final class LegacyDraftExport: NSObject, NSApplicationDelegate, WKScriptMessageHandlerWithReply, WKNavigationDelegate, NSWindowDelegate {
    private var webView: WKWebView!
    private var window: NSWindow!
    private var status: NSTextField!
    private var activity: NSObjectProtocol?
    private var origin = ""
    private var vault = ""
    private var bundleID = ""
    private var destination: URL!
    private var staging: URL!
    private var output: FileHandle!
    private var rows: [[String: Any]] = []
    private var total: UInt64 = 0
    private var wholeHash = SHA256()
    private var rowHash = SHA256()
    private var rowBytes = 0
    private var rowKey: String?
    private var undefinedPaths: [[Any]] = []
    private var undefinedPathsHash = ""
    private var verifying = false
    private var verifiedCount = 0
    private var theme: Any = NSNull()
    private var databasePresent = false
    private var done = false
    private var lastMessage = Date()

    static func main() {
        let app = NSApplication.shared
        let delegate = LegacyDraftExport()
        app.delegate = delegate
        app.setActivationPolicy(.accessory)
        app.run()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        do {
            let args = CommandLine.arguments
            guard args.count == 8, args[1] == "--origin", args[3] == "--vault-id", args[5] == "--output", args[7] == "--quiescent",
                  let components = URLComponents(string: args[2]), components.scheme == "http",
                  components.host == "127.0.0.1", let port = components.port, (1...65535).contains(port),
                  components.path.isEmpty || components.path == "/", components.query == nil,
                  components.fragment == nil, components.user == nil, components.password == nil,
                  args[4].range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil,
                  let actualID = Bundle.main.bundleIdentifier,
                  actualID == "local.solasi.launcher" || actualID.hasPrefix("local.solasi.migration-fixture-") else {
                throw failure("Usage: --origin <exact-http-loopback-origin> --vault-id <32hex-vault-id> --output <new-output-directory> --quiescent")
            }
            guard NSRunningApplication.runningApplications(withBundleIdentifier: actualID).allSatisfy({ $0.processIdentifier == getpid() }) else {
                throw failure("The original app is still running. Preserve live inputs and quit it before exporting its persistent store.")
            }
            origin = "http://127.0.0.1:\(port)"; vault = args[4]; bundleID = actualID
            destination = URL(fileURLWithPath: args[6]).standardizedFileURL
            guard !FileManager.default.fileExists(atPath: destination.path) else { throw failure("Export destination already exists") }
            staging = destination.deletingLastPathComponent().appendingPathComponent(destination.lastPathComponent + ".partial-" + UUID().uuidString)
            try FileManager.default.createDirectory(at: staging, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
            let path = staging.appendingPathComponent("drafts.jsonl").path
            let fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0o600)
            guard fd >= 0 else { throw failure("Cannot create draft export: \(errno)") }
            output = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
            let configuration = WKWebViewConfiguration()
            configuration.websiteDataStore = .default()
            configuration.userContentController.addScriptMessageHandler(self, contentWorld: .page, name: "exportDrafts")
            // A windowless WKWebView can be suspended after loading, even while the export promise is pending.
            window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 420, height: 140), styleMask: [.titled, .closable], backing: .buffered, defer: false)
            window.title = "Solasi 초안 이전"; window.delegate = self; window.isReleasedWhenClosed = false
            webView = WKWebView(frame: window.contentView!.bounds, configuration: configuration)
            webView.autoresizingMask = [.width, .height]; window.contentView = webView
            status = NSTextField(wrappingLabelWithString: "기존 초안을 읽고 있습니다.\n창을 닫으면 이전을 취소합니다.")
            status.frame = NSRect(x: 24, y: 32, width: 372, height: 76); webView.addSubview(status)
            activity = ProcessInfo.processInfo.beginActivity(options: [.userInitiated, .idleSystemSleepDisabled], reason: "Preserving local Solasi drafts")
            window.center(); window.orderFrontRegardless()
            webView.navigationDelegate = self
            webView.loadHTMLString("<meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; script-src 'unsafe-inline'\"><script>\(Self.script)</script>", baseURL: URL(string: origin + "/")!)
            Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] timer in
                guard let self, !self.done else { timer.invalidate(); return }
                if Date().timeIntervalSince(self.lastMessage) > 120 { self.stop(self.failure("No migration progress for 120 seconds; source and partial export preserved")) }
            }
        } catch { stop(error) }
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        decisionHandler(navigationAction.request.url?.absoluteString == origin + "/" ? .allow : .cancel)
    }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { stop(error) }
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { stop(failure("Migration WebKit process terminated; partial export retained")) }
    func windowWillClose(_ notification: Notification) { if !done { stop(failure("Migration cancelled; source and partial export preserved")) } }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage, replyHandler: @escaping (Any?, String?) -> Void) {
        do {
            let security = message.frameInfo.securityOrigin
            guard !done, message.frameInfo.isMainFrame,
                  "\(security.protocol)://\(security.host):\(security.port)" == origin,
                  let value = message.body as? [String: Any], let type = value["type"] as? String else { throw failure("Untrusted migration message") }
            lastMessage = Date()
            switch type {
            case "start":
                guard total == 0, rows.isEmpty, let present = value["database_present"] as? Bool,
                      value["theme"] is String || value["theme"] is NSNull else { throw failure("Invalid start metadata") }
                theme = value["theme"]!; databasePresent = present
            case "row":
                guard rowKey == nil, let key = value["key"] as? String, !key.isEmpty, key.utf8.count <= 16384,
                      let paths = value["undefined_paths"] as? [[Any]] else { throw failure("Invalid draft key or undefined paths") }
                undefinedPaths = try paths.map { path in
                    guard !path.isEmpty else { throw failure("Undefined row root") }
                    return try path.map { component -> Any in
                        if let name = component as? String { return name }
                        if let index = component as? NSNumber, CFGetTypeID(index) != CFBooleanGetTypeID(),
                           index.doubleValue >= 0, index.doubleValue <= 4294967294, index.doubleValue.rounded() == index.doubleValue { return index.int64Value }
                        throw failure("Invalid undefined path component")
                    }
                }
                let pathsData = try JSONSerialization.data(withJSONObject: undefinedPaths, options: [.sortedKeys, .withoutEscapingSlashes])
                guard pathsData.count <= 64 * 1024 * 1024 else { throw failure("Undefined paths exceed 64MiB; source preserved") }
                undefinedPathsHash = Self.hex(SHA256.hash(data: pathsData))
                if verifying {
                    guard verifiedCount < rows.count, rows[verifiedCount]["key"] as? String == key,
                          rows[verifiedCount]["undefined_paths_sha256"] as? String == undefinedPathsHash else { throw failure("Draft keys or undefined fields changed during export") }
                }
                rowKey = key; rowBytes = 0; rowHash = SHA256()
            case "chunk":
                guard rowKey != nil, let encoded = value["base64"] as? String, encoded.utf8.count <= 174764,
                      let bytes = Data(base64Encoded: encoded), !bytes.isEmpty, bytes.count <= 131072,
                      rowBytes + bytes.count <= 64 * 1024 * 1024 else { throw failure("Invalid or oversized draft chunk") }
                rowHash.update(data: bytes); rowBytes += bytes.count
                if !verifying { try output.write(contentsOf: bytes); wholeHash.update(data: bytes) }
            case "end_row":
                guard let key = rowKey, rowBytes > 0 else { throw failure("Missing draft row") }
                let hash = Self.hex(rowHash.finalize())
                if verifying {
                    let old = rows[verifiedCount]
                    guard old["bytes"] as? Int == rowBytes, old["sha256"] as? String == hash else { throw failure("Draft contents changed during export") }
                    verifiedCount += 1
                } else {
                    rows.append(["key":key,"offset":total,"bytes":rowBytes,"sha256":hash,"undefined_paths":undefinedPaths,"undefined_paths_sha256":undefinedPathsHash])
                    let newline = Data([10]); try output.write(contentsOf: newline); wholeHash.update(data: newline)
                    total += UInt64(rowBytes + 1)
                }
                rowKey = nil
                status.stringValue = verifying ? "초안 대조 중 · \(verifiedCount) / \(rows.count)개\n원본 초안은 그대로 보존합니다." : "초안 내보내는 중 · \(rows.count)개\n원본 초안은 그대로 보존합니다."
            case "verify":
                guard !verifying, rowKey == nil else { throw failure("Invalid verification phase") }; verifying = true
            case "finish":
                guard verifying, rowKey == nil, verifiedCount == rows.count,
                      value["database_present"] as? Bool == databasePresent,
                      Self.jsonEqual(value["theme"] ?? NSNull(), theme) else { throw failure("Draft store or theme changed during export") }
                try finish()
            case "error": throw failure(value["message"] as? String ?? "Draft export failed")
            default: throw failure("Unknown migration message")
            }
            replyHandler(["ok":true], nil)
        } catch { replyHandler(nil, error.localizedDescription); stop(error) }
    }

    private func finish() throws {
        try output.synchronize(); try output.close(); output = nil
        let manifest: [String: Any] = ["version":1,"format":"solasi-legacy-drafts-jsonl","vault_id":vault,"origin":origin,"source_bundle_id":bundleID,"theme":theme,"database_present":databasePresent,"rows":rows,"row_count":rows.count,"rows_sha256":Self.hex(wholeHash.finalize()),"total_bytes":total,"verified":true,"unsaved_inputs":[],"unsaved_inputs_captured":false]
        let manifestData = try JSONSerialization.data(withJSONObject: manifest, options: [.prettyPrinted, .sortedKeys])
        let manifestURL = staging.appendingPathComponent("manifest.json")
        try manifestData.write(to: manifestURL, options: .withoutOverwriting)
        try FileManager.default.setAttributes([.posixPermissions:0o600], ofItemAtPath:manifestURL.path)
        let handle = try FileHandle(forWritingTo: manifestURL); try handle.synchronize(); try handle.close()
        guard renamex_np(staging.path, destination.path, UInt32(RENAME_EXCL)) == 0 else { throw failure("Cannot publish export; partial retained: \(errno)") }
        done = true
        if let activity { ProcessInfo.processInfo.endActivity(activity); self.activity = nil }
        print("Legacy draft export verified: \(rows.count) rows, \(total) bytes; \(destination.path)")
        DispatchQueue.main.async { exit(0) }
    }

    private func stop(_ error: Error) {
        guard !done else { return }; done = true
        if let activity { ProcessInfo.processInfo.endActivity(activity); self.activity = nil }
        try? output?.synchronize(); try? output?.close()
        fputs("\(error.localizedDescription)\nPartial export: \(staging?.path ?? "not created")\n", stderr)
        DispatchQueue.main.async { exit(1) }
    }
    private func failure(_ message: String) -> Error { NSError(domain:"Solasi.LegacyDraftExport",code:1,userInfo:[NSLocalizedDescriptionKey:message]) }
    private static func hex(_ bytes: SHA256.Digest) -> String { bytes.map { String(format:"%02x",$0) }.joined() }
    private static func jsonEqual(_ lhs: Any, _ rhs: Any) -> Bool { (lhs as? String) == (rhs as? String) && (lhs is NSNull) == (rhs is NSNull) }

    private static let script = #"""
    (async () => {
      const send = value => window.webkit.messageHandlers.exportDrafts.postMessage(value);
      let db;
      try {
        const databases = await indexedDB.databases();
        const present = databases.some(item => item.name === 'solasi-page-drafts');
        const theme = localStorage.getItem('solasi.theme');
        await send({type:'start',database_present:present,theme});
        if (present) {
          db = await new Promise((resolve,reject) => {
            const r=indexedDB.open('solasi-page-drafts');
            r.onupgradeneeded=()=>{r.transaction.abort();reject(new Error('Draft database disappeared; source was not created'));};
            r.onblocked=()=>reject(new Error('Draft database is blocked by another process; source preserved'));
            r.onerror=()=>reject(r.error); r.onsuccess=()=>resolve(r.result);
          });
          if (!db.objectStoreNames.contains('drafts')) throw new Error('Draft store is missing');
          if (db.transaction('drafts','readonly').objectStore('drafts').keyPath !== 'key') throw new Error('Unexpected draft schema');
        }
        // BEGIN RAW_DRAFT_CODEC
        const rawDraftUndefinedPaths = value => {
          const paths=[];
          const visit = (value,path,seen) => {
          if (value===undefined) { paths.push(path); return; }
          if (value===null || typeof value==='string' || typeof value==='boolean') return;
          if (typeof value==='number' && Number.isFinite(value)) return;
          if (typeof value!=='object' || seen.has(value) || (!Array.isArray(value) && Object.getPrototypeOf(value)!==Object.prototype)) throw new Error('Unsupported raw draft value; source preserved');
          if (Array.isArray(value) && (Object.keys(value).length!==value.length || Object.keys(value).some((key,index)=>key!==String(index)))) throw new Error('Sparse or extended draft array; source preserved');
          seen.add(value);
          for (const key of Object.keys(value)) visit(value[key], [...path, Array.isArray(value)?Number(key):key], seen);
          seen.delete(value);
          };
          visit(value,[],new Set()); return paths;
        };
        // END RAW_DRAFT_CODEC
        const next = last => new Promise((resolve,reject) => {
          const t=db.transaction('drafts','readonly'),r=t.objectStore('drafts').openCursor(last===undefined ? undefined : IDBKeyRange.lowerBound(last,true));
          let result=null; r.onsuccess=()=>{if(r.result)result={key:r.result.primaryKey,value:r.result.value};};
          t.oncomplete=()=>resolve(result); t.onerror=()=>reject(t.error); t.onabort=()=>reject(t.error);
        });
        const pass = async () => {
          if (!db) return;
          let last;
          while (true) {
            const item=await next(last); if(!item)break;
            if(typeof item.key!=='string' || item.value?.key!==item.key)throw new Error('Raw key mismatch');
            const undefinedPaths=rawDraftUndefinedPaths(item.value);
            const bytes=new TextEncoder().encode(JSON.stringify(item.value));
            if(bytes.length>64*1024*1024)throw new Error('A raw draft exceeds 64MiB; source preserved');
            await send({type:'row',key:item.key,undefined_paths:undefinedPaths});
            for(let i=0;i<bytes.length;i+=131072){
              const chunk=bytes.subarray(i,i+131072); let binary='';
              for(let j=0;j<chunk.length;j+=8192)binary+=String.fromCharCode(...chunk.subarray(j,j+8192));
              await send({type:'chunk',base64:btoa(binary)});
            }
            await send({type:'end_row'}); last=item.key;
          }
        };
        await pass(); await send({type:'verify'}); await pass();
        if(db)db.close(); db=undefined;
        const after=await indexedDB.databases();
        await send({type:'finish',database_present:after.some(item=>item.name==='solasi-page-drafts'),theme:localStorage.getItem('solasi.theme')});
      } catch (error) { if(db)db.close(); await send({type:'error',message:String(error)}); }
    })();
    """#
}
