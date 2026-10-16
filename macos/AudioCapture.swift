import AppKit
import AVFoundation
import Foundation

struct PCMSequence {
    private var origin: Int64?
    private(set) var sequence: UInt64 = 0
    private(set) var end: UInt64 = 0
    mutating func packet(samples: [Float], sampleTime: Int64) throws -> Data {
        guard !samples.isEmpty, samples.count <= 192000 else { throw BridgeFailure.invalid("입력 프레임 길이를 확인하세요.") }
        origin = origin ?? sampleTime
        let (position,overflow) = sampleTime.subtractingReportingOverflow(origin!)
        guard !overflow, position >= 0, UInt64(position) >= end, position <= 9_007_199_254_740_991 - Int64(samples.count), sequence < 9_007_199_254_740_991 else { throw BridgeFailure.invalid("마이크 입력 시각이 바뀌었습니다.") }
        var seq = sequence.littleEndian, first = UInt64(position).littleEndian, count = UInt32(samples.count).littleEndian
        var data = withUnsafeBytes(of:&seq) { Data($0) }
        data += withUnsafeBytes(of:&first) { Data($0) }; data += withUnsafeBytes(of:&count) { Data($0) }
        for value in samples {
            let sample = value.isFinite ? max(-1,min(1,value)) : 0
            var pcm = Int16((sample * (sample < 0 ? 32768 : 32767)).rounded()).littleEndian
            withUnsafeBytes(of:&pcm) { data.append(contentsOf:$0) }
        }
        end = UInt64(position) + UInt64(samples.count); sequence += 1
        return data
    }
}

struct CaptureGuard {
    private(set) var finished = false
    private(set) var waiting = false
    private(set) var recovered = false
    var acceptsPermission: Bool { !finished }
    mutating func finish() { finished = true; waiting = false }
    mutating func waitForInput() { if !finished { waiting = true } }
    mutating func recoverOnFreshInput() -> Bool {
        guard !finished, waiting, !recovered else { return false }
        waiting = false; recovered = true; return true
    }
}

final class AudioCapture {
    let id: String
    private let session: String, mode: String, worker: WorkerBridge
    private let event: ([String: Any]) -> Void
    private let processing = DispatchQueue(label:"Solasi.audio.pcm",qos:.userInitiated)
    private let inputSlots = DispatchSemaphore(value:32)
    private var engine: AVAudioEngine?
    private var tapInstalled = false
    private var guardState = CaptureGuard()
    private var timeline = PCMSequence()
    private var rate = 0
    private var segmentRate = 0
    private var recordingID: String?, streamID: String?, packetID: String?
    private var deferredID:String?, deferredEnd:UInt64=0
    private var packets: [(data:Data,sequence:UInt64,frames:Int)] = []
    private var pendingFrames = 0, activePacketFrames = 0
    private var phase = "starting", error = ""
    private var recordedSeconds = 0.0
    private var lastInput = Date(), lastACK = Date(), lastTick = Date()
    private var sleeping = false, closing = false, opening = false, awaitingRecovery = false
    private var flushingInput = false
    private var stopCallbacks: [() -> Void] = []
    private var timer: Timer?, startup: DispatchWorkItem?
    private var observers: [(NotificationCenter, NSObjectProtocol)] = []

    init(id:String,session:String,mode:String,worker:WorkerBridge,event:@escaping ([String:Any])->Void) {
        self.id=id; self.session=session; self.mode=mode; self.worker=worker; self.event=event
    }
    private func publish() {
        event(["capture_id":id,"phase":phase,"seconds":recordedSeconds+(segmentRate>0 ? Double(timeline.end)/Double(segmentRate) : 0),"pending":rate>0 ? Double(pendingFrames+activePacketFrames)/Double(rate) : 0,"error":error,"recovered":guardState.recovered])
    }

    func start() {
        publish()
        armStartupDeadline()
        switch AVCaptureDevice.authorizationStatus(for:.audio) {
        case .authorized: permission(true)
        case .notDetermined: AVCaptureDevice.requestAccess(for:.audio) { allowed in DispatchQueue.main.async { self.permission(allowed) } }
        default: permission(false)
        }
    }

