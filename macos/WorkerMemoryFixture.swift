import Foundation
import Darwin

@main
final class WorkerMemoryFixture {
    let worker = WorkerBridge()
    var count = 0
    var baseline: UInt64 = 0

    static func main() throws {
        let fixture = WorkerMemoryFixture()
        try fixture.start()
        dispatchMain()
    }

    func residentBytes() -> UInt64 {
        var info = mach_task_basic_info()
        var size = mach_msg_type_number_t(MemoryLayout<mach_task_basic_info>.size / MemoryLayout<integer_t>.size)
        let result = withUnsafeMutablePointer(to: &info) {
            $0.withMemoryRebound(to: integer_t.self, capacity: Int(size)) {
                task_info(mach_task_self_, task_flavor_t(MACH_TASK_BASIC_INFO), $0, &size)
            }
        }
        precondition(result == KERN_SUCCESS)
        return info.resident_size
    }

    func start() throws {
        worker.ready = { self.send() }
        worker.terminated = { exit($0) }
        try worker.start(executable: URL(fileURLWithPath: CommandLine.arguments[1]), arguments: [CommandLine.arguments[2]], environment: ProcessInfo.processInfo.environment, log: FileHandle.standardError)
    }

    func send() {
        worker.request(["op": "audio_packet", "seq": count]) { header, _ in
            guard header["event"] as? String == "complete" else { exit(1) }
            self.count += 1
            if self.count == 500 { self.baseline = self.residentBytes() }
            if self.count < 5000 { self.send(); return }
            let final = self.residentBytes()
            print("Worker read memory baseline", self.baseline, "final", final)
            // Thousands of tiny ACKs must not retain a 16KiB availableData buffer each.
            guard final <= self.baseline + 24 * 1024 * 1024 else {
                self.worker.process.terminate()
                exit(1)
            }
            self.worker.shutdown()
        }
    }
}
