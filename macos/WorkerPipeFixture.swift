import Foundation
import Darwin

@main
final class WorkerPipeFixture {
    let worker=WorkerBridge()
    let directory=FileManager.default.temporaryDirectory.appendingPathComponent("solasi-pipe-"+UUID().uuidString)
    var recording="",stream=""
    var playback:AudioPlayback?
    var seeking=false
    var timeline=PCMSequence()
    static func main() throws {
        let fixture=WorkerPipeFixture()
        try fixture.start()
        dispatchMain()
    }
    func start() throws {
        guard CommandLine.arguments.count == 3 else { fatalError("python and checkout arguments required") }
        let source=CommandLine.arguments[2]
        try FileManager.default.createDirectory(at:directory,withIntermediateDirectories:true)
        var env=ProcessInfo.processInfo.environment;env["PYTHONPATH"]=source;env["PYTHONDONTWRITEBYTECODE"]="1"
        worker.ready={ self.json("/api/sessions",["title":"Pipe fixture","kind":"lecture"]) { session in
            self.json("/api/sessions/"+(session["id"] as! String)+"/audio/start",["sample_rate":8000,"transcription_mode":"after_stop"]) { record in
                self.recording=record["recording_id"] as! String
                self.stream=self.worker.request(["op":"audio_open","session_id":session["id"]!,"recording_id":self.recording,"sample_rate":8000]) { header,_ in
                    if header["event"] as? String == "error" { self.fail(header) }
                    if header["event"] as? String == "complete" { self.sendAudio() }
                }
            }
        } }
        worker.terminated={ status in
            do {
                let wave=try Data(contentsOf:self.directory.appendingPathComponent("audio/"+self.recording+"/raw.wav"))
                guard status == 0, wave.count == 9_600_044, wave.dropFirst(44).allSatisfy({$0 == 0}) else { self.fail(["error":"WAV contents or worker shutdown mismatch","exit":status,"bytes":wave.count]); return }
                print("Swift pipe → ASGI recording → durable PCM ACK → graceful shutdown: 4,800,000 silent frames (10 minutes) preserved")
                try? FileManager.default.removeItem(at:self.directory); exit(0)
            } catch { self.fail(["error":error.localizedDescription]) }
        }
        try worker.start(executable:URL(fileURLWithPath:CommandLine.arguments[1]),arguments:["-m","lecture_study.native_worker","--data-dir",directory.path,"--runtime-dir",directory.appendingPathComponent("runtime").path],environment:env,log:FileHandle.standardError)
        DispatchQueue.main.asyncAfter(deadline:.now()+60) { self.fail(["error":"pipe fixture timeout"]) }
    }
    func sendAudio() {
        do {
            let sequence=timeline.sequence
            let packet=try timeline.packet(samples:Array(repeating:Float(0),count:8000),sampleTime:100+Int64(timeline.end))
            worker.request(["op":"audio_packet","stream_id":stream],body:packet) { header,_ in
                if header["event"] as? String == "error" { self.fail(header) }
                if header["event"] as? String == "complete" {
                    guard let ack=header["payload"] as? [String:Any],ack["frame_count"] as? Int == 8000,(ack["seq"] as? NSNumber)?.uint64Value == sequence else { self.fail(header); return }
                    if self.timeline.sequence < 600 { self.sendAudio();return }
                    self.json("/api/recordings/"+self.recording+"/stop",["end_frame":4_800_000,"defer_transcription":true]) { _ in self.checkPlayback() }
                }
            }
        } catch { fail(["error":error.localizedDescription]) }
    }
    func checkPlayback() {
        do {
            playback=try AudioPlayback(path:"/api/recordings/"+recording+"/audio",worker:worker) { state in
                if let error=state["error"] as? String,!error.isEmpty { self.fail(state) }
                if state["ready"] as? Bool == true && !self.seeking {
                    self.seeking=true
                    do { try self.playback?.seek(599) } catch { self.fail(["error":error.localizedDescription]) }
                }
                if state["seeked"] as? Bool == true {
                    guard abs((state["currentTime"] as? Double ?? 0)-599)<0.05,abs((state["duration"] as? Double ?? 0)-600)<0.01 else { self.fail(state);return }
                    print("Native AVPlayer loaded 10-minute worker Range resource and sought to 599 seconds")
                    self.playback?.close();self.worker.shutdown()
                }
            }
        } catch { fail(["error":error.localizedDescription]) }
    }
    func json(_ path:String,_ body:[String:Any],completion:@escaping ([String:Any])->Void) {
        var data=Data(),status=0
        worker.request(["op":"http","method":"POST","path":path],body:try! JSONSerialization.data(withJSONObject:body)) { header,chunk in
            switch header["event"] as? String {
            case "response_start": status=header["status"] as? Int ?? 0
            case "body": data.append(chunk)
            case "error": self.fail(header)
            case "complete":
                guard (200..<300).contains(status),let value=try JSONSerialization.jsonObject(with:data) as? [String:Any] else { self.fail(["status":status,"body":String(decoding:data,as:UTF8.self)]); return }
                completion(value)
            default: break
            }
        }
    }
    func fail(_ detail:[String:Any]) { print(detail); if worker.process.isRunning { worker.process.terminate() }; exit(1) }
}