    private func armStartupDeadline() {
        startup?.cancel()
        let timeout = DispatchWorkItem { [weak self] in
            guard let self = self, !self.guardState.finished, self.phase == "starting" else { return }
            self.fail("마이크 준비 시간 초과 · 다시 시작", recoverable:false)
        }
        startup=timeout; DispatchQueue.main.asyncAfter(deadline:.now()+30,execute:timeout)
    }

    private func permission(_ allowed:Bool) {
        guard guardState.acceptsPermission else { return }
        guard allowed else { fail("마이크 접근이 허용되지 않았습니다. macOS 마이크 설정을 확인하세요.",recoverable:false); return }
        observe(NSWorkspace.shared.notificationCenter,NSWorkspace.willSleepNotification) { self.sleeping=true; self.fail("절전으로 녹음이 중단되었습니다",recoverable:true) }
        observe(NSWorkspace.shared.notificationCenter,NSWorkspace.didWakeNotification) {
            self.sleeping=false; self.lastTick=Date()
            if self.guardState.waiting { self.restartInputProbe() }
        }
        let configurationObserver=NotificationCenter.default.addObserver(forName:.AVAudioEngineConfigurationChange,object:nil,queue:.main) { notification in
            guard let engine=notification.object as? AVAudioEngine,engine === self.engine,
                  !self.closing,!self.opening,!self.guardState.waiting,!self.guardState.finished,self.phase == "recording" else { return }
            self.fail("마이크 입력 구성이 바뀌었습니다",recoverable:true)
            if !self.sleeping { self.restartInputProbe() }
        }
        observers.append((NotificationCenter.default,configurationObserver))
        timer=Timer.scheduledTimer(withTimeInterval:1,repeats:true) { [weak self] _ in self?.health() }
        if let timer=timer { RunLoop.main.add(timer,forMode:.common) }
        openSegment(resume:nil)
    }

    private func observe(_ center:NotificationCenter,_ name:Notification.Name,handler:@escaping ()->Void) {
        observers.append((center,center.addObserver(forName:name,object:nil,queue:.main) { _ in handler() }))
    }

    private func prepareEngine() throws {
        stopEngine()
        let next = AVAudioEngine()
        let input = next.inputNode, format=input.outputFormat(forBus:0)
        guard format.sampleRate >= 8000, format.sampleRate <= 192000, format.sampleRate.rounded() == format.sampleRate,
              format.channelCount > 0, format.channelCount <= 8, format.commonFormat == .pcmFormatFloat32 else { throw BridgeFailure.invalid("사용 가능한 마이크 입력을 찾지 못했습니다.") }
        rate=Int(format.sampleRate); engine=next
        input.installTap(onBus:0,bufferSize:4096,format:format) { [weak self, weak next] buffer, timestamp in
            guard let self = self, let next = next, timestamp.isSampleTimeValid, buffer.frameLength>0, let channels=buffer.floatChannelData else { return }
            guard self.inputSlots.wait(timeout:.now()) == .success else {
                DispatchQueue.main.async { self.fail("오디오 수집 대기 한도를 초과했습니다",recoverable:true) }; return
            }
            let count=Int(buffer.frameLength), channelCount=Int(buffer.format.channelCount), sampleTime=timestamp.sampleTime
            let copied: [[Float]]
            if buffer.format.isInterleaved { copied=(0..<channelCount).map { channel in (0..<count).map { channels[0][$0*channelCount+channel] } } }
            else { copied=(0..<channelCount).map { Array(UnsafeBufferPointer(start:channels[$0],count:count)) } }
            self.processing.async {
                var mono=Array(repeating:Float(0),count:count)
                for channel in copied { for index in 0..<count { mono[index] += channel[index]/Float(channelCount) } }
                DispatchQueue.main.async {
                    defer { self.inputSlots.signal() }
                    guard self.engine === next else { return }
                    self.received(mono,sampleTime:sampleTime)
                }
            }
        }
        tapInstalled=true
    }

