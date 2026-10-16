import Darwin

enum BridgeFailure: LocalizedError {
    case invalid(String)
    var errorDescription: String? {
        if case .invalid(let value) = self { return value }
        return nil
    }
}

final class WorkerBridge {
    typealias Receive = ([String: Any], Data) throws -> Void
    private var pending: [String: Receive] = [:]
    private var cancelled: Receive?
    private(set) var cancellations = 0

    @discardableResult
    func request(_ fields: [String: Any], body: Data = Data(), receive: @escaping Receive) -> String {
        let id = UUID().uuidString
        if fields["op"] as? String == "audio_packet" {
            pending[id] = receive
            return id
        }
        DispatchQueue.main.async {
            if fields["op"] as? String == "http" {
                try? receive(["event": "response_start", "status": 200], Data())
                try? receive(["event": "body"], Data("{}".utf8))
            }
            try? receive(["event": "complete"], Data())
        }
        return id
    }

    func cancel(_ id: String, error: Error? = nil) {
        cancellations += 1
        cancelled = pending.removeValue(forKey: id)
        // WorkerBridge.cancel reports cancellation synchronously, before returning.
        try? cancelled?(["event": "error", "message": "Request cancelled"], Data())
    }

    func lateACK() {
        try? cancelled?(["event": "complete", "payload": ["type": "ack", "seq": 0, "frame_count": 4096]], Data())
    }

    func observe(_ id: String, receive: @escaping Receive) {}
    func unobserve(_ id: String) {}
}

// The runner joins this fixture to the real source so this extension can inspect private state.
extension AudioCapture {
    static func verifyRecovery() {
        let worker = WorkerBridge()
        let capture = AudioCapture(id: UUID().uuidString, session: String(repeating: "a", count: 32), mode: "after_stop", worker: worker, event: { _ in })
        capture.rate = 48000
        capture.segmentRate = 48000
        capture.recordingID = String(repeating: "b", count: 32)
        capture.streamID = "fixture"
        capture.phase = "recording"
        capture.sleeping = true
        capture.received(Array(repeating: 0, count: 4096), sampleTime: 100)
        capture.fail("절전으로 녹음이 중단되었습니다", recoverable: true)
        DispatchQueue.main.asyncAfter(deadline: .now() + 3.7) {
            guard worker.cancellations == 1, !capture.guardState.finished, capture.guardState.waiting,
                  capture.awaitingRecovery, capture.phase == "recovering" else {
                print("Recovery lost after drain cancellation:", worker.cancellations, capture.guardState.finished, capture.guardState.waiting, capture.awaitingRecovery, capture.phase)
                exit(1)
            }
            capture.packetID = "later-request"
            capture.activePacketFrames = 4096
            worker.lateACK()
            guard capture.packetID == "later-request", capture.activePacketFrames == 4096,
                  capture.guardState.waiting, capture.phase == "recovering" else {
                print("Stale packet ACK changed a later request or recovery state")
                exit(1)
            }
            capture.packetID = nil
            capture.activePacketFrames = 0
            capture.stop {
                print("Native pending ACK cancellation preserves recovery; stale ACK ignored; explicit stop completes")
                exit(0)
            }
        }
    }
}

@main
struct AudioRecoveryFixture {
    static func main() {
        AudioCapture.verifyRecovery()
        dispatchMain()
    }
}
