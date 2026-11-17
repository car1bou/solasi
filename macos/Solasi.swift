import AppKit
import AVFoundation
import Darwin
import Foundation
import WebKit
import UniformTypeIdentifiers

struct LaunchSettings: Decodable {
    let data: String
    let runtime: String
}

private final class WindowResizeHandle: NSView {
    private var start: (frame: NSRect, mouse: NSPoint)?
    override var acceptsFirstResponder: Bool { true }

    static func resizedFrame(_ frame: NSRect, delta: NSPoint, minimum: NSSize) -> NSRect {
        let size = NSSize(width: max(minimum.width, frame.width + delta.x), height: max(minimum.height, frame.height - delta.y))
        return NSRect(x: frame.minX, y: frame.maxY - size.height, width: size.width, height: size.height)
    }

    override func draw(_ dirtyRect: NSRect) {
        NSColor.secondaryLabelColor.setStroke()
        let lines = NSBezierPath()
        lines.lineWidth = 1.5
        for offset in [CGFloat(7), 12, 17] {
            lines.move(to: NSPoint(x: bounds.maxX - offset - 5, y: 5))
            lines.line(to: NSPoint(x: bounds.maxX - 5, y: offset + 5))
        }
        lines.stroke()
    }

    override func mouseDown(with event: NSEvent) {
        guard let window else { return }
        window.makeFirstResponder(self)
        start = (window.frame, NSEvent.mouseLocation)
    }
    override func mouseDragged(with event: NSEvent) {
        guard let window, let start else { return }
        let point = NSEvent.mouseLocation
        window.setFrame(Self.resizedFrame(start.frame, delta: NSPoint(x: point.x - start.mouse.x, y: point.y - start.mouse.y), minimum: window.minSize), display: true)
    }
    override func mouseUp(with event: NSEvent) { start = nil }
    override func keyDown(with event: NSEvent) {
        guard let window else { return }
        let steps: [UInt16: NSPoint] = [123: NSPoint(x: -20,y: 0),124: NSPoint(x: 20,y: 0),125: NSPoint(x: 0,y: -20),126: NSPoint(x: 0,y: 20)]
        guard let delta = steps[event.keyCode] else { super.keyDown(with: event);return }
        window.setFrame(Self.resizedFrame(window.frame, delta: delta, minimum: window.minSize), display: true)
    }
}

private final class AppWindow {
    let window: NSWindow
    let webView: WKWebView
    let status = NSTextField(wrappingLabelWithString: "기록을 준비하고 있습니다…")
    let retry = NSButton(title: "화면 다시 열기", target: nil, action: nil)
    var userClickAt = Date.distantPast
    var uiReady = false
    let resizeHandle = WindowResizeHandle()

    init(configuration: WKWebViewConfiguration) {
        webView = WKWebView(frame: .zero, configuration: configuration)
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1200, height: 820), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Solasi"
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.titlebarSeparatorStyle = .none
        window.minSize = NSSize(width: 680, height: 480)
        window.isReleasedWhenClosed = false
        let notice = NSStackView(views: [status, retry])
        notice.orientation = .horizontal
        notice.spacing = 12
        notice.edgeInsets = NSEdgeInsets(top: 32, left: 12, bottom: 8, right: 12)
        status.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        retry.isHidden = true
        let sizing = NSView()
        resizeHandle.toolTip = "창 크기 조절 · 드래그 또는 클릭 후 방향키"
        resizeHandle.setAccessibilityElement(true)
        resizeHandle.setAccessibilityRole(.splitter)
        resizeHandle.setAccessibilityLabel("창 크기 조절")
        sizing.addSubview(resizeHandle)
        resizeHandle.translatesAutoresizingMaskIntoConstraints = false
        let content = NSStackView(views: [notice, webView, sizing])
        content.orientation = .vertical
        content.alignment = .leading
        content.spacing = 0
        content.distribution = .fill
        window.contentView = content
        webView.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            notice.widthAnchor.constraint(equalTo: content.widthAnchor),
            status.topAnchor.constraint(equalTo: notice.topAnchor, constant: 32),
            status.bottomAnchor.constraint(lessThanOrEqualTo: notice.bottomAnchor, constant: -8),
            webView.widthAnchor.constraint(equalTo: content.widthAnchor),
            webView.heightAnchor.constraint(greaterThanOrEqualToConstant: 200),
            sizing.widthAnchor.constraint(equalTo: content.widthAnchor),
            sizing.heightAnchor.constraint(equalToConstant: 28),
            resizeHandle.widthAnchor.constraint(equalToConstant: 32),
            resizeHandle.heightAnchor.constraint(equalTo: sizing.heightAnchor),
            resizeHandle.trailingAnchor.constraint(equalTo: sizing.trailingAnchor),
            resizeHandle.bottomAnchor.constraint(equalTo: sizing.bottomAnchor)
        ])
        window.center()
    }

    func showStatus(_ message: String, canRetry: Bool = false) {
        status.stringValue = message
        status.superview?.isHidden = message.isEmpty
        retry.isHidden = !canRetry
    }
}

final class SolasiApp: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler, WKScriptMessageHandlerWithReply, WKDownloadDelegate {
    private let worker = WorkerBridge()
    private var resources: AppResources?
    private var vaultID = ""
    private var workerReady = false
    private var pendingAudio: URL?
    private var requests: [ObjectIdentifier: [String: String]] = [:]
    private var captures: [String: (owner:ObjectIdentifier,capture:AudioCapture)] = [:]
    private var players: [String: (owner:ObjectIdentifier,player:AudioPlayback)] = [:]
    private var mainWindow: AppWindow?
    private var extraWindows: [AppWindow] = []
    private var downloadWindows: [ObjectIdentifier: AppWindow] = [:]
    private var cancelledDownloads: Set<ObjectIdentifier> = []
    private var downloadTargets: [ObjectIdentifier: (destination: URL, staging: URL)] = [:]
    private let clickWorld = WKContentWorld.world(name: "SolasiUserInput")
    private var uninstalling = false
    private var uninstallFrozen = false
    private var uninstallAuthorized = false
    private var quitting = false
    private var preparingQuit = false
    private var preparingWindows = Set<ObjectIdentifier>()
    private var approvedWindows = Set<ObjectIdentifier>()
    private var deliveringAudio = false
    private var log: FileHandle?
    private let logURL = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Logs/" + (Bundle.main.bundleIdentifier ?? "local.solasi.development") + "/engine.log")