    private func stopEngine() {
        if let engine=engine { if tapInstalled { engine.inputNode.removeTap(onBus:0); tapInstalled=false }; engine.stop() }
        engine=nil
    }

    private func flushInput(_ completion:@escaping ()->Void) {
        flushingInput=true
        if let engine=engine { if tapInstalled { engine.inputNode.removeTap(onBus:0);tapInstalled=false };engine.stop() }
        processing.async { DispatchQueue.main.async { self.engine=nil;self.flushingInput=false;completion() } }
    }

    private func openSegment(resume:String?) {
        guard !guardState.finished, !opening else { return }
        if resume != nil { armStartupDeadline() }
        opening=true
        do { try prepareEngine() } catch { opening=false; fail(error.localizedDescription,recoverable:false); return }
        let segmentRate=rate
        var body: [String:Any] = ["sample_rate":rate,"transcription_mode":mode]
        if let resume=resume { body["resume_from"]=resume }
        json("/api/sessions/"+session+"/audio/start",body:body) { result in
            switch result {
            case .failure(let failure):
                self.opening=false
                if self.guardState.finished { self.error=failure.localizedDescription; self.finishStop() }
                else { self.fail(failure.localizedDescription,recoverable:false) }
            case .success(let response):
                guard let rid=response["recording_id"] as? String else { self.opening=false; self.fail("녹음 식별자를 확인할 수 없습니다",recoverable:false); return }
                self.recordingID=rid; self.timeline=PCMSequence(); self.segmentRate=segmentRate
                if self.guardState.finished { self.opening=false; self.closeSegment(interrupted:true,deferred:false) { self.finishStop() }; return }
                var opened=""
                opened=self.worker.request(["op":"audio_open","session_id":self.session,"recording_id":rid,"sample_rate":segmentRate]) { header, _ in
                    guard ["complete","error"].contains(header["event"] as? String ?? "") else { return }
                    self.opening=false
                    if header["event"] as? String == "error" {
                        if self.guardState.finished { self.closeSegment(interrupted:true,deferred:false) { self.finishStop() } }
                        else { self.fail(header["message"] as? String ?? "녹음 저장 연결 실패",recoverable:false) }
                        return
                    }
                    self.streamID=opened
                    self.worker.observe(opened) { header, _ in
                        if let payload=header["payload"] as? [String:Any], payload["type"] as? String == "error" { self.fail(payload["error"] as? String ?? "원음 저장 실패",recoverable:payload["recoverable"] as? Bool ?? false) }
                    }
                    if self.guardState.finished { self.closeSegment(interrupted:true,deferred:false) { self.finishStop() }; return }
                    do { self.engine?.prepare(); try self.engine?.start(); self.lastInput=Date(); self.lastACK=Date(); self.lastTick=Date() }
                    catch { self.fail(error.localizedDescription,recoverable:false) }
                }
                DispatchQueue.main.asyncAfter(deadline:.now()+5) { if self.opening && self.recordingID == rid && self.streamID == nil { self.worker.cancel(opened,error:BridgeFailure.invalid("녹음 연결 시간 초과")) } }
            }
        }
    }

    private func received(_ samples:[Float],sampleTime:Int64) {
        guard !guardState.finished || flushingInput else { return }
        lastInput=Date()
        if guardState.waiting && !flushingInput {
            guard awaitingRecovery, !sleeping, !closing, !opening else { return }
            guard guardState.recoverOnFreshInput() else { fail("자동 복구 기회를 이미 사용했습니다",recoverable:false); return }
            awaitingRecovery=false
            recordedSeconds += segmentRate>0 ? Double(timeline.end)/Double(segmentRate) : 0
            timeline=PCMSequence(); phase="starting"
            openSegment(resume:recordingID); return
        }
        guard (!closing || flushingInput), streamID != nil else { return }
        guard samples.count+pendingFrames+activePacketFrames <= rate*10 else { fail("원음 저장 대기 한도를 초과했습니다",recoverable:true); return }
        do {
            let data=try timeline.packet(samples:samples,sampleTime:sampleTime)
            packets.append((data,timeline.sequence-1,samples.count)); pendingFrames += samples.count
            startup?.cancel(); sendNext(); publish()
        } catch { fail(error.localizedDescription,recoverable:true) }
    }

