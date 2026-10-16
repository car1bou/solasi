import Foundation
import Darwin

enum BridgeFailure: LocalizedError {
    case invalid(String)
    var errorDescription: String? { if case .invalid(let message) = self { return message }; return nil }
}

struct WorkerFrame {
    static let headerLimit = 64 * 1024
    static let requestLimit = 10 * 1024 * 1024
    static let chunkLimit = 256 * 1024
    private var buffer = Data()

    static func encode(_ fields: [String: Any], body: Data = Data()) throws -> Data {
        guard body.count <= requestLimit else { throw BridgeFailure.invalid("요청 크기를 초과했습니다.") }
        var header = fields
        header["version"] = 1; header["body_length"] = body.count
        let json = try JSONSerialization.data(withJSONObject: header)
        guard json.count <= headerLimit else { throw BridgeFailure.invalid("요청 헤더가 너무 큽니다.") }
        var length = UInt32(json.count).bigEndian
        return withUnsafeBytes(of: &length) { Data($0) } + json + body
    }

    mutating func append(_ data: Data) throws -> [([String: Any], Data)] {
        buffer.append(data)
        var frames: [([String: Any], Data)] = []
        while buffer.count >= 4 {
            let size = buffer.prefix(4).reduce(0) { ($0 << 8) | Int($1) }
            guard size > 0, size <= Self.headerLimit else { throw BridgeFailure.invalid("작업 엔진 헤더가 올바르지 않습니다.") }
            guard buffer.count >= 4 + size else { break }
            guard let header = try JSONSerialization.jsonObject(with: buffer.subdata(in: 4..<4 + size)) as? [String: Any],
                  header["version"] as? Int == 1, let id = header["id"] as? String,
                  id.range(of: "^[A-Za-z0-9_-]{1,64}$", options: .regularExpression) != nil,
                  let length = header["body_length"] as? Int, length >= 0, length <= Self.chunkLimit else {
                throw BridgeFailure.invalid("작업 엔진 프레임이 올바르지 않습니다.")
            }
            guard buffer.count >= 4 + size + length else { break }
            frames.append((header, buffer.subdata(in: 4 + size..<4 + size + length)))
            buffer.removeSubrange(0..<4 + size + length)
        }
        return frames
    }
}

final class WorkerBridge {
    typealias Receive = ([String: Any], Data) throws -> Void
    let process = Process()
    var ready: (() -> Void)?
    var terminated: ((Int32) -> Void)?
    private let input = Pipe(), output = Pipe()
    private let readQueue = DispatchQueue(label: "Solasi.worker.read")
    private let writeQueue = DispatchQueue(label: "Solasi.worker.write")
    private var callbacks: [String: Receive] = [:]
    private var sequences: [String: Int] = [:]
    private var observers: [String: Receive] = [:]
    private var closed = false
    private var shuttingDown = false
    private var shutdownDeadlines: [DispatchWorkItem] = []
    private var ownedGroup: pid_t?