    func applicationDidFinishLaunching(_ notification: Notification) {
        installMenu()
        // Dock can retain the generic icon after replacing an existing local app bundle.
        if let iconURL = Bundle.main.url(forResource: "Solasi", withExtension: "icns"), let icon = NSImage(contentsOf: iconURL) {
            NSApp.applicationIconImage = icon
        }
        do {
            guard let settingsURL = Bundle.main.url(forResource: "launch", withExtension: "json") else {
                throw NSError(domain: "Solasi", code: 1, userInfo: [NSLocalizedDescriptionKey: "실행 설정이 없습니다. 실행 앱을 다시 설치하세요."])
            }
            let settings = try JSONDecoder().decode(LaunchSettings.self, from: Data(contentsOf: settingsURL))
            guard let bundle = Bundle.main.resourceURL else { throw BridgeFailure.invalid("앱 번들을 찾을 수 없습니다.") }
            let engine = bundle.appendingPathComponent("engine/solasi-engine")
            let frontend = bundle.appendingPathComponent("frontend")
            for path in [engine.path, frontend.appendingPathComponent("index.html").path, settings.data, settings.runtime] {
                guard FileManager.default.fileExists(atPath: path) else {
                    throw NSError(domain: "Solasi", code: 2, userInfo: [NSLocalizedDescriptionKey: "필요한 파일이나 폴더가 없습니다: \(path)"])
                }
            }
            resources = AppResources(root: frontend, worker: worker)
            let configuration = WKWebViewConfiguration()
            configuration.websiteDataStore = .default()
            configuration.setURLSchemeHandler(resources!, forURLScheme: "solasi-app")
            configuration.userContentController.addScriptMessageHandler(self, contentWorld: .page, name: "solasi")
            configuration.userContentController.add(self, contentWorld: clickWorld, name: "userClick")
            configuration.userContentController.addUserScript(WKUserScript(source: """
                document.addEventListener('click', event => {
                    if (event.isTrusted) window.webkit.messageHandlers.userClick.postMessage(null);
                }, true);
                """, injectionTime: .atDocumentStart, forMainFrameOnly: true, in: clickWorld))
            mainWindow = makeWindow(configuration: configuration)
            mainWindow?.window.setFrameAutosaveName("SolasiMainWindow")
            showWindow()
            try FileManager.default.createDirectory(at: logURL.deletingLastPathComponent(), withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            if !FileManager.default.fileExists(atPath:logURL.path) { FileManager.default.createFile(atPath: logURL.path, contents: nil, attributes: [.posixPermissions: 0o600]) }
            log = try FileHandle(forWritingTo: logURL)
            try log?.seekToEnd()
            var environment = ProcessInfo.processInfo.environment
            environment.removeValue(forKey: "PYTHONPATH")
            environment.removeValue(forKey: "PYTHONHOME")
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            environment["PYTHONUNBUFFERED"] = "1"
            environment["SOLASI_OWNER_PID"] = String(ProcessInfo.processInfo.processIdentifier)
            worker.ready = { [weak self] in
                guard let self = self else { return }
                self.prepareVault()
            }
            worker.terminated = { [weak self] _ in
                guard let self = self else { return }
                for active in Array(self.captures.values) { active.capture.stop(interrupted:true,reason:"작업 엔진이 종료되었습니다") {} }
                if self.quitting { NSApp.reply(toApplicationShouldTerminate: true) }
                else { self.fail("작업 엔진이 종료되었습니다. 저장된 기록을 보존했습니다. 로그를 확인한 뒤 앱을 다시 실행하세요.") }
            }
            try worker.start(executable: engine, arguments: ["--data-dir", settings.data, "--runtime-dir", settings.runtime], environment: environment, log: log)
            DispatchQueue.main.asyncAfter(deadline: .now() + 120) { [weak self] in
                guard let self = self, !self.quitting, !self.workerReady else { return }
                self.fail("기록 준비 시간이 초과되었습니다. 로그에서 원인을 확인하세요.")
            }
        } catch { fail(error.localizedDescription) }
    }

    private func installMenu() {
        let menu = NSMenu()
        let appItem = NSMenuItem()
        menu.addItem(appItem)
        let actions = NSMenu(title: "Solasi")
        actions.addItem(withTitle: "Solasi 열기", action: #selector(showWindow), keyEquivalent: "o")
        actions.addItem(withTitle: "로그 보기", action: #selector(showLog), keyEquivalent: "")
        actions.addItem(.separator())
        actions.addItem(withTitle: "Solasi 가리기", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        actions.addItem(.separator())
        actions.addItem(withTitle: "Solasi 종료", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = actions
        let editItem = NSMenuItem()
        menu.addItem(editItem)
        let edit = NSMenu(title: "편집")
        edit.addItem(withTitle: "실행 취소", action: Selector(("undo:")), keyEquivalent: "z")
        let redo = edit.addItem(withTitle: "다시 실행", action: Selector(("redo:")), keyEquivalent: "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        edit.addItem(.separator())
        edit.addItem(withTitle: "잘라내기", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "복사", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "붙여넣기", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "모두 선택", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit
        let windowItem = NSMenuItem()
        menu.addItem(windowItem)
        let windows = NSMenu(title: "윈도우")
        windows.addItem(withTitle: "최소화", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        let compact = windows.addItem(withTitle: "작은 창 (680×480)", action: #selector(compactWindow), keyEquivalent: "1")
        compact.keyEquivalentModifierMask = [.command, .option]
        let standard = windows.addItem(withTitle: "기본 크기 (1200×820)", action: #selector(standardWindow), keyEquivalent: "2")
        standard.keyEquivalentModifierMask = [.command, .option]
        windows.addItem(withTitle: "창 닫기", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        windowItem.submenu = windows
        NSApp.windowsMenu = windows
        NSApp.mainMenu = menu
    }

    private func makeWindow(configuration: WKWebViewConfiguration) -> AppWindow {
        let page = AppWindow(configuration: configuration)
        page.window.delegate = self
        page.webView.navigationDelegate = self
        page.webView.uiDelegate = self
        page.retry.target = self
        page.retry.action = #selector(retryPage(_:))
        return page
    }

    private func page(for webView: WKWebView) -> AppWindow? {
        ([mainWindow].compactMap { $0 } + extraWindows).first { $0.webView === webView }
    }

    private func trusted(_ url: URL?) -> Bool {
        AppResourcePolicy.trusted(url)
    }

    private func trustedBlob(_ url: URL?) -> Bool {
        guard let url = url, url.scheme == "blob" else { return false }
        return trusted(URL(string: String(url.absoluteString.dropFirst("blob:".count))))
    }

    private func trusted(_ origin: WKSecurityOrigin) -> Bool {
        origin.protocol == "solasi-app" && origin.host == "app" && origin.port == 0
    }

    @objc private func showWindow() {
        if mainWindow?.window.isMiniaturized == true { mainWindow?.window.deminiaturize(nil) }
        mainWindow?.window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    @objc private func showLog() { NSWorkspace.shared.open(logURL) }

    private func resizeWindow(_ size: NSSize) {
        guard let window = NSApp.keyWindow ?? mainWindow?.window else { return }
        let frame = window.frame
        window.setFrame(NSRect(x: frame.minX,y: frame.maxY - size.height,width: size.width,height: size.height), display: true, animate: true)
    }
    @objc private func compactWindow() { resizeWindow(NSSize(width: 680,height: 480)) }
    @objc private func standardWindow() { resizeWindow(NSSize(width: 1200,height: 820)) }

    @objc private func retryPage(_ sender: NSButton) {
        guard let page = ([mainWindow].compactMap { $0 } + extraWindows).first(where: { $0.retry === sender }), worker.process.isRunning else { return }
        let alert = NSAlert()
        alert.messageText = "화면을 다시 여시겠습니까?"
        alert.informativeText = "진행 중인 녹음과 화면 입력이 중단될 수 있습니다. 저장된 원음과 기록은 화면을 다시 연 뒤 확인하세요."
        alert.addButton(withTitle: "다시 열기")
        alert.addButton(withTitle: "취소")
        alert.beginSheetModal(for: page.window) { result in
            if result == .alertFirstButtonReturn { page.webView.reload() }
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showWindow()
        return false
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        if uninstalling { return false }
        if sender === mainWindow?.window { sender.orderOut(nil); return false }
        let key=ObjectIdentifier(sender)
        if approvedWindows.remove(key) != nil { return true }
        guard !preparingQuit,!quitting,!preparingWindows.contains(key),let page=extraWindows.first(where: { $0.window === sender }) else { return false }
        preparingWindows.insert(key)
        prepareClose([page]) { result in
            self.preparingWindows.remove(key)
            switch result {
            case .success: self.approvedWindows.insert(key);sender.performClose(nil)
            case .failure(let error): page.showStatus(error.localizedDescription)
            }
        }
        return false
    }

    func windowWillClose(_ notification: Notification) {
        guard let window = notification.object as? NSWindow else { return }
        if let page=extraWindows.first(where: { $0.window === window }) {
            for (id,active) in players where active.owner == ObjectIdentifier(page.webView) { active.player.close();players.removeValue(forKey:id) }
        }
        DispatchQueue.main.async { self.extraWindows.removeAll { $0.window === window } }
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if uninstallAuthorized { finishQuit(); return .terminateLater }
        if uninstalling { mainWindow?.showStatus("설치 삭제 준비·확인을 마치거나 취소한 뒤 종료하세요."); return .terminateCancel }
        if preparingQuit || quitting { return .terminateLater }
        guard preparingWindows.isEmpty else { mainWindow?.showStatus("창의 초안 저장을 마친 뒤 다시 종료해 주세요.");return .terminateCancel }
        preparingQuit=true
        let pages=[mainWindow].compactMap { $0 }+extraWindows
        prepareClose(pages) { result in
            self.preparingQuit=false
            switch result {
            case .failure(let error):
                self.mainWindow?.showStatus(error.localizedDescription);self.showWindow();NSApp.reply(toApplicationShouldTerminate:false)
            case .success: self.finishQuit()
            }
        }
        return .terminateLater
    }

    private func prepareClose(_ pages:[AppWindow],completion:@escaping (Result<Void,Error>)->Void) {
        let pages=pages.filter { AppResourcePolicy.trustedUI($0.webView.url) }
        guard !pages.isEmpty else { DispatchQueue.main.async { completion(.success(())) };return }
        var finished=false,remaining=pages.count
        var deadline:DispatchWorkItem?
        func settle(_ result:Result<Void,Error>) {
            guard !finished else { return };finished=true;deadline?.cancel()
            if case .failure=result {
                for page in pages { page.webView.callAsyncJavaScript("window.solasiLifecycle?.resume()",arguments:[:],in:nil,in:.page,completionHandler:nil) }
            }
            completion(result)
        }
        let timeout=DispatchWorkItem { settle(.failure(BridgeFailure.invalid("초안 저장이 끝나지 않아 창을 유지했습니다. 저장 상태를 확인하고 다시 시도해 주세요."))) }
        deadline=timeout;DispatchQueue.main.asyncAfter(deadline:.now()+30,execute:timeout)
        for page in pages {
            page.webView.callAsyncJavaScript("if (!window.solasiLifecycle) throw new Error('화면 준비가 끝난 뒤 다시 닫아 주세요.'); return await window.solasiLifecycle.prepareClose();",arguments:[:],in:nil,in:.page) { result in
                guard !finished else { return }
                switch result {
                case .success(let value):
                    guard value as? Bool == true else { settle(.failure(BridgeFailure.invalid("초안 저장 결과를 확인하지 못해 창을 유지했습니다.")));return }
                    remaining-=1;if remaining==0 { settle(.success(())) }
                case .failure(let error):
                    let failure=error as NSError
                    settle(.failure(BridgeFailure.invalid(failure.userInfo["WKJavaScriptExceptionMessage"] as? String ?? failure.localizedDescription)))
                }
            }
        }
    }

    private func finishQuit() {
        quitting=true
        for active in players.values { active.player.close() };players.removeAll()
        if worker.process.isRunning {
            let active=Array(captures.values)
            if active.isEmpty { worker.shutdown() }
            else {
                var remaining=active.count
                for item in active { item.capture.stop(interrupted:true,reason:"앱 종료로 녹음을 마쳤습니다") { remaining -= 1; if remaining == 0 { self.worker.shutdown() } } }
            }
            return
        }
        NSApp.reply(toApplicationShouldTerminate:true)
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.name == "userClick", message.world == clickWorld, message.frameInfo.isMainFrame,
              trusted(message.frameInfo.securityOrigin), let webView = message.webView,
              AppResourcePolicy.trustedUI(webView.url) else { return }
        page(for: webView)?.userClickAt = Date()
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage, replyHandler: @escaping (Any?, String?) -> Void) {
        guard message.name == "solasi", message.frameInfo.isMainFrame, trusted(message.frameInfo.securityOrigin),
              let webView = message.webView, AppResourcePolicy.trustedUI(webView.url), let page = page(for: webView),
              let body = message.body as? [String: Any], let op = body["op"] as? String else {
            replyHandler(nil, "허용하지 않은 앱 요청입니다."); return
        }
        if op == "uninstall_info" {
            let helper = Bundle.main.resourceURL?.appendingPathComponent("UninstallHelper")
            replyHandler(["available": helper.map { FileManager.default.isExecutableFile(atPath:$0.path) } ?? false],nil); return
        }
        if op == "uninstall_begin" || op == "reset_begin" {
            guard webView === mainWindow?.webView, consumeClick(page), !uninstalling, !quitting, !preparingQuit,
                  preparingWindows.isEmpty, captures.isEmpty, workerReady,
                  let selection = body["selection"] as? [String:Any], Set(selection.keys) == Set(["documents","audio","results"]),
                  selection.values.allSatisfy({ value in guard let number = value as? NSNumber else { return false }; return CFGetTypeID(number) == CFBooleanGetTypeID() }) else {
                replyHandler(nil,"녹음·창 저장을 마친 뒤 초기화·설치 삭제 버튼을 다시 눌러 주세요."); return
            }
            chooseUninstall(page:page,selection:selection,reset:op == "reset_begin",reply:replyHandler); return
        }
        let readOnlyStatus = op == "http" && body["method"] as? String == "GET" && body["path"] as? String == "/api/knowledge/status"
        if uninstallFrozen && !readOnlyStatus { replyHandler(nil,"초기화·설치 삭제 준비 중입니다. 마지막 확인에서 취소한 뒤 다시 사용하세요."); return }
        let owner = ObjectIdentifier(webView)
        if op == "ui_ready" {
            page.uiReady=true;replyHandler(["ready":true],nil)
            DispatchQueue.main.async { self.deliverAudio() };return
        }
        if op.hasPrefix("playback_") {
            guard let id=body["id"] as? String,UUID(uuidString:id) != nil else { replyHandler(nil,"재생 식별자가 없습니다."); return }
            do {
                if op == "playback_load" {
                    guard players[id] == nil,players.count < 16,let path=body["path"] as? String else { throw BridgeFailure.invalid("재생 중인 원음을 먼저 닫아 주세요.") }
                    let playback=try AudioPlayback(path:path,worker:worker) { [weak webView] state in
                        webView?.callAsyncJavaScript("window.dispatchEvent(new CustomEvent('solasi-playback-state', {detail: state}))",arguments:["state":state.merging(["id":id]) { _,new in new }],in:nil,in:.page,completionHandler:nil)
                    }
                    players[id]=(owner,playback)
                } else {
                    guard let active=players[id],active.owner == owner else { replyHandler(["closed":true],nil); return }
                    switch op {
                    case "playback_play": active.player.player.play()
                    case "playback_pause": active.player.player.pause()
                    case "playback_seek":
                        guard let time=body["time"] as? Double else { throw BridgeFailure.invalid("재생 시각을 확인하세요.") }
                        try active.player.seek(time) { error in replyHandler(error == nil ? ["accepted":true] : nil,error?.localizedDescription) };return
                    case "playback_volume": guard let value=body["volume"] as? Double,value.isFinite,(0...1).contains(value) else { throw BridgeFailure.invalid("음량을 확인하세요.") };active.player.player.volume=Float(value)
                    case "playback_close": active.player.close();players.removeValue(forKey:id)
                    case "playback_release":
                        active.player.player.pause();let state=active.player.snapshot()
                        active.player.close();players.removeValue(forKey:id);replyHandler(state,nil);return
                    default: throw BridgeFailure.invalid("허용하지 않은 재생 요청입니다.")
                    }
                }
                replyHandler(["accepted":true],nil)
            } catch { replyHandler(nil,error.localizedDescription) }
            return
        }
        if op == "audio_start" {
            guard webView === mainWindow?.webView, consumeClick(page), let id=body["capture_id"] as? String,
                  UUID(uuidString:id) != nil, captures[id] == nil, let session=body["session_id"] as? String,
                  session.range(of:"^[a-f0-9]{32}$",options:.regularExpression) != nil,
                  let mode=body["transcription_mode"] as? String,["after_stop","realtime"].contains(mode) else { replyHandler(nil,"녹음 시작 버튼을 다시 눌러 주세요."); return }
            let capture=AudioCapture(id:id,session:session,mode:mode,worker:worker) { [weak self,weak webView] state in
                guard let self=self,let webView=webView else { return }
                webView.callAsyncJavaScript("window.dispatchEvent(new CustomEvent('solasi-recording-state', {detail: state}))", arguments:["state":state],in:nil,in:.page,completionHandler:nil)
                if state["phase"] as? String == "idle" { self.captures.removeValue(forKey:id) }
            }
            captures[id]=(owner,capture); capture.start(); replyHandler(["accepted":true],nil); return
        }
        if op == "audio_stop" {
            guard let id=body["capture_id"] as? String else { replyHandler(nil,"녹음 식별자가 없습니다."); return }
            guard let active=captures[id] else { replyHandler(["stopped":true],nil); return }
            guard active.owner == owner else { replyHandler(nil,"이 창에서 시작한 녹음만 종료할 수 있습니다."); return }
            active.capture.stop(interrupted:body["interrupted"] as? Bool ?? false) { replyHandler(["stopped":true],nil) }; return
        }
        if op == "cancel", let target = body["target"] as? String {
            if let id = requests[owner]?.removeValue(forKey: target) { worker.cancel(id) }
            replyHandler(["cancelled":true], nil); return
        }
        if op == "export_text" {
            guard consumeClick(page), let text = body["text"] as? String, text.utf8.count <= 64 * 1024 * 1024,
                  let filename = body["filename"] as? String, filename.utf8.count < 256 else { replyHandler(nil, "내보내기 버튼을 다시 눌러 주세요."); return }
            saveDestination(page: page, filename: filename) { selection in
                do {
                    guard let export = try selection.get() else { replyHandler(["cancelled":true], nil); return }
                    try export.append(Data(text.utf8)); try export.finish(); replyHandler(["saved":true], nil)
                }
                catch { replyHandler(nil, error.localizedDescription) }
            }
            return
        }
        guard op == "http", let path = body["path"] as? String, AppResourcePolicy.validAPIPath(path),
              let method = body["method"] as? String, ["GET","HEAD","POST","PUT","PATCH","DELETE"].contains(method),
              let clientID = body["id"] as? String, UUID(uuidString: clientID) != nil,
              requests[owner]?[clientID] == nil, body["body"] == nil || body["body"] is String else {
            replyHandler(nil, "잘못된 앱 요청입니다."); return
        }
        let data = Data((body["body"] as? String ?? "").utf8)
        guard data.count <= WorkerFrame.requestLimit else { replyHandler(nil, "요청 크기를 초과했습니다."); return }
        var header: [String: Any] = ["op":"http", "method":method, "path":path]
        let picker = method == "POST" && path.range(of: "^/api/((sessions|courses)/[a-f0-9]{32}/files/select|sessions/[a-f0-9]{32}/recordings)$", options: .regularExpression) != nil
        if picker {
            guard consumeClick(page) else { replyHandler(nil, "파일 연결 버튼을 다시 눌러 주세요."); return }
            let panel = NSOpenPanel()
            panel.canChooseDirectories = false; panel.allowsMultipleSelection = true
            let audio = path.hasSuffix("/recordings")
            panel.title = audio ? "녹음 파일 연결" : "자료 연결"
            panel.allowedContentTypes = (audio ? ["wav","mp3","m4a","aac","flac","ogg","webm","mp4"] : ["pdf","png","jpg","jpeg","txt","md"]).compactMap { UTType(filenameExtension: $0) }
            panel.beginSheetModal(for: page.window) { result in
                let urls = result == .OK ? panel.urls : []
                guard urls.count <= 64 else { replyHandler(nil, "한 번에 파일 64개까지 연결할 수 있습니다."); return }
                header["native_selected_files"] = urls.map(\.path)
                self.jsonRequest(header, data: data, owner: owner, clientID: clientID, reply: replyHandler)
            }
        } else { jsonRequest(header, data: data, owner: owner, clientID: clientID, reply: replyHandler) }
    }

    private func jsonRequest(_ header: [String: Any], data: Data, owner: ObjectIdentifier, clientID: String, reply: @escaping (Any?, String?) -> Void) {
        var result = Data(), status = 500
        let request = worker.request(header, body: data) { event, bytes in
            switch event["event"] as? String {
            case "response_start": status = event["status"] as? Int ?? 500
            case "body":
                guard result.count + bytes.count <= 64 * 1024 * 1024 else { throw BridgeFailure.invalid("응답 크기를 초과했습니다.") }
                result.append(bytes)
            case "complete":
                self.requests[owner]?.removeValue(forKey: clientID)
                reply(["status":status,"text":String(decoding:result,as:UTF8.self)], nil)
            case "error":
                self.requests[owner]?.removeValue(forKey: clientID)
                reply(nil, event["message"] as? String ?? "요청을 처리하지 못했습니다.")
            default: break
            }
        }
        requests[owner, default: [:]][clientID] = request
    }

    private func uninstallRequest(_ fields: [String:Any], completion: @escaping (Result<[String:Any],Error>) -> Void) {
        var finished = false
        worker.request(fields) { event,_ in
            guard !finished else { return }
            if event["event"] as? String == "complete" { finished = true; completion(.success(event)) }
            if event["event"] as? String == "error" { finished = true; completion(.failure(BridgeFailure.invalid(event["message"] as? String ?? "설치 삭제 준비 실패"))) }
        }
    }

    private func chooseUninstall(page: AppWindow, selection: [String:Any], reset: Bool = false, reply: @escaping (Any?,String?) -> Void) {
        uninstalling = true
        let choice = UninstallChoiceView(selection:selection.mapValues { $0 as? Bool ?? true })
        let alert = NSAlert(); alert.messageText = reset ? "초기화 전에 보존할 기록을 선택하세요" : "삭제할 항목을 선택하세요"
        alert.informativeText = reset ? "앱은 유지하고 원래 보관함·수정 이력, 설정·저장된 API 키, 전용 모델·추가 엔진·캐시·로그를 초기화합니다. 보존할 기록을 선택하세요. 모델과 추가 엔진은 이후 다시 준비해야 합니다." : "앱·솔라시 전용 모델과 엔진·설정은 함께 삭제합니다. 아래 사용자 기록은 각각 보존하거나 삭제하도록 선택하세요."
        alert.accessoryView = choice; alert.addButton(withTitle:"취소"); alert.addButton(withTitle:"선택한 항목으로 계속")
        alert.beginSheetModal(for:page.window) { answer in
            guard answer == .alertSecondButtonReturn else { self.uninstalling = false; reply(["cancelled":true],nil); return }
            self.beginUninstall(page:page,selection:choice.selection.mapValues { $0 as Any },reset:reset,reply:reply)
        }
    }

    private func beginUninstall(page: AppWindow, selection: [String:Any], reset: Bool = false, reply: @escaping (Any?,String?) -> Void) {
        guard let helper = Bundle.main.resourceURL?.appendingPathComponent("UninstallHelper"), FileManager.default.isExecutableFile(atPath:helper.path) else { uninstalling = false; reply(nil,"설치 삭제 도우미가 없습니다. 앱을 다시 설치하세요."); return }
        uninstalling = true
        let panel = NSOpenPanel(); panel.title = "솔라시 보존 자료 저장 위치"
        panel.message = "선택한 폴더 안에 새 보관 폴더를 만듭니다. 기존 파일은 덮어쓰지 않습니다."
        panel.canChooseDirectories = true; panel.canChooseFiles = false; panel.canCreateDirectories = true; panel.allowsMultipleSelection = false
        panel.directoryURL = FileManager.default.urls(for:.documentDirectory,in:.userDomainMask).first
        panel.beginSheetModal(for:page.window) { answer in
            guard answer == .OK, let directory = panel.url?.resolvingSymlinksInPath() else { self.uninstalling = false; reply(["cancelled":true],nil); return }
            let bundle = Bundle.main.bundleURL.resolvingSymlinksInPath()
            guard !directory.path.hasPrefix(bundle.path+"/"), directory != bundle else { self.uninstalling = false; reply(nil,"앱 밖의 보존 위치를 선택하세요."); return }
            let pages = [self.mainWindow].compactMap{$0}+self.extraWindows
            self.prepareClose(pages) { result in
                switch result {
                case .failure(let error): self.uninstalling = false; reply(nil,error.localizedDescription)
                case .success:
                    self.uninstallFrozen = true
                    page.showStatus("1/3 · 보존 파일 생성·검증 중입니다. 원래 기록은 유지하고 있습니다.")
                    self.uninstallRequest(["op":"uninstall_prepare","destination":directory.path,"selection":selection]) { prepared in
                        do {
                            let value = try prepared.get()
                            guard let receipt = value["receipt"] as? [String:Any], let receiptID = receipt["id"] as? String else { throw BridgeFailure.invalid("보존 결과를 확인할 수 없습니다.") }
                            page.showStatus("2/3 · 삭제 대상과 보존 결과를 다시 확인하고 있습니다.")
                            self.uninstallRequest(["op":"uninstall_plan","receipt_id":receiptID,"app_bundle":bundle.path]) { planned in
                                do {
                                    let summary = try planned.get()
                                    guard let path = summary["plan_path"] as? String, let originalDigest = summary["plan_sha256"] as? String else { throw BridgeFailure.invalid("삭제 대상 계획이 없습니다.") }
                                    let planURL = URL(fileURLWithPath:path), stagedHelper = planURL.deletingLastPathComponent().appendingPathComponent("UninstallHelper")
                                    try FileManager.default.copyItem(at:helper,to:stagedHelper)
                                    DispatchQueue.global(qos:.userInitiated).async {
                                        let checked = Result {
                                            let digest = reset ? try RemovalPlan.prepareReset(planURL,digest:originalDigest) : originalDigest
                                            let plan = try RemovalPlan.load(planURL,digest:digest); try plan.validate(); return (plan,digest)
                                        }
                                        DispatchQueue.main.async {
                                            do {
                                                let (plan,digest) = try checked.get()
                                                page.showStatus("3/3 · 보존 검증을 마쳤습니다. 마지막 확인을 기다리고 있습니다.")
                                                self.confirmUninstall(page:page,plan:plan,planURL:planURL,digest:digest,helper:stagedHelper,receiptID:receiptID,reply:reply)
                                            } catch { self.cancelUninstall(receiptID:receiptID,error:error,reply:reply) }
                                        }
                                    }
                                } catch { self.cancelUninstall(receiptID:receiptID,error:error,reply:reply) }
                            }
                        } catch { self.cancelUninstall(receiptID:nil,error:error,reply:reply) }
                    }
                }
            }
        }
    }

    private func cancelUninstall(receiptID: String?, error: Error?, reply: @escaping (Any?,String?) -> Void) {
        var request: [String:Any] = ["op":"uninstall_cancel"]
        if let receiptID { request["receipt_id"] = receiptID }
        uninstallRequest(request) { result in
            self.uninstallFrozen = false; self.uninstalling = false
            for page in [self.mainWindow].compactMap({$0})+self.extraWindows {
                page.webView.callAsyncJavaScript("window.solasiLifecycle?.resume()",arguments:[:],in:nil,in:.page,completionHandler:nil)
            }
            var failure = error
            if case .failure(let cancelError) = result, failure == nil { failure = cancelError }
            self.mainWindow?.showStatus(failure?.localizedDescription ?? "작업을 취소했습니다. 앱과 원래 기록을 유지했습니다.")
            reply(failure == nil ? ["cancelled":true] : nil,failure?.localizedDescription)
        }
    }

    private func confirmUninstall(page: AppWindow, plan: RemovalPlan, planURL: URL, digest: String, helper: URL, receiptID: String, reply: @escaping (Any?,String?) -> Void) {
        let reset = plan.isReset
        let alert = NSAlert(); alert.alertStyle = .warning; alert.messageText = reset ? "솔라시를 초기화할까요?" : "솔라시를 실제 삭제할까요?"
        let count = plan.receipt.files.count
        alert.informativeText = removalSelectionSummary(plan.receipt.selection) + "\n" + (count == 0 ? "보존할 기록이 없습니다. 원래 기록을 모두 삭제합니다." : "보존 파일 \(count)개를 검증했습니다.\n위치: \(plan.receipt.directory)") +
            (reset ? "\n초기화: 원래 보관함·수정 이력, 전용 모델·추가 엔진, 앱 설정·저장된 API 키·캐시·로그\n앱과 내장 기본 엔진은 유지합니다. AI 기능은 모델·추가 엔진을 다시 준비한 뒤 사용할 수 있습니다.\n" : "\n삭제: 원래 보관함·수정 이력, 앱, 전용 모델·엔진, 앱 설정·저장된 API 키·캐시·로그\n") + "예상 확보 용량: \(ByteCountFormatter.string(fromByteCount:plan.bytes,countStyle:.file))\n" +
            (plan.preserved.isEmpty ? "" : "별도 백업·실험 자료 등 \(plan.preserved.count)개 항목은 남깁니다.\n") +
            "PDF는 열람용이며 원래 필기 편집·이력 복원을 보장하지 않습니다. 삭제한 원래 기록은 되돌릴 수 없습니다."
        alert.addButton(withTitle:"취소"); let execute = alert.addButton(withTitle:reset ? "초기화 실행" : "삭제 실행"); alert.addButton(withTitle:"선택 변경"); alert.addButton(withTitle:"보존 폴더 열기")
        let field = NSTextField(frame:NSRect(x:0,y:0,width:360,height:26)); field.placeholderString = reset ? "솔라시 초기화" : "솔라시 삭제"; field.setAccessibilityLabel(reset ? "초기화 확인 문구" : "삭제 확인 문구")
        let label = NSTextField(wrappingLabelWithString:"계속하려면 ‘\(reset ? "솔라시 초기화" : "솔라시 삭제")’를 입력하세요.")
        let accessory = NSStackView(views:[label,field]); accessory.orientation = .vertical; accessory.alignment = .leading; accessory.spacing = 8
        accessory.frame = NSRect(x:0,y:0,width:360,height:60); alert.accessoryView = accessory; execute.isEnabled = false
        let observer = NotificationCenter.default.addObserver(forName:NSControl.textDidChangeNotification,object:field,queue:.main) { _ in execute.isEnabled = removalConsent(verified:true,confirmed:true,phrase:field.stringValue,reset:reset) }
        alert.beginSheetModal(for:page.window) { response in
            NotificationCenter.default.removeObserver(observer)
            if response == .alertThirdButtonReturn {
                self.cancelUninstall(receiptID:receiptID,error:nil) { _,error in
                    if let error { reply(nil,error); return }
                    self.chooseUninstall(page:page,selection:plan.receipt.selection.mapValues { $0 as Any },reset:reset,reply:reply)
                }; return
            }
            if response.rawValue == NSApplication.ModalResponse.alertFirstButtonReturn.rawValue+3 {
                NSWorkspace.shared.open(URL(fileURLWithPath:plan.receipt.directory))
                self.confirmUninstall(page:page,plan:plan,planURL:planURL,digest:digest,helper:helper,receiptID:receiptID,reply:reply); return
            }
            guard removalConsent(verified:true,confirmed:response == .alertSecondButtonReturn,phrase:field.stringValue,reset:reset) else { self.cancelUninstall(receiptID:receiptID,error:nil,reply:reply); return }
            page.showStatus("보존 파일을 마지막으로 검증하고 앱을 종료합니다…")
            self.uninstallRequest(["op":"uninstall_verify","receipt_id":receiptID]) { result in
                do {
                    guard try result.get()["verified"] as? Bool == true else { throw BridgeFailure.invalid("보존 검증이 완료되지 않았습니다.") }
                    let process = Process(); process.executableURL = helper
                    process.arguments = ["--execute",planURL.path,digest,String(getpid()),String(self.worker.process.processIdentifier)]
                    process.standardInput = FileHandle.nullDevice; process.standardOutput = FileHandle.nullDevice; process.standardError = FileHandle.nullDevice
                    try process.run()
                    self.uninstallAuthorized = true
                    reply(["accepted":true],nil)
                    NSApp.terminate(nil)
                } catch { self.cancelUninstall(receiptID:receiptID,error:error,reply:reply) }
            }
        }
        alert.window.initialFirstResponder = field
    }

    private func consumeClick(_ page: AppWindow) -> Bool {
        guard Date().timeIntervalSince(page.userClickAt) < 5 else { return false }
        page.userClickAt = .distantPast; return true
    }

    private func prepareVault() {
        var data = Data(), status = 500
        worker.request(["op":"http","method":"GET","path":"/api/native/state"]) { header, bytes in
            switch header["event"] as? String {
            case "response_start": status = header["status"] as? Int ?? 500
            case "body":
                guard data.count + bytes.count <= 1024 * 1024 else { throw BridgeFailure.invalid("보관함 응답을 확인하세요.") }
                data.append(bytes)
            case "complete":
                guard status == 200, let state = try JSONSerialization.jsonObject(with:data) as? [String:Any],
                      let id = state["vault_id"] as? String, id.range(of:"^[a-f0-9]{32}$",options:.regularExpression) != nil else {
                    self.fail("보관함 식별자를 확인할 수 없습니다."); return
                }
                self.vaultID = id; self.workerReady = true
                self.mainWindow?.webView.load(URLRequest(url:URL(string:"solasi-app://app/")!))
            case "error": self.fail(header["message"] as? String ?? "보관함을 열 수 없습니다.")
            default: break
            }
        }
    }

    private func saveDestination(page: AppWindow, filename: String, completion: @escaping (Result<ExclusiveExport?, Error>) -> Void) {
        let panel = NSSavePanel()
        panel.title = "Solasi 내보내기"; panel.message = "기존 파일은 보존합니다. 새 파일 이름을 선택하세요."
        panel.nameFieldStringValue = (filename as NSString).lastPathComponent; panel.canCreateDirectories = true
        panel.beginSheetModal(for: page.window) { result in
            guard result == .OK, let destination = panel.url else { completion(ExclusiveExport.prepare(destination: nil)); return }
            if FileManager.default.fileExists(atPath: destination.path) {
                let alert = NSAlert(); alert.messageText = "기존 파일을 덮어쓰지 않습니다"; alert.informativeText = "다른 파일 이름이나 저장 위치를 선택하세요."
                alert.beginSheetModal(for: page.window) { _ in self.saveDestination(page: page, filename: filename, completion: completion) }; return
            }
            completion(ExclusiveExport.prepare(destination: destination))
        }
    }

    private func exportResource(_ url: URL, page: AppWindow) {
        guard consumeClick(page) else { return }
        var components = URLComponents(url: url, resolvingAgainstBaseURL: false)!
        components.scheme = nil; components.host = nil; components.fragment = nil
        let path = components.string!
        guard AppResourcePolicy.resourcePath(path) else { return }
        let suffix = components.path.hasSuffix("/notebook.pdf") ? "pdf" : components.queryItems?.first(where: { $0.name == "format" })?.value == "txt" ? "txt" : "md"
        page.showStatus("")
        saveDestination(page: page, filename: "Solasi-내보내기." + suffix) { selection in
            let export: ExclusiveExport
            do { guard let selected = try selection.get() else { page.showStatus("내보내기를 취소했습니다."); return }; export = selected }
            catch { page.showStatus("저장 위치를 준비할 수 없습니다. " + error.localizedDescription); return }
            var successful = false
            self.worker.request(["op":"http","method":"GET","path":path]) { header, bytes in
                switch header["event"] as? String {
                case "response_start":
                    successful = (200..<300).contains(header["status"] as? Int ?? 500)
                    if !successful { throw BridgeFailure.invalid("내보낼 기록을 불러올 수 없습니다.") }
                case "body": try export.append(bytes)
                case "complete":
                    guard successful else { page.showStatus(export.preserveFailure(BridgeFailure.invalid("내보낼 기록을 불러올 수 없습니다.")).localizedDescription); return }
                    do { try export.finish(); page.showStatus("내보내기를 완료했습니다.") }
                    catch { page.showStatus(error.localizedDescription) }
                case "error": page.showStatus(export.preserveFailure(BridgeFailure.invalid(header["message"] as? String ?? "내보내기에 실패했습니다.")).localizedDescription)
                default: break
                }
            }
        }
    }

    func application(_ application: NSApplication, open urls: [URL]) {
        guard let url = urls.first, url.scheme == "solasi", url.host == "audio" else { return }
        pendingAudio = url; showWindow(); deliverAudio()
    }

    private func deliverAudio() {
        guard let url = pendingAudio,!vaultID.isEmpty,!deliveringAudio else { return }
        guard let link = AppResourcePolicy.audioLink(url,vault:vaultID) else { pendingAudio=nil;mainWindow?.showStatus("이 보관함에 연결된 원음 링크가 아닙니다.");return }
        guard
              let page=mainWindow,page.uiReady,AppResourcePolicy.trustedUI(page.webView.url),!page.webView.isLoading else { return }
        let webView=page.webView;deliveringAudio=true
        let payload: [String: Any] = ["url":"/api/recordings/" + link.id + "/audio", "start":link.start, "end":link.end]
        webView.callAsyncJavaScript("window.dispatchEvent(new CustomEvent('solasi-open-audio', {detail: clip}))", arguments: ["clip":payload], in: nil, in: .page) { result in
            self.deliveringAudio=false
            if case .success=result { if self.pendingAudio==url { self.pendingAudio=nil };self.deliverAudio() }
            else { page.showStatus("원음 링크를 화면에 전달하지 못했습니다. 화면을 다시 연 뒤 링크를 눌러 주세요.") }
        }
    }

    func webView(_ webView: WKWebView, requestMediaCapturePermissionFor origin: WKSecurityOrigin, initiatedByFrame frame: WKFrameInfo, type: WKMediaCaptureType, decisionHandler: @escaping (WKPermissionDecision) -> Void) {
        guard webView === mainWindow?.webView, trusted(webView.url), trusted(origin), frame.isMainFrame,
              trusted(frame.securityOrigin), type == .microphone,
              let page = mainWindow, Date().timeIntervalSince(page.userClickAt) < 5 else { decisionHandler(.deny); return }
        page.userClickAt = .distantPast
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized: decisionHandler(.grant)
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .audio) { [weak self, weak webView] allowed in
                DispatchQueue.main.async {
                    guard let self = self, let webView = webView else { decisionHandler(.deny); return }
                    decisionHandler(allowed && !self.quitting && self.trusted(webView.url) ? .grant : .deny)
                }
            }
        default: decisionHandler(.deny)
        }
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if navigationAction.shouldPerformDownload, trustedBlob(navigationAction.request.url),
           navigationAction.sourceFrame.isMainFrame, trusted(navigationAction.sourceFrame.securityOrigin), trusted(webView.url) {
            decisionHandler(.download)
            return
        }
        if trusted(navigationAction.request.url) {
            if navigationAction.shouldPerformDownload, let url = navigationAction.request.url, let page = page(for: webView),
               AppResourcePolicy.trustedUI(webView.url), navigationAction.sourceFrame.isMainFrame {
                decisionHandler(.cancel); exportResource(url, page: page)
            } else { decisionHandler(.allow) }
            return
        }
        decisionHandler(.cancel)
        openExternalLink(navigationAction, from: webView)
    }

    private func openExternalLink(_ action: WKNavigationAction, from webView: WKWebView) {
        guard action.navigationType == .linkActivated, action.sourceFrame.isMainFrame,
              trusted(action.sourceFrame.securityOrigin), let url = action.request.url,
              ["http", "https"].contains(url.scheme ?? ""), url.user == nil, url.password == nil,
              let page = page(for: webView), Date().timeIntervalSince(page.userClickAt) < 5 else { return }
        page.userClickAt = .distantPast
        NSWorkspace.shared.open(url)
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationResponse: WKNavigationResponse, decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        if trustedBlob(navigationResponse.response.url), navigationResponse.isForMainFrame, trusted(webView.url) {
            decisionHandler(.download)
            return
        }
        guard trusted(navigationResponse.response.url) else { decisionHandler(.cancel); return }
        decisionHandler(navigationResponse.canShowMIMEType ? .allow : .download)
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        guard trusted(navigationAction.request.url) else { openExternalLink(navigationAction, from: webView); return nil }
        guard navigationAction.targetFrame == nil, navigationAction.sourceFrame.isMainFrame,
              trusted(navigationAction.sourceFrame.securityOrigin) else { return nil }
        configuration.websiteDataStore = webView.configuration.websiteDataStore
        let page = makeWindow(configuration: configuration)
        page.showStatus("")
        extraWindows.append(page)
        page.window.makeKeyAndOrderFront(nil)
        return page.webView
    }

    func webViewDidClose(_ webView: WKWebView) { page(for: webView)?.window.performClose(nil) }

    func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) { page(for:webView)?.uiReady=false }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { page(for: webView)?.showStatus(""); deliverAudio() }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { showLoadFailure(webView, error: error) }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { showLoadFailure(webView, error: error) }

    private func showLoadFailure(_ webView: WKWebView, error: Error) {
        let error = error as NSError
        guard !quitting, !(error.domain == NSURLErrorDomain && error.code == NSURLErrorCancelled),
              !(error.domain == "WebKitErrorDomain" && error.code == 102) else { return }
        page(for: webView)?.showStatus("화면을 불러오지 못했습니다. 로그를 확인하세요. \(error.localizedDescription)", canRetry: true)
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        for (id,active) in players where active.owner == ObjectIdentifier(webView) { active.player.close();players.removeValue(forKey:id) }
        for active in Array(captures.values) where active.owner == ObjectIdentifier(webView) { active.capture.stop(interrupted:true,reason:"화면 프로세스가 종료되었습니다") {} }
        page(for: webView)?.showStatus("화면 프로세스가 종료되었습니다. 녹음이 중단됐을 수 있습니다. 화면을 다시 열고 저장된 원음을 확인하세요.", canRetry: true)
    }

    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) { start(download, in: webView) }
    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) { start(download, in: webView) }

    private func start(_ download: WKDownload, in webView: WKWebView) {
        downloadWindows[ObjectIdentifier(download)] = page(for: webView)
        download.delegate = self
    }

    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        guard trusted(response.url) || trustedBlob(response.url), let page = downloadWindows[ObjectIdentifier(download)] else { completionHandler(nil); return }
        chooseDestination(for: download, page: page, filename: suggestedFilename, completionHandler: completionHandler)
    }

    private func chooseDestination(for download: WKDownload, page: AppWindow, filename: String, completionHandler: @escaping (URL?) -> Void) {
        let panel = NSSavePanel()
        panel.title = "Solasi 내보내기"
        panel.message = "기존 파일은 보존합니다. 새 파일 이름을 선택하세요."
        panel.nameFieldStringValue = (filename as NSString).lastPathComponent
        panel.canCreateDirectories = true
        page.window.makeKeyAndOrderFront(nil)
        panel.beginSheetModal(for: page.window) { [weak self] result in
            guard let self = self else { completionHandler(nil); return }
            guard result == .OK, let url = panel.url else {
                self.cancelledDownloads.insert(ObjectIdentifier(download))
                completionHandler(nil)
                return
            }
            if FileManager.default.fileExists(atPath: url.path) {
                let alert = NSAlert()
                alert.messageText = "기존 파일을 덮어쓰지 않습니다"
                alert.informativeText = "다른 파일 이름이나 저장 위치를 선택하세요."
                alert.addButton(withTitle: "다시 선택")
                alert.beginSheetModal(for: page.window) { _ in
                    self.chooseDestination(for: download, page: page, filename: filename, completionHandler: completionHandler)
                }
                return
            }
            do {
                let staging = url.deletingLastPathComponent().appendingPathComponent(".solasi-export-" + UUID().uuidString, isDirectory: true)
                try FileManager.default.createDirectory(at: staging, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
                self.downloadTargets[ObjectIdentifier(download)] = (url, staging)
                completionHandler(staging.appendingPathComponent("download"))
            } catch {
                page.showStatus("저장 위치를 준비할 수 없습니다. \(error.localizedDescription)")
                self.cancelledDownloads.insert(ObjectIdentifier(download))
                completionHandler(nil)
            }
        }
    }

    func download(_ download: WKDownload, willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest, decisionHandler: @escaping (WKDownload.RedirectPolicy) -> Void) {
        decisionHandler(trusted(request.url) ? .allow : .cancel)
    }

    func downloadDidFinish(_ download: WKDownload) {
        let key = ObjectIdentifier(download)
        let page = downloadWindows.removeValue(forKey: key)
        cancelledDownloads.remove(key)
        guard let target = downloadTargets.removeValue(forKey: key) else { return }
        let staged = target.staging.appendingPathComponent("download")
        if renamex_np(staged.path, target.destination.path, UInt32(RENAME_EXCL)) == 0 {
            try? FileManager.default.removeItem(at: target.staging)
            page?.showStatus("내보내기를 완료했습니다.")
        } else {
            page?.showStatus("저장 위치가 변경되었거나 같은 이름의 파일이 생겼습니다. 기존 파일은 보존했으며 내보낸 파일은 다음 위치에 있습니다: \(staged.path)")
        }
    }

    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        let key = ObjectIdentifier(download)
        let page = downloadWindows.removeValue(forKey: key)
        let cancelled = cancelledDownloads.remove(key) != nil
        if let target = downloadTargets.removeValue(forKey: key) { try? FileManager.default.removeItem(at: target.staging) }
        let failure = error as NSError
        if !cancelled && !(failure.domain == NSURLErrorDomain && failure.code == NSURLErrorCancelled) {
            page?.showStatus("내보내기에 실패했습니다. \(failure.localizedDescription)")
        }
    }

    private func fail(_ message: String) {
        guard !quitting else { return }
        if mainWindow == nil { let alert = NSAlert(); alert.messageText = "Solasi를 시작하지 못했습니다"; alert.informativeText = message; alert.runModal(); return }
        mainWindow?.showStatus(message)
        showWindow()
    }
}

@main
enum SolasiMain {
    static func main() {
        let app = NSApplication.shared
        let delegate = SolasiApp()
        app.setActivationPolicy(.regular)
        app.delegate = delegate
        app.run()
    }
}
