import AppKit
import Darwin
import Foundation

@main enum UninstallHelper {
    static func main() {
        let app = NSApplication.shared
        app.setActivationPolicy(.regular)
        let args = CommandLine.arguments
        var plan: RemovalPlan?
        var result = ""
        var success = false
        do {
            guard args.count == 6, args[1] == "--execute", let parent = Int32(args[4]), let worker = Int32(args[5]), parent > 1, worker > 1 else { throw RemovalError.invalid("최종 확인 정보가 없습니다") }
            let url = URL(fileURLWithPath: args[2])
            let loaded = try RemovalPlan.load(url,digest:args[3]); plan = loaded
            let deadline = Date().addingTimeInterval(40)
            while kill(parent,0) == 0 || kill(worker,0) == 0 || kill(-worker,0) == 0 {
                guard Date() < deadline else { throw RemovalError.invalid("앱·엔진 종료를 확인하지 못했습니다. 삭제를 실행하지 않았습니다.") }
                Thread.sleep(forTimeInterval:0.1)
            }
            try loaded.remove()
            success = true
            result = loaded.isReset ? "솔라시를 초기화했습니다. 앱은 유지했고 원래 보관함·설정·저장된 API 키·전용 모델과 추가 엔진을 제거했습니다. 모델과 추가 엔진은 설정에서 다시 준비하세요.\n보존 자료: \(loaded.receipt.directory)" : "솔라시와 전용 구성요소를 삭제했습니다.\n보존 자료: \(loaded.receipt.directory)"
            if !loaded.preserved.isEmpty { result += "\n별도 백업·실험 자료 등 소유권을 확인하지 못한 항목은 남겼습니다. 전체 경로의 모든 파일을 삭제한 상태는 아닙니다.\n"+loaded.preserved.prefix(10).joined(separator:"\n") }
        } catch { result = "초기화·삭제를 완료하지 못했습니다. 보존 자료는 유지됩니다. 일부 항목이 이미 삭제되었을 수 있습니다.\n"+error.localizedDescription }
        if let plan {
            let report = URL(fileURLWithPath:plan.receipt.directory).appendingPathComponent((plan.isReset ? "초기화 결과-" : "설치 삭제 결과-")+UUID().uuidString+".txt")
            let descriptor = Darwin.open(report.path,O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW,0o600)
            if descriptor >= 0 {
                let handle = FileHandle(fileDescriptor:descriptor,closeOnDealloc:true)
                do { try handle.write(contentsOf:Data((result+"\n\n보존된 기타 경로:\n"+plan.preserved.joined(separator:"\n")).utf8));try handle.synchronize() }
                catch { result += "\n삭제 결과 보고서 저장 실패: \(error.localizedDescription)" }
            } else { result += "\n삭제 결과 보고서를 저장하지 못했습니다." }
        }
        let alert = NSAlert(); alert.messageText = success ? (plan?.isReset == true ? "솔라시 초기화 결과" : "솔라시 설치 삭제 결과") : "솔라시 초기화·삭제 확인 필요"
        alert.informativeText = result; alert.addButton(withTitle:success && plan?.isReset == true ? "솔라시 다시 열기" : "닫기")
        if plan != nil { alert.addButton(withTitle:"보존 폴더 열기") }
        app.activate(ignoringOtherApps:true)
        let answer = alert.runModal()
        if answer == .alertSecondButtonReturn, let plan { NSWorkspace.shared.open(URL(fileURLWithPath:plan.receipt.directory)) }
        if answer == .alertFirstButtonReturn, success, let plan, plan.isReset { NSWorkspace.shared.open(URL(fileURLWithPath:plan.app)) }
        // The private plan/helper directory is created by the worker, never a caller's data folder.
        if args.count > 2 {
            let directory = URL(fileURLWithPath:args[2]).deletingLastPathComponent()
            if directory.lastPathComponent.hasPrefix("solasi-uninstall-"), directory.path.hasPrefix(FileManager.default.temporaryDirectory.resolvingSymlinksInPath().path) {
                try? FileManager.default.removeItem(at:directory)
            }
        }
    }
}