    func start(executable: URL, arguments: [String], environment: [String: String], log: FileHandle?) throws {
        guard fcntl(input.fileHandleForWriting.fileDescriptor,F_SETNOSIGPIPE,1) == 0 else { throw BridgeFailure.invalid("작업 엔진 파이프를 준비할 수 없습니다.") }
        process.executableURL = executable
        process.arguments = arguments
        process.environment = environment
        process.standardInput = input; process.standardOutput = output; process.standardError = log
        process.terminationHandler = { [weak self] process in
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.closed = true
                self.shutdownDeadlines.forEach { $0.cancel() }; self.shutdownDeadlines.removeAll()
                let callbacks = self.callbacks; self.callbacks.removeAll(); self.sequences.removeAll()
                for (id, callback) in callbacks { try? callback(["id": id, "event":"error", "message":"작업 엔진이 종료되었습니다."], Data()) }
                self.finishTermination(process.terminationStatus)
            }
        }
        try process.run()
        readQueue.async { [weak self] in self?.read() }
    }

    private func read() {
        var decoder = WorkerFrame()
        do {
            while true {
                // This work item lives until EOF; release Foundation buffers after each read.
                let hasData = try autoreleasepool {
                    let bytes = output.fileHandleForReading.availableData
                    if bytes.isEmpty { return false }
                    for (header, body) in try decoder.append(bytes) {
                        // The worker waits for consumption ACK before sending another body chunk.
                        DispatchQueue.main.sync { self.received(header, body) }
                    }
                    return true
                }
                if !hasData { return }
            }
        } catch {
            DispatchQueue.main.async { if self.process.isRunning { self.process.terminate() } }
        }
    }

    private func received(_ header: [String: Any], _ body: Data) {
        guard let id = header["id"] as? String, let event = header["event"] as? String else { process.terminate(); return }
        if id == "worker", event == "ready" {
            let pid=process.processIdentifier
            guard header["process_group"] as? Int == Int(pid),getpgid(pid)==pid else { process.terminate();return }
            ownedGroup=pid;ready?();return
        }
        if event == "audio_event", let observer=observers[id] { try? observer(header,body); return }
        guard let callback = callbacks[id] else { return }
        if event == "body" {
            guard let sequence = header["sequence"] as? Int, sequence == sequences[id, default: 0] else { process.terminate(); return }
            sequences[id] = sequence + 1
        }
        if event == "complete" || event == "error" { callbacks.removeValue(forKey: id); sequences.removeValue(forKey: id) }
        do {
            try callback(header, body)
            if event == "body", callbacks[id] != nil { send(["id":UUID().uuidString,"op":"ack","target":id,"sequence":header["sequence"]!]) }
        } catch {
            if callbacks[id] != nil { cancel(id, error: error) }
            else { try? callback(["id":id,"event":"error","message":error.localizedDescription],Data()) }
        }
    }

    @discardableResult
    func request(_ fields: [String: Any], body: Data = Data(), receive: @escaping Receive) -> String {
        let id = UUID().uuidString
        guard !closed, !shuttingDown, process.isRunning, callbacks.count < 32 else {
            DispatchQueue.main.async { try? receive(["id":id,"event":"error","message":"처리 중인 요청이 많거나 작업 엔진이 종료되었습니다."],Data()) }; return id
        }
        var header = fields; header["id"] = id
        callbacks[id] = receive
        do { try write(WorkerFrame.encode(header, body: body)) }
        catch { callbacks.removeValue(forKey: id); DispatchQueue.main.async { try? receive(["id":id,"event":"error","message":error.localizedDescription],Data()) } }
        return id
    }

    private func send(_ fields: [String: Any]) {
        do { try write(WorkerFrame.encode(fields)) } catch { if process.isRunning { process.terminate() } }
    }

    private func write(_ bytes: Data) throws {
        guard !closed else { throw BridgeFailure.invalid("작업 엔진이 종료되었습니다.") }
        writeQueue.async {
            do { try self.input.fileHandleForWriting.write(contentsOf: bytes) }
            catch { DispatchQueue.main.async { if self.process.isRunning { self.process.terminate() } } }
        }
    }

    func cancel(_ id: String, error: Error? = nil) {
        let callback = callbacks.removeValue(forKey: id); sequences.removeValue(forKey: id)
        try? callback?(["id":id,"event":"error","message":error?.localizedDescription ?? "요청이 취소되었습니다."], Data())
        send(["id":UUID().uuidString,"op":"cancel","target":id])
    }

    func shutdown() {
        guard process.isRunning, !shuttingDown else { return }
        shuttingDown = true
        // The child may stop reading while a large request blocks the write queue.
        let terminate = DispatchWorkItem { [weak self] in
            guard let self = self, self.process.isRunning else { return }
            self.signalOwned(SIGTERM)
        }
        let kill = DispatchWorkItem { [weak self] in
            guard let self = self, self.process.isRunning else { return }
            self.signalOwned(SIGKILL)
        }
        shutdownDeadlines = [terminate, kill]
        DispatchQueue.main.asyncAfter(deadline: .now() + 9, execute: terminate)
        DispatchQueue.main.asyncAfter(deadline: .now() + 11, execute: kill)
        send(["id":UUID().uuidString,"op":"shutdown"])
    }
    private func signalOwned(_ signal:Int32) {
        if let group=ownedGroup { Darwin.kill(-group,signal) }
        else if process.isRunning { Darwin.kill(process.processIdentifier,signal) }
    }
    private func finishTermination(_ status:Int32) {
        guard let group=ownedGroup,Darwin.kill(-group,0)==0 else { terminated?(status);return }
        Darwin.kill(-group,SIGTERM)
        // Wait for owned model/resource-tracker children before allowing the app to quit.
        DispatchQueue.main.asyncAfter(deadline:.now()+2) {
            if Darwin.kill(-group,0)==0 { Darwin.kill(-group,SIGKILL) }
            self.terminated?(status)
        }
    }
    func observe(_ id:String,receive:@escaping Receive) { observers[id]=receive }
    func unobserve(_ id:String) { observers.removeValue(forKey:id) }
}
