import Darwin
import Foundation
import UniformTypeIdentifiers
import WebKit

enum AppResourcePolicy {
    static func trusted(_ url: URL?) -> Bool {
        guard let url = url else { return false }
        return url.scheme == "solasi-app" && url.host == "app" && url.port == nil && url.user == nil && url.password == nil
    }
    static func trustedUI(_ url: URL?) -> Bool { trusted(url) && ["/", "/index.html"].contains(url!.path) }
    static func validAPIPath(_ path: String) -> Bool {
        guard path.utf8.count <= 8192, let parts = URLComponents(string: path), parts.scheme == nil, parts.host == nil,
              parts.fragment == nil, parts.path.hasPrefix("/api/"), !parts.path.contains("\\"), !parts.path.contains("\0"),
              !parts.path.split(separator: "/").contains(where: { $0 == "." || $0 == ".." }),
              !["/api/bootstrap", "/api/client"].contains(parts.path) else { return false }
        return true
    }
    static func resourcePath(_ path: String) -> Bool {
        guard validAPIPath(path), let parts = URLComponents(string: path) else { return false }
        let pattern = "^/api/(assets/[a-f0-9]{32}/(original|pages/[1-9][0-9]*|images/[A-Za-z0-9_.-]+)|recordings/[a-f0-9]{32}/audio|sessions/[a-f0-9]{32}/transcripts/export|artifacts/[a-f0-9]{32}/export)$"
        return parts.path.range(of: pattern, options: .regularExpression) != nil
    }
    static func byteRange(_ header: String?, size: Int) throws -> Range<Int> {
        guard let header = header else { return 0..<size }
        guard header.hasPrefix("bytes="), size > 0 else { throw BridgeFailure.invalid("잘못된 재생 범위입니다.") }
        let parts = header.dropFirst(6).split(separator: "-", omittingEmptySubsequences: false)
        guard parts.count == 2 else { throw BridgeFailure.invalid("잘못된 재생 범위입니다.") }
        if parts[0].isEmpty, let count = Int(parts[1]), count > 0 { return max(0, size - count)..<size }
        guard let start = Int(parts[0]), start >= 0, start < size,
              parts[1].isEmpty || Int(parts[1]) != nil else { throw BridgeFailure.invalid("잘못된 재생 범위입니다.") }
        let end = parts[1].isEmpty ? size - 1 : min(Int(parts[1])!, size - 1)
        guard end >= start else { throw BridgeFailure.invalid("잘못된 재생 범위입니다.") }
        return start..<end + 1
    }
    static func audioLink(_ url: URL, vault: String) -> (id: String, start: Double, end: Double)? {
        guard url.scheme == "solasi", url.host == "audio", url.user == nil, url.password == nil, url.port == nil,
              let parts = URLComponents(url: url, resolvingAgainstBaseURL: false), parts.fragment == nil else { return nil }
        let path = url.path.split(separator: "/")
        guard path.count == 2, path[0] == vault,
              path[1].range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil,
              let query = parts.queryItems, query.count == 2,
              query.filter({ $0.name == "start_ms" }).count == 1, query.filter({ $0.name == "end_ms" }).count == 1,
              let start = Double(query.first(where: { $0.name == "start_ms" })?.value ?? ""),
              let end = Double(query.first(where: { $0.name == "end_ms" })?.value ?? ""),
              start.isFinite, end.isFinite, start >= 0, end > start else { return nil }
        return (String(path[1]), start / 1000, end / 1000)
    }
}

final class ExclusiveExport {
    let destination: URL, staging: URL
    private var handle: FileHandle?
    init(destination: URL) throws {
        self.destination = destination
        staging = destination.deletingLastPathComponent().appendingPathComponent(".solasi-export-" + UUID().uuidString)
        let descriptor = open(staging.path, O_CREAT | O_EXCL | O_WRONLY, 0o600)
        guard descriptor >= 0 else { throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno)) }
        handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
    }
    func append(_ data: Data) throws {
        guard let handle = handle else { throw BridgeFailure.invalid("내보내기가 이미 끝났습니다.") }
        try handle.write(contentsOf: data)
    }
    func finish() throws {
        try handle?.synchronize(); try handle?.close(); handle = nil
        guard renamex_np(staging.path, destination.path, UInt32(RENAME_EXCL)) == 0 else {
            throw BridgeFailure.invalid("기존 파일은 보존했습니다. 내보낸 사본: " + staging.path)
        }
    }
    func cancel() { try? handle?.close(); handle = nil; try? FileManager.default.removeItem(at: staging) }
}

final class AppResources: NSObject, WKURLSchemeHandler {
    private let root: URL
    private let worker: WorkerBridge
    private var active: [ObjectIdentifier: String] = [:]
    init(root: URL, worker: WorkerBridge) { self.root = root.resolvingSymlinksInPath(); self.worker = worker }

