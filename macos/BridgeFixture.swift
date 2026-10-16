import Foundation

@main
struct BridgeFixture {
    static func main() throws {
        assert(AppResourcePolicy.trustedUI(URL(string: "solasi-app://app/")))
        assert(!AppResourcePolicy.trustedUI(URL(string: "solasi-app://app/api/courses")))
        assert(!AppResourcePolicy.trustedUI(URL(string: "solasi-app://evil/")))
        assert(!AppResourcePolicy.trustedUI(URL(string: "solasi-app://user@app/")))
        assert(AppResourcePolicy.validAPIPath("/api/courses?limit=10"))
        assert(!AppResourcePolicy.validAPIPath("/api/%2e%2e/secret"))
        assert(!AppResourcePolicy.validAPIPath("/api/client"))
        assert(!AppResourcePolicy.validAPIPath("https://example.org/api/courses"))
        assert(AppResourcePolicy.resourcePath("/api/recordings/" + String(repeating: "a", count: 32) + "/audio"))
        assert(!AppResourcePolicy.resourcePath("/api/provider"))
        let vault=String(repeating:"a",count:32),record=String(repeating:"b",count:32)
        let audio=URL(string:"solasi://audio/\(vault)/\(record)?start_ms=1000&end_ms=2000")!
        let link=AppResourcePolicy.audioLink(audio,vault:vault)
        assert(link?.id == record && link?.start == 1 && link?.end == 2)
        assert(AppResourcePolicy.audioLink(audio,vault:"other") == nil)
        assert(AppResourcePolicy.audioLink(URL(string:"solasi://audio/\(vault)/\(record)?start_ms=1000&start_ms=2000&end_ms=3000")!,vault:vault) == nil)
        assert(AppResourcePolicy.audioLink(URL(string:"solasi://audio/\(vault)/\(record)?start_ms=-1&end_ms=1000")!,vault:vault) == nil)
        let explicit = try AppResourcePolicy.byteRange("bytes=3-7", size: 20)
        let suffix = try AppResourcePolicy.byteRange("bytes=-5", size: 20)
        let tail = try AppResourcePolicy.byteRange("bytes=7-", size: 20)
        assert(explicit == 3..<8 && suffix == 15..<20 && tail == 7..<20)
        do { _ = try AppResourcePolicy.byteRange("bytes=30-40", size: 20); assertionFailure() } catch {}
        let frame = try WorkerFrame.encode(["id":"test", "op":"http", "path":"/api/courses"], body: Data("{}".utf8))
        var decoder = WorkerFrame()
        var frames: [([String: Any], Data)] = []
        for byte in frame { frames += try decoder.append(Data([byte])) }
        assert(frames.count == 1 && frames[0].0["id"] as? String == "test")
        assert(frames[0].1 == Data("{}".utf8))
        var malformed = WorkerFrame()
        do { _ = try malformed.append(Data([0xff, 0xff, 0xff, 0xff])); assertionFailure() } catch {}
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let destination = root.appendingPathComponent("note.txt")
        try Data("original".utf8).write(to: destination)
        let export = try ExclusiveExport(destination: destination)
        try export.append(Data("new".utf8))
        do { try export.finish(); assertionFailure() } catch {}
        let original = try Data(contentsOf: destination)
        assert(original == Data("original".utf8))
        export.cancel()
        let fresh = root.appendingPathComponent("new.txt")
        let saved = try ExclusiveExport(destination: fresh)
        try saved.append(Data("saved".utf8)); try saved.finish()
        let savedBytes = try Data(contentsOf: fresh)
        assert(savedBytes == Data("saved".utf8))
        let cancelled = try ExclusiveExport(destination: root.appendingPathComponent("cancelled.txt"))
        try cancelled.append(Data("partial".utf8)); cancelled.cancel()
        assert(!FileManager.default.fileExists(atPath: root.appendingPathComponent("cancelled.txt").path))
        print("Native bridge policy, framing, range and exclusive export fixtures passed")
    }
}