    private func sendNext() {
        guard packetID == nil, !packets.isEmpty, let stream=streamID else { return }
        let packet=packets.removeFirst(); pendingFrames -= packet.frames; activePacketFrames=packet.frames
        lastACK=Date()
        packetID=worker.request(["op":"audio_packet","stream_id":stream],body:packet.data) { header,_ in
            guard ["complete","error"].contains(header["event"] as? String ?? "") else { return }
            self.packetID=nil; self.activePacketFrames=0; self.lastACK=Date()
            guard header["event"] as? String == "complete", let ack=header["payload"] as? [String:Any],
                  ack["type"] as? String == "ack", (ack["seq"] as? NSNumber)?.uint64Value == packet.sequence,
                  ack["frame_count"] as? Int == packet.frames else {
                self.fail(header["message"] as? String ?? "원음 저장 응답 오류",recoverable:false); return
            }
            if !self.closing && !self.guardState.finished && !self.guardState.waiting { self.phase="recording"; self.error=""; self.publish() }
            self.sendNext()
        }
    }

    private func health() {
        guard !guardState.finished else { return }
        let now=Date(); defer { lastTick=now }
        guard !guardState.waiting, !closing, !opening else { return }
        if now.timeIntervalSince(lastTick)>10 || now<lastTick { fail("절전 또는 오디오 수집 중단 감지",recoverable:true) }
        else if packetID != nil && now.timeIntervalSince(lastACK)>5 { fail("원음 저장 확인이 지연됩니다",recoverable:true) }
        else if phase == "recording" && now.timeIntervalSince(lastInput)>5 { fail("오디오 입력이 도착하지 않습니다",recoverable:true) }
    }

    private func fail(_ reason:String,recoverable:Bool) {
        guard !guardState.finished else { return }
        if guardState.waiting && recoverable { return }
        error=reason
        if recoverable && !guardState.recovered && !opening {
            guardState.waitForInput(); phase="recovering"; publish()
            closeSegment(interrupted:true,deferred:mode == "after_stop") {
                guard !self.guardState.finished else { self.finishStop(); return }
                self.awaitingRecovery=true; self.error="오디오 복귀 대기 · 종료하면 받은 원음을 보존합니다"; self.publish()
                if !self.sleeping { self.restartInputProbe() }
            }
        } else { stop(interrupted:true,reason:reason) {} }
    }

    private func restartInputProbe() {
        guard guardState.waiting, !guardState.finished, !sleeping, awaitingRecovery else { return }
        // A fresh callback, not a wake notification, spends the one recovery attempt.
        do { try prepareEngine(); engine?.prepare(); try engine?.start() }
        catch { fail("마이크 복귀 실패 · "+error.localizedDescription,recoverable:false) }
    }