    func webView(_ webView: WKWebView, start task: WKURLSchemeTask) {
        guard let url = task.request.url, AppResourcePolicy.trusted(url), ["GET", "HEAD"].contains(task.request.httpMethod ?? "GET") else {
            task.didFailWithError(BridgeFailure.invalid("허용하지 않은 자료 요청입니다.")); return
        }
        let key = ObjectIdentifier(task)
        active[key] = ""
        if url.path.hasPrefix("/api/") {
            var components = URLComponents(url: url, resolvingAgainstBaseURL: false)!
            components.scheme = nil; components.host = nil
            let path = components.string!
            guard AppResourcePolicy.resourcePath(path) else { fail(task, BridgeFailure.invalid("자료 경로를 확인하세요.")); return }
            var headers: [String: String] = [:]
            for name in ["Range", "If-Range"] { if let value = task.request.value(forHTTPHeaderField: name) { headers[name.lowercased()] = value } }
            let request = worker.request(["op":"http", "method":task.request.httpMethod ?? "GET", "path":path, "headers":headers]) { [weak self] header, body in
                guard let self = self, self.active[key] != nil else { return }
                switch header["event"] as? String {
                case "response_start":
                    var fields: [String: String] = [:]
                    for pair in header["headers"] as? [[String]] ?? [] where pair.count == 2 { fields[pair[0]] = pair[1] }
                    guard let response = HTTPURLResponse(url: url, statusCode: header["status"] as? Int ?? 500, httpVersion: "HTTP/1.1", headerFields: fields) else { throw BridgeFailure.invalid("자료 응답을 확인할 수 없습니다.") }
                    task.didReceive(response)
                case "body": task.didReceive(body)
                case "complete": self.active.removeValue(forKey: key); task.didFinish()
                case "error": self.fail(task, BridgeFailure.invalid(header["message"] as? String ?? "자료를 열 수 없습니다."))
                default: break
                }
            }
            if active[key] != nil { active[key] = request }
            return
        }
        let path = url.path == "/" ? "index.html" : String(url.path.dropFirst())
        let file = root.appendingPathComponent(path).resolvingSymlinksInPath()
        guard !url.path.contains("\\"), file.path.hasPrefix(root.path + "/"), FileManager.default.fileExists(atPath: file.path) else {
            fail(task, BridgeFailure.invalid("앱 화면 파일이 없습니다.")); return
        }
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                let size = try file.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
                let range = try AppResourcePolicy.byteRange(task.request.value(forHTTPHeaderField: "Range"), size: size)
                let partial = task.request.value(forHTTPHeaderField: "Range") != nil
                let mime = ["html":"text/html; charset=utf-8","js":"text/javascript; charset=utf-8","mjs":"text/javascript; charset=utf-8","css":"text/css; charset=utf-8","json":"application/json","svg":"image/svg+xml","png":"image/png","wav":"audio/wav","woff2":"font/woff2"][file.pathExtension.lowercased()] ?? UTType(filenameExtension:file.pathExtension)?.preferredMIMEType ?? "application/octet-stream"
                var headers = ["Content-Type":mime, "Content-Length":String(range.count), "Accept-Ranges":"bytes", "X-Content-Type-Options":"nosniff"]
                if file.pathExtension == "html" { headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; media-src 'self' blob:; object-src 'none'; frame-src 'none'; base-uri 'none'" }
                if partial { headers["Content-Range"] = "bytes \(range.lowerBound)-\(range.upperBound - 1)/\(size)" }
                let response = HTTPURLResponse(url: url, statusCode: partial ? 206 : 200, httpVersion: "HTTP/1.1", headerFields: headers)!
                var running = DispatchQueue.main.sync { () -> Bool in guard self.active[key] != nil else { return false }; task.didReceive(response); return true }
                if task.request.httpMethod != "HEAD", running {
                    let fileHandle = try FileHandle(forReadingFrom: file)
                    defer { try? fileHandle.close() }
                    try fileHandle.seek(toOffset: UInt64(range.lowerBound))
                    var remaining = range.count
                    while running && remaining > 0 {
                        let bytes = try fileHandle.read(upToCount: min(WorkerFrame.chunkLimit, remaining)) ?? Data()
                        guard !bytes.isEmpty else { throw BridgeFailure.invalid("앱 파일을 끝까지 읽을 수 없습니다.") }
                        remaining -= bytes.count
                        running = DispatchQueue.main.sync { guard self.active[key] != nil else { return false }; task.didReceive(bytes); return true }
                    }
                }
                DispatchQueue.main.async { if self.active.removeValue(forKey: key) != nil { task.didFinish() } }
            } catch { DispatchQueue.main.async { self.fail(task, error) } }
        }
    }

    func webView(_ webView: WKWebView, stop task: WKURLSchemeTask) {
        if let request = active.removeValue(forKey: ObjectIdentifier(task)), !request.isEmpty { worker.cancel(request) }
    }
    private func fail(_ task: WKURLSchemeTask, _ error: Error) {
        if active.removeValue(forKey: ObjectIdentifier(task)) != nil { task.didFailWithError(error) }
    }
}
