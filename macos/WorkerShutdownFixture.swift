import Foundation
import Darwin

@main
struct WorkerShutdownFixture {
    static func main() throws {
        let arguments=CommandLine.arguments
        if arguments.count>1,arguments[1]=="blocked" {
            guard setpgid(0,0)==0 else { fatalError("fixture process group failed") }
            signal(SIGTERM,SIG_IGN)
            let descendant=Process()
            descendant.executableURL=URL(fileURLWithPath:arguments[0]);descendant.arguments=["descendant",arguments[2]]
            try descendant.run()
            try FileHandle.standardOutput.write(contentsOf:WorkerFrame.encode(["id":"worker","event":"ready","process_group":Int(getpgrp())]))
            while true { Thread.sleep(forTimeInterval:1) }
        }
        if arguments.count>1,arguments[1]=="descendant" {
            // Foundation Process creates a new group; Python model children inherit it.
            guard setpgid(0,getppid())==0 else { fatalError("fixture descendant group failed") }
            signal(SIGTERM,SIG_IGN)
            try String(getpid()).write(toFile:arguments[2],atomically:true,encoding:.utf8)
            while true { Thread.sleep(forTimeInterval:1) }
        }
        let path=FileManager.default.temporaryDirectory.appendingPathComponent("solasi-shutdown-"+UUID().uuidString)
        let worker=WorkerBridge(),started=Date()
        var failedRequests=0
        worker.ready={
            worker.request(["op":"http","path":"/api/fixture"],body:Data(repeating:0,count:WorkerFrame.requestLimit)) { header,_ in
                if header["event"] as? String=="error" { failedRequests+=1 }
            }
            worker.shutdown();worker.shutdown()
            worker.request(["op":"http","path":"/api/fixture"]) { header,_ in
                assert(header["event"] as? String=="error");failedRequests+=1
            }
        }
        worker.terminated={ status in
            assert(status==SIGKILL);assert(!worker.process.isRunning);assert(failedRequests==2)
            assert(Date().timeIntervalSince(started)<16)
            let child=pid_t(try! String(contentsOf:path,encoding:.utf8).trimmingCharacters(in:.whitespacesAndNewlines))!
            assert(Darwin.kill(child,0) == -1 && errno==ESRCH,"Owned model fixture survived worker shutdown")
            try? FileManager.default.removeItem(at:path)
            print("Blocked pipe shutdown, request rejection, SIGTERM/SIGKILL and owned descendant cleanup passed")
            exit(0)
        }
        try worker.start(executable:URL(fileURLWithPath:arguments[0]),arguments:["blocked",path.path],environment:ProcessInfo.processInfo.environment,log:FileHandle.standardError)
        DispatchQueue.main.asyncAfter(deadline:.now()+18) {
            Darwin.kill(-worker.process.processIdentifier,SIGKILL)
            fputs("Worker shutdown fixture timed out\n",stderr);exit(1)
        }
        dispatchMain()
    }
}
