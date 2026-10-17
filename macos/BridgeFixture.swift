import Darwin
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
        let cancelledSelection = try ExclusiveExport.prepare(destination: nil).get()
        assert(cancelledSelection == nil)
        let missingParent = root.appendingPathComponent("missing-parent/new.json")
        switch ExclusiveExport.prepare(destination: missingParent) {
        case .success: assertionFailure("A failed export destination is not a user cancellation")
        case .failure(let error): assert((error as NSError).domain == NSPOSIXErrorDomain)
        }
        assert(!FileManager.default.fileExists(atPath: missingParent.path))
        let destination = root.appendingPathComponent("note.txt")
        try Data("original".utf8).write(to: destination)
        let export = try ExclusiveExport(destination: destination)
        try export.append(Data("new".utf8))
        do { try export.finish(); assertionFailure() } catch {}
        let original = try Data(contentsOf: destination)
        assert(original == Data("original".utf8))
        export.cancel()
        let fresh = root.appendingPathComponent("new.txt")
        guard let saved = try ExclusiveExport.prepare(destination: fresh).get() else { fatalError("A selected destination must prepare an export") }
        try saved.append(Data("saved".utf8)); try saved.finish()
        let savedBytes = try Data(contentsOf: fresh)
        assert(savedBytes == Data("saved".utf8))
        let cancelled = try ExclusiveExport(destination: root.appendingPathComponent("cancelled.txt"))
        try cancelled.append(Data("partial".utf8)); cancelled.cancel()
        assert(!FileManager.default.fileExists(atPath: root.appendingPathComponent("cancelled.txt").path))
        let failedWrite = try ExclusiveExport(destination: root.appendingPathComponent("failed-write.txt"))
        try failedWrite.append(Data("preserved prefix".utf8))
        var writeFailure: Error?
        do {
            var originalLimit = rlimit()
            guard getrlimit(RLIMIT_FSIZE, &originalLimit) == 0 else { throw BridgeFailure.invalid("Cannot read fixture file limit") }
            var writeLimit = originalLimit; writeLimit.rlim_cur = 0
            let originalSignal = signal(SIGXFSZ, SIG_IGN)
            defer { _ = setrlimit(RLIMIT_FSIZE, &originalLimit); _ = signal(SIGXFSZ, originalSignal) }
            guard setrlimit(RLIMIT_FSIZE, &writeLimit) == 0 else { throw BridgeFailure.invalid("Cannot set fixture file limit") }
            do { try failedWrite.append(Data("cannot append".utf8)); assertionFailure("A full export must fail") }
            catch { writeFailure = error }
        }
        assert(writeFailure?.localizedDescription.contains(failedWrite.staging.path) == true)
        let preservedPrefix = try Data(contentsOf: failedWrite.staging)
        assert(preservedPrefix == Data("preserved prefix".utf8))
        assert(!FileManager.default.fileExists(atPath: failedWrite.destination.path))
        let streaming = try ExclusiveExport(destination: root.appendingPathComponent("interrupted-stream.txt"))
        try streaming.append(Data("stream prefix".utf8))
        let streamFailure = streaming.preserveFailure(BridgeFailure.invalid("stream interrupted"))
        assert(streamFailure.localizedDescription.contains(streaming.staging.path))
        assert(streaming.preserveFailure(streamFailure).localizedDescription == streamFailure.localizedDescription)
        let preservedStream = try Data(contentsOf: streaming.staging)
        assert(preservedStream == Data("stream prefix".utf8))
        assert(!FileManager.default.fileExists(atPath: streaming.destination.path))
        print("Native bridge policy, framing, range and exclusive export fixtures passed")
    }
}
