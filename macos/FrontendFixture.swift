import AppKit
import WebKit

@main
final class FrontendFixture:NSObject,NSApplicationDelegate,WKNavigationDelegate,WKScriptMessageHandler,WKScriptMessageHandlerWithReply {
    let worker=WorkerBridge()
    var webView:WKWebView!,window:NSWindow!,root:URL!
    var diagnostics:[[String:Any]]=[],lastResult="",finished=false,uiReady=false
    var status:NSTextField?
    static func main(){let app=NSApplication.shared,delegate=FrontendFixture();app.delegate=delegate;app.run()}
    func applicationDidFinishLaunching(_ notification:Notification){
        do{
            guard CommandLine.arguments.count>=4 else {fatalError("frontend root, python, checkout required")}
            root=FileManager.default.temporaryDirectory.appendingPathComponent("solasi-frontend-"+UUID().uuidString)
            try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
            let configuration=WKWebViewConfiguration();configuration.websiteDataStore = .nonPersistent()
            configuration.setURLSchemeHandler(AppResources(root:URL(fileURLWithPath:CommandLine.arguments[1]),worker:worker),forURLScheme:"solasi-app")
            configuration.userContentController.add(self,name:"fixture")
            configuration.userContentController.addScriptMessageHandler(self,contentWorld:.page,name:"solasi")
            configuration.userContentController.addUserScript(WKUserScript(source:"""
                window.fixtureErrors=[];
                function report(kind,detail){window.fixtureErrors.push({kind,detail});window.webkit.messageHandlers.fixture.postMessage({kind,detail});}
                window.addEventListener('error',event=>report('error',event.error?.stack||event.message||event.target?.src||'resource'),true);
                window.addEventListener('unhandledrejection',event=>report('unhandledrejection',event.reason?.stack||String(event.reason)));
                window.addEventListener('securitypolicyviolation',event=>report('csp',event.violatedDirective+' '+event.blockedURI));
                for(const method of ['warn','error']){const original=console[method];console[method]=(...args)=>{report('console.'+method,args.map(value=>String(value)).join(' ').slice(0,1000));original.apply(console,args);};}
                """,injectionTime:.atDocumentStart,forMainFrameOnly:true))
            let stack=CommandLine.arguments.contains("--stack")
            webView=WKWebView(frame:stack ? .zero:NSRect(x:0,y:0,width:680,height:600),configuration:configuration);webView.navigationDelegate=self
            window=NSWindow(contentRect:NSRect(x:0,y:0,width:680,height:600),styleMask:[.titled,.closable,.miniaturizable,.resizable,.fullSizeContentView],backing:.buffered,defer:false)
            window.title="Solasi Frontend Fixture";window.titleVisibility = .hidden;window.titlebarAppearsTransparent=true;window.titlebarSeparatorStyle = .none;window.minSize=NSSize(width:680,height:480);window.isReleasedWhenClosed=false
            if stack{
                let status=NSTextField(wrappingLabelWithString:"기록을 준비하고 있습니다…"),retry=NSButton(title:"화면 다시 열기",target:nil,action:nil)
                self.status=status
                let notice=NSStackView(views:[status,retry]);notice.orientation = .horizontal;notice.spacing=12;notice.edgeInsets=NSEdgeInsets(top:32,left:12,bottom:8,right:12)
                status.setContentCompressionResistancePriority(.defaultLow,for:.horizontal);retry.isHidden=true
                let content=NSStackView(views:[notice,webView]);content.orientation = .vertical;content.alignment = .leading;content.spacing=0;content.distribution = .fill
                window.contentView=content;webView.translatesAutoresizingMaskIntoConstraints=false
                NSLayoutConstraint.activate([notice.widthAnchor.constraint(equalTo:content.widthAnchor),status.topAnchor.constraint(equalTo:notice.topAnchor,constant:32),status.bottomAnchor.constraint(lessThanOrEqualTo:notice.bottomAnchor,constant:-8),webView.widthAnchor.constraint(equalTo:content.widthAnchor),webView.heightAnchor.constraint(greaterThanOrEqualToConstant:200)])
            }else{window.contentView=webView}
            window.center();window.makeKeyAndOrderFront(nil)
            var environment=ProcessInfo.processInfo.environment;environment["PYTHONPATH"]=CommandLine.arguments[3];environment["PYTHONDONTWRITEBYTECODE"]="1";environment["SOLASI_OWNER_PID"]=String(getpid())
            worker.ready={self.webView.load(URLRequest(url:URL(string:"solasi-app://app/")!))}
            worker.terminated={status in if self.finished {try? FileManager.default.removeItem(at:self.root);exit(status==0 ? 0:1)} else {self.finish("worker terminated \(status)",success:false)}}
            try worker.start(executable:URL(fileURLWithPath:CommandLine.arguments[2]),arguments:["-m","lecture_study.native_worker","--data-dir",root.path,"--runtime-dir",root.appendingPathComponent("runtime").path],environment:environment,log:FileHandle.standardError)
            DispatchQueue.main.asyncAfter(deadline:.now()+30){self.finish("timeout "+self.lastResult,success:false)}
        }catch{finish(error.localizedDescription,success:false)}
    }
    func userContentController(_ userContentController:WKUserContentController,didReceive message:WKScriptMessage){
        if let value=message.body as? [String:Any]{diagnostics.append(value);print("DIAGNOSTIC",value)}
    }
    func userContentController(_ userContentController:WKUserContentController,didReceive message:WKScriptMessage,replyHandler:@escaping (Any?,String?)->Void){
        let origin=message.frameInfo.securityOrigin
        print("BRIDGE_ORIGIN",origin.protocol,origin.host,origin.port,"main",message.frameInfo.isMainFrame,"url",message.webView?.url?.absoluteString ?? "nil")
        guard message.frameInfo.isMainFrame,origin.protocol=="solasi-app",origin.host=="app",origin.port==0,AppResourcePolicy.trustedUI(message.webView?.url) else {replyHandler(nil,"허용하지 않은 앱 요청입니다.");return}
        guard let body=message.body as? [String:Any],let op=body["op"] as? String else {replyHandler(nil,"invalid fixture request");return}
        if op=="ui_ready" {uiReady=true;print("UI_READY");replyHandler(["ready":true],nil);return}
        guard op=="http",let path=body["path"] as? String else {replyHandler(nil,"unsupported fixture operation");return}
        print("API",path)
        var bytes=Data(),status=0
        worker.request(["op":"http","method":body["method"] as? String ?? "GET","path":path],body:Data((body["body"] as? String ?? "").utf8)){header,chunk in
            switch header["event"] as? String{
            case "response_start":status=header["status"] as? Int ?? 0
            case "body":bytes.append(chunk)
            case "complete":replyHandler(["status":status,"text":String(decoding:bytes,as:UTF8.self)],nil)
            case "error":replyHandler(nil,header["message"] as? String ?? "worker request error")
            default:break
            }
        }
    }
    func webView(_ webView:WKWebView,didFinish navigation:WKNavigation!){status?.stringValue="";status?.superview?.isHidden=true;check()}
    func check(){
        DispatchQueue.main.asyncAfter(deadline:.now()+1){
            self.webView.evaluateJavaScript("JSON.stringify({url:location.href,textLength:document.body.innerText.length,children:document.getElementById('root')?.childElementCount,root:document.getElementById('root')?.getBoundingClientRect().toJSON(),window:[innerWidth,innerHeight],errors:window.fixtureErrors,uuid:typeof crypto.randomUUID,subtle:typeof crypto.subtle,secure:isSecureContext})"){result,error in
                guard !self.finished else{return}
                guard let result=result as? String,error==nil else{self.finish(error?.localizedDescription ?? String(describing:result),success:false);return}
                self.lastResult=result
                print("NATIVE_FRAME",self.webView.frame,"window",self.window.contentView!.frame,"hidden",self.webView.isHiddenOrHasHiddenAncestor)
                guard let bytes=result.data(using:.utf8),let value=try? JSONSerialization.jsonObject(with:bytes) as? [String:Any] else{self.finish(result,success:false);return}
                if self.uiReady,(value["children"] as? Int ?? 0)>0,self.webView.frame.height>=200 {self.finish(result,success:self.diagnostics.isEmpty);return}
                if !self.diagnostics.isEmpty {self.finish(result,success:false);return}
                self.check()
            }
        }
    }
    func webView(_ webView:WKWebView,didFailProvisionalNavigation navigation:WKNavigation!,withError error:Error){finish(error.localizedDescription,success:false)}
    func finish(_ message:String,success:Bool){
        guard !finished else{return};finished=true;print(success ? "FRONTEND_PASS":"FRONTEND_FAIL",message)
        if !success {worker.terminated={_ in exit(1)}}
        if worker.process.isRunning {worker.shutdown()} else {exit(success ? 0:1)}
    }
}
