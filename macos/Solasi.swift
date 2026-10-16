import AppKit
import AVFoundation
import Darwin
import Foundation
import WebKit

struct LaunchSettings: Decodable {
    let python: String
    let source: String
    let data: String
    let runtime: String
    let port: Int
}

private final class AppWindow {
    let window: NSWindow
    let webView: WKWebView
    let status = NSTextField(wrappingLabelWithString: "로컬 서버를 준비하고 있습니다…")
    let retry = NSButton(title: "화면 다시 열기", target: nil, action: nil)
    var userClickAt = Date.distantPast

    init(configuration: WKWebViewConfiguration) {
        webView = WKWebView(frame: .zero, configuration: configuration)
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1200, height: 820), styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView], backing: .buffered, defer: false)
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
        let content = NSStackView(views: [notice, webView])
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
            webView.heightAnchor.constraint(greaterThanOrEqualToConstant: 200)
        ])
        window.center()
    }

    func showStatus(_ message: String, canRetry: Bool = false) {
        status.stringValue = message
        status.superview?.isHidden = message.isEmpty
        retry.isHidden = !canRetry
    }
}

final class SolasiApp: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler, WKDownloadDelegate {
    private var server: Process?
    private var output = Data()
    private var originURL: URL?
    private var receivedBootstrap = false
    private var mainWindow: AppWindow?
    private var extraWindows: [AppWindow] = []
    private var downloadWindows: [ObjectIdentifier: AppWindow] = [:]
    private var cancelledDownloads: Set<ObjectIdentifier> = []
    private var downloadTargets: [ObjectIdentifier: (destination: URL, staging: URL)] = [:]
    private let clickWorld = WKContentWorld.world(name: "SolasiUserInput")
    private var quitting = false
    private var log: FileHandle?
    private let logURL = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Logs/Solasi/server.log")

