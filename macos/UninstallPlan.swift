import Foundation
import CryptoKit
import Darwin
import Security

enum RemovalError: LocalizedError {
    case invalid(String)
    case missing(String)
    var errorDescription: String? { switch self { case .invalid(let text), .missing(let text): return text } }
}

struct RemovalProof: Decodable { let bytes: Int64; let sha256: String }
struct RemovalFile: Decodable { let path: String; let bytes: Int64; let sha256: String }
struct RemovalReceipt: Decodable {
    let directory: String
    let selection: [String:Bool]
    let directory_identity: [UInt64]
    let files: [RemovalFile]
    let manifest: String
    let manifest_sha256: String
}
struct RemovalEntry: Decodable {
    let name: String
    let device: UInt64
    let inode: UInt64
    let kind: String
    let bytes: Int64
    let mtime: Int64
}
struct RemovalTarget: Decodable {
    let path: String
    let device: UInt64
    let inode: UInt64
    let mutable: Bool
    let entries: [RemovalEntry]
}

func removalParent(_ path: String) throws -> (Int32, String) {
    let url = URL(fileURLWithPath: path)
    guard path.hasPrefix("/"), !path.contains("//"), !path.split(separator:"/").contains(where: { $0 == "." || $0 == ".." }), !path.contains("\0"), path != "/" else { throw RemovalError.invalid("삭제 경로 오류") }
    var descriptor = Darwin.open("/", O_RDONLY | O_DIRECTORY | O_CLOEXEC)
    guard descriptor >= 0 else { throw RemovalError.invalid("삭제 경로 접근 실패") }
    for part in url.deletingLastPathComponent().pathComponents.dropFirst() {
        let child = openat(descriptor, part, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        Darwin.close(descriptor)
        guard child >= 0 else {
            if errno == ENOENT { throw RemovalError.missing("삭제 경로가 없습니다: \(path)") }
            throw RemovalError.invalid("삭제 경로가 바뀌었거나 연결 경로입니다: \(path)")
        }
        descriptor = child
    }
    return (descriptor, url.lastPathComponent)
}

func optionalRemovalParent(_ path: String) throws -> (Int32,String)? {
    do { return try removalParent(path) }
    catch RemovalError.missing { return nil }
}

func removalSelectionSummary(_ selection: [String:Bool]) -> String {
    let categories = [("documents","필기·문서"),("audio","녹음"),("results","전사·AI 결과")]
    let kept = categories.filter{selection[$0.0] == true}.map{$0.1}
    let lost = categories.filter{selection[$0.0] != true}.map{$0.1}
    return "보존: " + (kept.isEmpty ? "없음" : kept.joined(separator:", ")) + "\n미보존·삭제: " + (lost.isEmpty ? "없음" : lost.joined(separator:", "))
}

func removalHash(_ path: String) throws -> (Int64, String) {
    let (parent, name) = try removalParent(path); defer { Darwin.close(parent) }
    let descriptor = openat(parent, name, O_RDONLY | O_NOFOLLOW | O_CLOEXEC)
    guard descriptor >= 0 else { throw RemovalError.invalid("파일 읽기 실패: \(path)") }
    let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
    var before = stat(); guard fstat(descriptor, &before) == 0, (before.st_mode & S_IFMT) == S_IFREG else { throw RemovalError.invalid("일반 파일이 아닙니다: \(path)") }
    var digest = SHA256()
    while let chunk = try handle.read(upToCount: 1024*1024), !chunk.isEmpty { digest.update(data: chunk) }
    var after = stat(); guard fstat(descriptor, &after) == 0, before.st_ino == after.st_ino, before.st_size == after.st_size,
        before.st_mtimespec.tv_sec == after.st_mtimespec.tv_sec, before.st_mtimespec.tv_nsec == after.st_mtimespec.tv_nsec else { throw RemovalError.invalid("검증 중 파일 변경: \(path)") }
    return (Int64(after.st_size), digest.finalize().map { String(format: "%02x", $0) }.joined())
}

struct RemovalPlan: Decodable {
    let format: Int
    let operation: String?
    var isReset: Bool { operation == "reset" }
    let app, data, runtime, bundle_id, service: String
    let receipt: RemovalReceipt
    let database_proof: RemovalProof
    let os_paths: [String]?
    let targets: [RemovalTarget]
    let preserved: [String]
    let bytes: Int64

    static func load(_ url: URL, digest: String) throws -> RemovalPlan {
        var info = stat()
        guard lstat(url.path, &info) == 0, info.st_uid == getuid(), (info.st_mode & S_IFMT) == S_IFREG,
              info.st_mode & 0o077 == 0, try removalHash(url.path).1 == digest else { throw RemovalError.invalid("최종 확인한 삭제 계획이 아닙니다") }
        return try JSONDecoder().decode(Self.self, from: Data(contentsOf: url))
    }

    static func prepareReset(_ url: URL, digest: String) throws -> String {
        let original = try load(url,digest:digest)
        try original.validate()
        var value = try JSONSerialization.jsonObject(with:Data(contentsOf:url)) as! [String:Any]
        value["operation"] = "reset"
        value["bytes"] = original.targets.filter { $0.path != original.app }.flatMap(\.entries).filter { $0.kind == "file" }.reduce(Int64(0)) { $0 + $1.bytes }
        try JSONSerialization.data(withJSONObject:value,options:[.sortedKeys]).write(to:url,options:.atomic)
        try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:url.path)
        return try removalHash(url.path).1
    }

    private func rootInfo(_ target: RemovalTarget) throws -> stat? {
        let (parent,name) = try removalParent(target.path); defer { Darwin.close(parent) }
        var value = stat()
        if fstatat(parent, name, &value, AT_SYMLINK_NOFOLLOW) != 0 {
            if errno == ENOENT && [data+"/app.sqlite3-wal",data+"/app.sqlite3-shm"].contains(target.path) { return nil }
            throw RemovalError.invalid("삭제 대상 접근 실패: \(target.path)")
        }
        let volatile = target.mutable && target.path.hasPrefix(FileManager.default.homeDirectoryForCurrentUser.path+"/Library/")
        guard (volatile || UInt64(value.st_dev) == target.device && UInt64(value.st_ino) == target.inode),
              value.st_uid == getuid(), (value.st_mode & S_IFMT != S_IFLNK || target.entries.first?.kind == "link") else { throw RemovalError.invalid("삭제 대상이 바뀌었습니다: \(target.path)") }
        return value
    }

    func validate() throws {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        guard format == 1, (operation == nil || operation == "reset"), ["local.solasi.launcher", "local.solasi.internal-validation"].contains(bundle_id), app.hasSuffix(".app"),
              targets.last?.path == app, Set(targets.map(\.path)).count == targets.count,
              !["/",home,home+"/Library"].contains(data), !["/",home,home+"/Library"].contains(runtime),
              service == "LectureStudy:" + SHA256.hash(data: Data(data.utf8)).prefix(8).map({String(format:"%02x",$0)}).joined() else { throw RemovalError.invalid("솔라시 삭제 계획 범위 오류") }
        let plist = try PropertyListSerialization.propertyList(from: Data(contentsOf: URL(fileURLWithPath: app+"/Contents/Info.plist")), format: nil) as? [String:Any]
        let settings = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: app+"/Contents/Resources/launch.json"))) as? [String:Any]
        guard plist?["CFBundleIdentifier"] as? String == bundle_id, plist?["CFBundleExecutable"] as? String == "Solasi",
              settings?["data"] as? String == data, settings?["runtime"] as? String == runtime else { throw RemovalError.invalid("앱 실행 설정이 달라졌습니다") }
        let preferences = [home+"/Library/Preferences/"+bundle_id+".plist",home+"/Library/Logs/"+bundle_id,home+"/Library/Caches/"+bundle_id,home+"/Library/WebKit/"+bundle_id,home+"/Library/HTTPStorages/"+bundle_id,home+"/Library/Saved Application State/"+bundle_id+".savedState"]
        guard Set(os_paths ?? []).isSubset(of:Set(preferences)),
              !isReset || (os_paths ?? []).allSatisfy({ $0 != app && !$0.hasPrefix(app+"/") && !app.hasPrefix($0+"/") }) else { throw RemovalError.invalid("OS 설정 정리 경로 오류") }
        for target in targets {
            let path = target.path
            guard (!isReset || path == app || (!path.hasPrefix(app+"/") && !app.hasPrefix(path+"/"))),
                  path == app || path.hasPrefix(data+"/") || path.hasPrefix(runtime+"/") || preferences.contains(path),
                  path != data, path != runtime,
                  !receipt.directory.hasPrefix(path+"/"), receipt.directory != path,
                  !path.hasPrefix(receipt.directory+"/") else { throw RemovalError.invalid("보존 자료 또는 허용 범위 밖의 삭제 요청") }
            guard try rootInfo(target) != nil else { continue }
            if !target.mutable {
                let expected = Dictionary(uniqueKeysWithValues: target.entries.map { ($0.name,$0) })
                try inspect(target.path, relative: ".", expected: expected)
            }
        }
        let proof = try removalHash(data+"/app.sqlite3")
        guard proof.0 == database_proof.bytes, proof.1 == database_proof.sha256 else { throw RemovalError.invalid("원래 보관함이 검증 이후 변경되었습니다") }
        let folder = URL(fileURLWithPath: receipt.directory)
        var info = stat(); let (parent,name) = try removalParent(folder.path); defer { Darwin.close(parent) }
        guard fstatat(parent,name,&info,AT_SYMLINK_NOFOLLOW) == 0, info.st_mode & S_IFMT == S_IFDIR,
              receipt.directory_identity == [UInt64(info.st_dev),UInt64(info.st_ino)],
              try removalHash(receipt.manifest).1 == receipt.manifest_sha256 else { throw RemovalError.invalid("보존 폴더나 목록이 바뀌었습니다") }
        for file in receipt.files {
            guard !file.path.hasPrefix("/"), !file.path.split(separator:"/").contains("..") else { throw RemovalError.invalid("보존 파일 경로 오류") }
            let value = try removalHash(folder.appendingPathComponent(file.path).path)
            guard value.0 == file.bytes, value.1 == file.sha256 else { throw RemovalError.invalid("보존 파일이 손상되었습니다: \(file.path)") }
        }
    }

    private func inspect(_ path: String, relative: String, expected: [String:RemovalEntry]) throws {
        var info = stat()
        guard lstat(path,&info) == 0, let entry = expected[relative], matches(info, entry) else { throw RemovalError.invalid("삭제 대상 내용 변경: \(path)") }
        if info.st_mode & S_IFMT == S_IFDIR {
            let actual = try FileManager.default.contentsOfDirectory(atPath: path)
            let children = expected.keys.filter { key in key != "." && (relative == "." ? !key.contains("/") : (key.hasPrefix(relative+"/") && !key.dropFirst(relative.count+1).contains("/"))) }
            guard actual.count == children.count else { throw RemovalError.invalid("삭제 대상에 새로운 파일이 있습니다: \(path)") }
            for name in actual { try inspect(path+"/"+name, relative: relative == "." ? name : relative+"/"+name, expected: expected) }
        }
    }

    private func matches(_ value: stat, _ entry: RemovalEntry) -> Bool {
        let kind = value.st_mode & S_IFMT
        return value.st_uid == getuid() && UInt64(value.st_dev) == entry.device && UInt64(value.st_ino) == entry.inode &&
            Int64(value.st_size) == entry.bytes && Int64(value.st_mtimespec.tv_sec)*1_000_000_000+Int64(value.st_mtimespec.tv_nsec) == entry.mtime &&
            ((kind == S_IFDIR && entry.kind == "directory") || (kind == S_IFREG && entry.kind == "file") || (kind == S_IFLNK && entry.kind == "link"))
    }

    func remove() throws {
        // The same lock used by the worker remains held until cleanup finishes.
        let (lockParent,lockName) = try removalParent(data+"/instance.lock"); defer { Darwin.close(lockParent) }
        let lock = openat(lockParent,lockName,O_RDWR | O_NOFOLLOW | O_CLOEXEC)
        guard lock >= 0 else { throw RemovalError.invalid("보관함 잠금 파일을 열 수 없습니다") }
        defer { Darwin.close(lock) }
        guard flock(lock,LOCK_EX | LOCK_NB) == 0 else { throw RemovalError.invalid("보관함을 사용하는 앱이 남아 있습니다") }
        try validate()
        var openChecks = targets.filter { $0.path.hasPrefix(runtime+"/") || $0.path == data+"/app.sqlite3" }.map(\.path)
        let appBinary = app+"/Contents/MacOS/Solasi"
        if FileManager.default.fileExists(atPath:appBinary) { openChecks.append(appBinary) }
        for start in stride(from:0,to:openChecks.count,by:128) {
            let process = Process(), output = Pipe(), errors = Pipe()
            process.executableURL = URL(fileURLWithPath:"/usr/sbin/lsof")
            process.arguments = ["-t","--"] + Array(openChecks[start..<min(start+128,openChecks.count)])
            process.standardOutput = output; process.standardError = errors
            try process.run()
            let opened = output.fileHandleForReading.readDataToEndOfFile()
            let diagnostic = errors.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            guard opened.isEmpty else { throw RemovalError.invalid("다른 프로세스가 보관함·모델·앱을 사용 중입니다. 종료한 뒤 다시 시도하세요.") }
            guard process.terminationStatus == 1, diagnostic.isEmpty else { throw RemovalError.invalid("구성요소 사용 여부를 확인할 수 없어 삭제를 중단했습니다.") }
        }
        let marker = openat(lockParent,".solasi-uninstalling",O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC,0o600)
        guard marker >= 0 else { throw RemovalError.invalid("설치 삭제 진행 표식을 만들 수 없습니다") }
        Darwin.close(marker)
        defer { _ = unlinkat(lockParent,".solasi-uninstalling",0) }
        var actualTargets = targets.filter { !isReset || $0.path != app }
        for path in os_paths ?? [] where !targets.contains(where: { $0.path == path }) {
            guard let (parent,name) = try optionalRemovalParent(path) else { continue }; defer { Darwin.close(parent) }
            var value = stat()
            if fstatat(parent,name,&value,AT_SYMLINK_NOFOLLOW) == 0 {
                guard value.st_uid == getuid(), value.st_mode & S_IFMT != S_IFLNK else { throw RemovalError.invalid("앱 설정 경로 변경 감지") }
                actualTargets.insert(RemovalTarget(path:path,device:UInt64(value.st_dev),inode:UInt64(value.st_ino),mutable:true,entries:[]),at:isReset ? actualTargets.count : actualTargets.count-1)
            } else if errno != ENOENT { throw RemovalError.invalid("앱 설정 경로를 확인할 수 없습니다") }
        }
        var parents: [String:Int32] = [:]
        defer { for descriptor in parents.values { Darwin.close(descriptor) } }
        for target in actualTargets {
            let parentPath = URL(fileURLWithPath: target.path).deletingLastPathComponent().path
            if parents[parentPath] == nil { parents[parentPath] = try removalParent(target.path).0 }
            guard faccessat(parents[parentPath]!,".",W_OK | X_OK,0) == 0 else { throw RemovalError.invalid("삭제 권한이 없습니다: \(target.path)") }
        }
        for account in ["openai","gemini","claude"] {
            let result = SecItemDelete([kSecClass:kSecClassGenericPassword,kSecAttrService:service,kSecAttrAccount:account] as CFDictionary)
            guard result == errSecSuccess || result == errSecItemNotFound else { throw RemovalError.invalid("저장된 API 키 삭제 실패 (\(result))") }
        }
        for target in actualTargets {
            guard let current = try rootInfo(target) else { continue }
            let url = URL(fileURLWithPath: target.path), parent = parents[url.deletingLastPathComponent().path]!, name = url.lastPathComponent
            var info = stat()
            guard fstatat(parent,name,&info,AT_SYMLINK_NOFOLLOW) == 0, info.st_dev == current.st_dev, info.st_ino == current.st_ino else { throw RemovalError.invalid("삭제 직전 대상 변경: \(target.path)") }
            let staged = ".solasi-remove-"+UUID().uuidString
            guard renameatx_np(parent,name,parent,staged,UInt32(RENAME_EXCL)) == 0 else { throw RemovalError.invalid("삭제 대상 격리 실패: \(target.path)") }
            do {
                var moved = stat()
                guard fstatat(parent,staged,&moved,AT_SYMLINK_NOFOLLOW) == 0, moved.st_ino == current.st_ino, moved.st_dev == current.st_dev else { throw RemovalError.invalid("삭제 대상이 바뀌었습니다") }
                try erase(parent, name: staged, relative: ".", expected: target.mutable ? nil : Dictionary(uniqueKeysWithValues: target.entries.map{($0.name,$0)}))
            } catch {
                let restored = renameatx_np(parent,staged,parent,name,UInt32(RENAME_EXCL)) == 0
                throw RemovalError.invalid("일부 항목을 삭제하지 못했습니다. 남은 위치: \(restored ? target.path : url.deletingLastPathComponent().appendingPathComponent(staged).path) · \(error.localizedDescription)")
            }
        }
        _ = unlinkat(lockParent,".solasi-uninstalling",0)
        // Only remove empty parents of planned items; leave unrelated backup directories alone.
        var containers = Set<String>()
        for target in actualTargets where target.path.hasPrefix(data+"/") || target.path.hasPrefix(runtime+"/") {
            var url = URL(fileURLWithPath: target.path).deletingLastPathComponent()
            while url.path == data || url.path == runtime || url.path.hasPrefix(data+"/") || url.path.hasPrefix(runtime+"/") {
                containers.insert(url.path); url.deleteLastPathComponent()
            }
        }
        for path in containers.sorted(by: { $0.count > $1.count }) where !isReset || (path != data && path != runtime) {
            if let (parent,name) = try? removalParent(path) { _ = unlinkat(parent,name,AT_REMOVEDIR); Darwin.close(parent) }
        }
    }

    private func erase(_ parent: Int32, name: String, relative: String, expected: [String:RemovalEntry]?) throws {
        var info = stat()
        guard fstatat(parent,name,&info,AT_SYMLINK_NOFOLLOW) == 0 else { throw RemovalError.invalid("삭제 항목 접근 실패") }
        if let expected { guard let entry = expected[relative], matches(info,entry) else { throw RemovalError.invalid("삭제 중 항목 변경 감지") } }
        if info.st_mode & S_IFMT == S_IFDIR {
            let directory = openat(parent,name,O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
            guard directory >= 0 else { throw RemovalError.invalid("삭제 폴더가 변경되었습니다") }
            defer { Darwin.close(directory) }
            var opened = stat(); guard fstat(directory,&opened) == 0, opened.st_ino == info.st_ino, opened.st_dev == info.st_dev else { throw RemovalError.invalid("삭제 폴더 변경 감지") }
            guard let stream = fdopendir(dup(directory)) else { throw RemovalError.invalid("삭제 폴더 읽기 실패") }
            var children: [String] = []
            while let item = readdir(stream) {
                let value = withUnsafePointer(to: &item.pointee.d_name) { pointer in pointer.withMemoryRebound(to:CChar.self,capacity:Int(item.pointee.d_namlen)+1) { String(cString:$0) } }
                if value != "." && value != ".." { children.append(value) }
            }
            closedir(stream)
            for child in children { try erase(directory,name:child,relative:relative == "." ? child : relative+"/"+child,expected:expected) }
            guard unlinkat(parent,name,AT_REMOVEDIR) == 0 else { throw RemovalError.invalid("빈 폴더 제거 실패") }
        } else {
            guard unlinkat(parent,name,0) == 0 else { throw RemovalError.invalid("파일 제거 실패") }
        }
    }
}

func removalConsent(verified: Bool, confirmed: Bool, phrase: String, reset: Bool = false) -> Bool {
    verified && confirmed && phrase == (reset ? "솔라시 초기화" : "솔라시 삭제")
}
