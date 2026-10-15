import AppKit
import Foundation

let application = NSApplication.shared
application.setActivationPolicy(.regular)
let panel = NSOpenPanel()
panel.title = CommandLine.arguments.contains("audio") ? "녹음 파일 연결" : "자료 연결"
panel.canChooseDirectories = false
panel.canChooseFiles = true
panel.allowsMultipleSelection = true
panel.allowedFileTypes = CommandLine.arguments.contains("audio")
    ? ["wav","mp3","m4a","aac","flac","ogg","webm","mp4"]
    : ["pdf","png","jpg","jpeg","txt","md"]
application.finishLaunching()
application.activate(ignoringOtherApps: true)
let timer = Timer.scheduledTimer(withTimeInterval: 600, repeats: false) { _ in panel.cancel(nil) }
let paths = panel.runModal() == .OK ? panel.urls.map { $0.path } : []
timer.invalidate()
let data = try JSONSerialization.data(withJSONObject: ["paths":paths])
print(String(data: data, encoding: .utf8)!)
