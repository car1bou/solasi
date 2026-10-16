import AVFoundation
import Foundation
import UniformTypeIdentifiers

final class AudioResources: NSObject, AVAssetResourceLoaderDelegate {
    let worker:WorkerBridge
    var requests:[ObjectIdentifier:String]=[:]
    init(worker:WorkerBridge) { self.worker=worker }
    func resourceLoader(_ resourceLoader:AVAssetResourceLoader,shouldWaitForLoadingOfRequestedResource loading:AVAssetResourceLoadingRequest)->Bool {
        guard let url=loading.request.url,url.scheme == "solasi-media",url.host == "app",
              url.path.range(of:"^/api/recordings/[a-f0-9]{32}/audio$",options:.regularExpression) != nil else { return false }
        let key=ObjectIdentifier(loading),data=loading.dataRequest
        var headers:[String:String]=[:]
        if let data=data {
            let offset=max(data.requestedOffset,data.currentOffset)
            guard offset>=0 else { loading.finishLoading(with:BridgeFailure.invalid("음성 재생 범위를 확인하세요."));return true }
            if data.requestsAllDataToEndOfResource { headers["range"]="bytes=\(offset)-" }
            else {
                let (end,overflow)=data.requestedOffset.addingReportingOverflow(Int64(data.requestedLength))
                guard !overflow,end>offset else { loading.finishLoading(with:BridgeFailure.invalid("음성 재생 범위를 확인하세요.")); return true }
                headers["range"]="bytes=\(offset)-\(end-1)"
            }
        }
        requests[key]=""
        let id=worker.request(["op":"http","method":data == nil ? "HEAD" : "GET","path":url.path,"headers":headers]) { [weak self] header,bytes in
            guard let self=self,self.requests[key] != nil else { return }
            switch header["event"] as? String {
            case "response_start":
                guard [200,206].contains(header["status"] as? Int ?? 500) else { throw BridgeFailure.invalid("원음을 열 수 없습니다.") }
                var fields:[String:String]=[:]
                for pair in header["headers"] as? [[String]] ?? [] where pair.count == 2 { fields[pair[0].lowercased()]=pair[1] }
                if let info=loading.contentInformationRequest {
                    let mime=String((fields["content-type"] ?? "audio/wav").split(separator:";")[0])
                    info.contentType=["audio/wav","audio/x-wav","audio/vnd.wave"].contains(mime) ? UTType.wav.identifier : UTType(mimeType:mime)?.identifier ?? UTType.audio.identifier
                    let total=fields["content-range"]?.split(separator:"/").last.map(String.init) ?? fields["content-length"] ?? ""
                    guard let length=Int64(total),length>=0 else { throw BridgeFailure.invalid("원음 길이를 확인할 수 없습니다.") }
                    info.contentLength=length;info.isByteRangeAccessSupported=true
                }
            case "body": loading.dataRequest?.respond(with:bytes)
            case "complete": self.requests.removeValue(forKey:key);loading.finishLoading()
            case "error": self.requests.removeValue(forKey:key);loading.finishLoading(with:BridgeFailure.invalid(header["message"] as? String ?? "원음 읽기 실패"))
            default: break
            }
        }
        if requests[key] != nil { requests[key]=id }
        return true
    }
    func resourceLoader(_ resourceLoader:AVAssetResourceLoader,didCancel loading:AVAssetResourceLoadingRequest) {
        if let id=requests.removeValue(forKey:ObjectIdentifier(loading)) { worker.cancel(id) }
    }
    func close() { let active=Array(requests.values);requests.removeAll();active.forEach { worker.cancel($0) } }
}

final class AudioPlayback {
    let player:AVPlayer
    let resources:AudioResources
    private let event:([String:Any])->Void
    private var observations:[NSKeyValueObservation]=[]
    private var tick:Any?,ended:NSObjectProtocol?
    private var closed=false
    private var pendingSeeks:[UUID:(Error?)->Void]=[:]
    init(path:String,worker:WorkerBridge,event:@escaping ([String:Any])->Void) throws {
        guard path.range(of:"^/api/recordings/[a-f0-9]{32}/audio$",options:.regularExpression) != nil,
              let url=URL(string:"solasi-media://app"+path) else { throw BridgeFailure.invalid("원음 경로를 확인하세요.") }
        self.event=event;resources=AudioResources(worker:worker)
        let asset=AVURLAsset(url:url)
        asset.resourceLoader.setDelegate(resources,queue:.main)
        let item=AVPlayerItem(asset:asset);player=AVPlayer(playerItem:item)
        observations.append(item.observe(\.status,options:[.new]) { [weak self] _,_ in DispatchQueue.main.async { self?.publish() } })
        observations.append(player.observe(\.timeControlStatus,options:[.new]) { [weak self] _,_ in DispatchQueue.main.async { self?.publish() } })
        tick=player.addPeriodicTimeObserver(forInterval:CMTime(seconds:0.2,preferredTimescale:600),queue:.main) { [weak self] _ in self?.publish() }
        ended=NotificationCenter.default.addObserver(forName:.AVPlayerItemDidPlayToEndTime,object:item,queue:.main) { [weak self] _ in self?.publish(ended:true) }
    }
    func snapshot(ended:Bool=false,seeked:Bool=false)->[String:Any] {
        let duration=player.currentItem?.duration.seconds ?? 0,time=player.currentTime().seconds
        return ["ready":player.currentItem?.status == .readyToPlay,"duration":duration.isFinite ? duration : 0,"currentTime":time.isFinite ? time : 0,"paused":player.rate == 0,"ended":ended,"seeked":seeked,"error":player.currentItem?.error?.localizedDescription ?? ""]
    }
    func publish(ended:Bool=false,seeked:Bool=false) {
        guard !closed else { return };event(snapshot(ended:ended,seeked:seeked))
    }
    func seek(_ seconds:Double,completion:@escaping (Error?)->Void={ _ in }) throws {
        guard !closed,seconds.isFinite,seconds>=0 else { throw BridgeFailure.invalid("재생 시각을 확인하세요.") }
        let id=UUID();pendingSeeks[id]=completion
        func finish(_ error:Error?) {
            guard let callback=self.pendingSeeks.removeValue(forKey:id) else { return }
            if error == nil { self.publish(seeked:true) };callback(error)
        }
        player.seek(to:CMTime(seconds:seconds,preferredTimescale:1000),toleranceBefore:.zero,toleranceAfter:.zero) { finished in
            DispatchQueue.main.async { finish(finished ? nil : BridgeFailure.invalid("재생 위치 이동이 중단되었습니다.")) }
        }
        DispatchQueue.main.asyncAfter(deadline:.now()+10) {
            guard self.pendingSeeks[id] != nil else { return }
            self.player.currentItem?.cancelPendingSeeks()
            finish(BridgeFailure.invalid("원음 재생 위치를 준비하지 못했습니다. 다시 시도해 주세요."))
        }
    }
    func close() {
        guard !closed else { return };closed=true
        let pending=pendingSeeks;pendingSeeks.removeAll()
        pending.values.forEach { $0(BridgeFailure.invalid("원음 재생이 닫혔습니다.")) }
        player.pause();observations.forEach { $0.invalidate() };observations.removeAll()
        if let tick=tick { player.removeTimeObserver(tick) };tick=nil
        if let ended=ended { NotificationCenter.default.removeObserver(ended) };ended=nil
        player.replaceCurrentItem(with:nil);resources.close()
    }
}