    private func closeSegment(interrupted:Bool,deferred:Bool,completion:@escaping ()->Void) {
        if closing { DispatchQueue.main.asyncAfter(deadline:.now()+0.05) { self.closeSegment(interrupted:interrupted,deferred:deferred,completion:completion) }; return }
        closing=true
        let deadline=Date().addingTimeInterval(3)
        func drain() {
            if (self.packetID != nil || !self.packets.isEmpty) && Date()<deadline {
                self.sendNext(); DispatchQueue.main.asyncAfter(deadline:.now()+0.025,execute:drain); return
            }
            let incomplete=self.packetID != nil || !self.packets.isEmpty
            if let request=self.packetID { self.worker.cancel(request); self.packetID=nil }
            self.packets.removeAll(); self.pendingFrames=0; self.activePacketFrames=0
            guard let rid=self.recordingID else { self.closing=false; completion(); return }
            let keepDeferred=deferred && !self.guardState.finished
            if keepDeferred { self.deferredID=rid;self.deferredEnd=self.timeline.end }
            var body: [String:Any] = ["end_frame":self.timeline.end,"interrupted":interrupted || incomplete,"defer_transcription":keepDeferred]
            if interrupted || incomplete { body["reason"]=String((self.error.isEmpty ? "원음 저장 확인 중단" : self.error).prefix(300)) }
            self.json("/api/recordings/"+rid+"/stop",body:body) { result in
                if case .failure(let error)=result { self.error=error.localizedDescription+" · 수신된 원음의 저장 상태를 확인하세요" }
                else if !keepDeferred && self.deferredID == rid { self.deferredID=nil }
                if let stream=self.streamID {
                    self.worker.unobserve(stream)
                    self.worker.request(["op":"audio_close","stream_id":stream]) { _,_ in }
                    self.streamID=nil
                }
                self.closing=false; completion()
            }
        }
        flushInput(drain)
    }

    func stop(interrupted:Bool=false,reason:String="",completion:@escaping ()->Void) {
        stopCallbacks.append(completion)
        if guardState.finished { if phase == "idle" { finishStop() }; return }
        guardState.finish(); startup?.cancel(); timer?.invalidate(); timer=nil
        if !reason.isEmpty { error=reason }
        phase="stopping"; publish()
        for (center,token) in observers { center.removeObserver(token) }; observers.removeAll()
        if opening { stopEngine(); return }
        closeSegment(interrupted:interrupted || !error.isEmpty,deferred:false) { self.finishStop() }
    }

    private func finishStop() {
        guard guardState.finished, !opening, !closing else { return }
        // Releasing a deferred recovery segment on explicit stop also releases its ASR work.
        if let rid=deferredID {
            deferredID=nil;awaitingRecovery=false
            json("/api/recordings/"+rid+"/stop",body:["interrupted":true,"defer_transcription":false,"end_frame":deferredEnd,"reason":String(error.prefix(300))]) { result in
                if case .failure(let error)=result { self.error=error.localizedDescription+" · 저장한 원음의 전사를 재시도하세요" }
                self.finishStop()
            }; return
        }
        phase="idle"; publish()
        let callbacks=stopCallbacks; stopCallbacks.removeAll(); callbacks.forEach { $0() }
    }

    private func json(_ path:String,body:[String:Any],completion:@escaping (Result<[String:Any],Error>)->Void) {
        do {
            let data=try JSONSerialization.data(withJSONObject:body), limit=1024*1024
            var bytes=Data(), status=500, done=false, request=""
            let timeout=DispatchWorkItem {
                guard !done else { return }; done=true
                self.worker.cancel(request); completion(.failure(BridgeFailure.invalid("녹음 저장·연결 시간 초과")))
            }
            request=worker.request(["op":"http","method":"POST","path":path],body:data) { header,chunk in
                guard !done else { return }
                switch header["event"] as? String {
                case "response_start": status=header["status"] as? Int ?? 500
                case "body": guard bytes.count+chunk.count<=limit else { throw BridgeFailure.invalid("녹음 응답 크기 오류") }; bytes.append(chunk)
                case "complete":
                    done=true; timeout.cancel()
                    do {
                        let result=try JSONSerialization.jsonObject(with:bytes) as? [String:Any] ?? [:]
                        guard (200..<300).contains(status) else { throw BridgeFailure.invalid(result["detail"] as? String ?? "녹음을 저장하지 못했습니다.") }
                        completion(.success(result))
                    } catch { completion(.failure(error)) }
                case "error": done=true; timeout.cancel(); completion(.failure(BridgeFailure.invalid(header["message"] as? String ?? "녹음 처리 실패")))
                default: break
                }
            }
            DispatchQueue.main.asyncAfter(deadline:.now()+5,execute:timeout)
        } catch { completion(.failure(error)) }
    }
}