    func applicationDidFinishLaunching(_ notification: Notification) {
        installMenu()
        // Dock can retain the generic icon after replacing an existing local app bundle.
        if let iconURL = Bundle.main.url(forResource: "Solasi", withExtension: "icns"), let icon = NSImage(contentsOf: iconURL) {
            NSApp.applicationIconImage = icon
        }
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        configuration.userContentController.add(self, contentWorld: clickWorld, name: "userClick")
        configuration.userContentController.addUserScript(WKUserScript(source: """
            document.addEventListener('click', event => {
                if (event.isTrusted) window.webkit.messageHandlers.userClick.postMessage(null);
            }, true);
            """, injectionTime: .atDocumentStart, forMainFrameOnly: true, in: clickWorld))
        mainWindow = makeWindow(configuration: configuration)
        showWindow()
        do {
            guard let settingsURL = Bundle.main.url(forResource: "launch", withExtension: "json") else {
                throw NSError(domain: "Solasi", code: 1, userInfo: [NSLocalizedDescriptionKey: "실행 설정이 없습니다. 실행 앱을 다시 설치하세요."])
            }
            let settings = try JSONDecoder().decode(LaunchSettings.self, from: Data(contentsOf: settingsURL))
            guard (1...65535).contains(settings.port) else {
                throw NSError(domain: "Solasi", code: 3, userInfo: [NSLocalizedDescriptionKey: "앱 초안 저장소를 유지하려면 고정 포트로 다시 설치하세요."])
            }
            for path in [settings.python, settings.source + "/frontend/dist/index.html", settings.data, settings.runtime] {
                guard FileManager.default.fileExists(atPath: path) else {
                    throw NSError(domain: "Solasi", code: 2, userInfo: [NSLocalizedDescriptionKey: "필요한 파일이나 폴더가 없습니다: \(path)"])
                }
            }
            try FileManager.default.createDirectory(at: logURL.deletingLastPathComponent(), withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            FileManager.default.createFile(atPath: logURL.path, contents: nil, attributes: [.posixPermissions: 0o600])
            log = try FileHandle(forWritingTo: logURL)
            let process = Process()
            let pipe = Pipe()
            process.executableURL = URL(fileURLWithPath: settings.python)
            process.currentDirectoryURL = URL(fileURLWithPath: settings.source)
            process.arguments = ["-m", "lecture_study.launcher", "--data-dir", settings.data, "--runtime-dir", settings.runtime, "--port", String(settings.port), "--strict-port", "--no-browser"]
            var environment = ProcessInfo.processInfo.environment
            environment["PYTHONPATH"] = settings.source
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            environment["PYTHONUNBUFFERED"] = "1"
            environment["SOLASI_OWNER_PID"] = String(ProcessInfo.processInfo.processIdentifier)
            process.environment = environment
            process.standardOutput = pipe
            process.standardError = log
            pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
                let data = handle.availableData
                if data.isEmpty { handle.readabilityHandler = nil; return }
                DispatchQueue.main.async { self?.received(data) }
            }
            process.terminationHandler = { [weak self] _ in
                pipe.fileHandleForReading.readabilityHandler = nil
                DispatchQueue.main.async {
                    guard let self = self else { return }
                    if self.quitting { NSApp.reply(toApplicationShouldTerminate: true) }
                    else { self.fail(self.originURL == nil ? "로컬 서버를 시작하지 못했습니다. 실행 중인 Solasi·포트 충돌과 로그를 확인하세요." : "로컬 서버가 종료되었습니다. 로그를 확인한 뒤 앱을 다시 실행하세요.") }
                }
            }
            server = process
            try process.run()
            DispatchQueue.main.asyncAfter(deadline: .now() + 120) { [weak self] in
                guard let self = self, !self.quitting, self.originURL == nil else { return }
                self.fail("서버 준비 시간이 초과되었습니다. 로그에서 원인을 확인하세요.")
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
        guard let url = url, let origin = originURL else { return false }
        return url.scheme == "http" && url.host == "127.0.0.1" && url.port == origin.port && url.user == nil && url.password == nil
    }

    private func trustedBlob(_ url: URL?) -> Bool {
        guard let url = url, url.scheme == "blob" else { return false }
        return trusted(URL(string: String(url.absoluteString.dropFirst("blob:".count))))
    }

    private func trusted(_ origin: WKSecurityOrigin) -> Bool {
        origin.protocol == "http" && origin.host == "127.0.0.1" && origin.port == originURL?.port
    }

    private func received(_ data: Data) {
        output.append(data)
        while let newline = output.firstIndex(of: 10) {
            let line = String(decoding: output[..<newline], as: UTF8.self)
            output.removeSubrange(...newline)
            guard !receivedBootstrap, line.hasPrefix("실행 링크: "),
                  let url = URL(string: String(line.dropFirst("실행 링크: ".count))),
                  url.scheme == "http", url.host == "127.0.0.1", let port = url.port, (1...65535).contains(port),
                  url.user == nil, url.password == nil, url.query == nil,
                  url.path == "/", url.fragment?.hasPrefix("bootstrap=") == true else { continue }
            receivedBootstrap = true
            waitUntilReady(url, remaining: 240)
        }
        if output.count > 65536 { output.removeAll() }
    }

    private func waitUntilReady(_ url: URL, remaining: Int) {
        guard !quitting, server?.isRunning == true else { return }
        var components = URLComponents(url: url, resolvingAgainstBaseURL: false)!
        components.fragment = nil
        let base = components.url!
        var request = URLRequest(url: base.appendingPathComponent("api/health"))
        request.timeoutInterval = 1
        URLSession.shared.dataTask(with: request) { [weak self] _, response, _ in
            DispatchQueue.main.async {
                guard let self = self, !self.quitting, self.server?.isRunning == true else { return }
                if (response as? HTTPURLResponse)?.statusCode == 200, response?.url == request.url {
                    self.originURL = base
                    self.mainWindow?.webView.load(URLRequest(url: url))
                } else if remaining > 0 {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) { self.waitUntilReady(url, remaining: remaining - 1) }
                } else { self.fail("로컬 서버에 연결할 수 없습니다.") }
            }
        }.resume()
    }

    @objc private func showWindow() {
        if mainWindow?.window.isMiniaturized == true { mainWindow?.window.deminiaturize(nil) }
        mainWindow?.window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    @objc private func showLog() { NSWorkspace.shared.open(logURL) }

    @objc private func retryPage(_ sender: NSButton) {
        guard let page = ([mainWindow].compactMap { $0 } + extraWindows).first(where: { $0.retry === sender }), server?.isRunning == true else { return }
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
        if sender === mainWindow?.window { sender.orderOut(nil); return false }
        return true
    }

    func windowWillClose(_ notification: Notification) {
        guard let window = notification.object as? NSWindow else { return }
        DispatchQueue.main.async { self.extraWindows.removeAll { $0.window === window } }
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        quitting = true
        if let process = server, process.isRunning {
            process.terminate()
            return .terminateLater
        }
        return .terminateNow
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.name == "userClick", message.world == clickWorld, message.frameInfo.isMainFrame,
              trusted(message.frameInfo.securityOrigin), let webView = message.webView,
              trusted(webView.url) else { return }
        page(for: webView)?.userClickAt = Date()
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
            decisionHandler(navigationAction.shouldPerformDownload ? .download : .allow)
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

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { page(for: webView)?.showStatus("") }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { showLoadFailure(webView, error: error) }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { showLoadFailure(webView, error: error) }

    private func showLoadFailure(_ webView: WKWebView, error: Error) {
        let error = error as NSError
        guard !quitting, !(error.domain == NSURLErrorDomain && error.code == NSURLErrorCancelled),
              !(error.domain == "WebKitErrorDomain" && error.code == 102) else { return }
        page(for: webView)?.showStatus("화면을 불러오지 못했습니다. 네트워크 연결과 로그를 확인하세요. \(error.localizedDescription)", canRetry: true)
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
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
        mainWindow?.showStatus(message)
        showWindow()
    }
}

let app = NSApplication.shared
let delegate = SolasiApp()
app.setActivationPolicy(.regular)
app.delegate = delegate
app.run()
