import AppKit
import Darwin
import CoreText
import Foundation
import PDFKit

struct Point: Decodable { let x, y, pressure: CGFloat }
struct Ink: Decodable { let tool, color: String; let width, opacity: CGFloat; let points: [Point]; let text: String? }
struct PageInk: Decodable { let page: Int; let ink: [Ink] }
enum ExportError: Error { case invalid(String) }

final class PDFSink {
    var descriptor: Int32
    var failure: Int32 = 0
    init(_ url: URL) throws {
        descriptor = Darwin.open(url.path, O_WRONLY | O_CREAT | O_EXCL, 0o600)
        guard descriptor >= 0 else { throw ExportError.invalid("새 PDF 출력 경로 확인 필요") }
    }
    deinit { if descriptor >= 0 { Darwin.close(descriptor) } }
    func append(_ bytes: UnsafeRawPointer, _ count: Int) -> Int {
        guard failure == 0 else { return 0 }
        var offset = 0
        while offset < count {
            let written = Darwin.write(descriptor, bytes.advanced(by: offset), count-offset)
            if written < 0 && errno == EINTR { continue }
            guard written > 0 else { failure = written == 0 ? EIO : errno; return 0 }
            offset += written
        }
        return count
    }
    func finish() throws {
        if failure == 0 && Darwin.fsync(descriptor) != 0 { failure = errno }
        if Darwin.close(descriptor) != 0 && failure == 0 { failure = errno }; descriptor = -1
        guard failure == 0 else { throw ExportError.invalid("PDF 쓰기 실패 · 저장 공간을 확인하세요 (\(failure))") }
    }
}

func draw(_ ink: Ink, size: CGSize, in context: CGContext) throws {
    guard ["pen", "highlighter", "text"].contains(ink.tool), ink.width.isFinite, ink.width >= 0.0002, ink.width <= 0.1,
          ink.opacity.isFinite, (0.05...1).contains(ink.opacity), !ink.points.isEmpty,
          ink.points.allSatisfy({ $0.x.isFinite && $0.y.isFinite && $0.pressure.isFinite && (0...1).contains($0.x) && (0...1).contains($0.y) && (0...1).contains($0.pressure) }),
          ink.color.range(of: "^#[0-9a-fA-F]{6}$", options: .regularExpression) != nil,
          let rgb = UInt32(ink.color.dropFirst(), radix: 16) else { throw ExportError.invalid("필기 형식 오류") }
    let color = NSColor(srgbRed: CGFloat((rgb >> 16) & 255)/255, green: CGFloat((rgb >> 8) & 255)/255, blue: CGFloat(rgb & 255)/255, alpha: 1)
    context.saveGState(); defer { context.restoreGState() }
    context.setAlpha(ink.opacity)
    if ink.tool == "text" {
        guard ink.points.count == 2, let text = ink.text, !text.isEmpty, text.count <= 10000,
              ink.points[1].x > ink.points[0].x, ink.points[1].y > ink.points[0].y else { throw ExportError.invalid("글상자 형식 오류") }
        let box = CGRect(x: ink.points[0].x*size.width, y: ink.points[0].y*size.height,
                         width: (ink.points[1].x-ink.points[0].x)*size.width, height: (ink.points[1].y-ink.points[0].y)*size.height)
        context.clip(to: box)
        let font = CTFontCreateWithName("Helvetica" as CFString, ink.width*size.width, nil)
        let value = NSAttributedString(string: text, attributes: [NSAttributedString.Key(kCTFontAttributeName as String): font, NSAttributedString.Key(kCTForegroundColorAttributeName as String): color.cgColor])
        let typesetter = CTTypesetterCreateWithAttributedString(value)
        let length = value.length, lineHeight = ink.width*size.width*1.25
        var offset = 0, top = box.minY
        while offset < length && top < box.maxY {
            let count = CTTypesetterSuggestLineBreak(typesetter, offset, Double(box.width))
            guard count > 0 else { break }
            let line = CTTypesetterCreateLine(typesetter, CFRange(location: offset, length: count))
            let baseline = top + (lineHeight - CTFontGetAscent(font) - CTFontGetDescent(font))/2 + CTFontGetAscent(font)
            context.saveGState()
            context.translateBy(x: box.minX, y: baseline); context.scaleBy(x: 1, y: -1)
            context.textMatrix = .identity; context.textPosition = .zero
            CTLineDraw(line, context); context.restoreGState()
            top += lineHeight; offset += count
        }
    } else {
        let points = ink.points.map { CGPoint(x: $0.x*size.width, y: $0.y*size.height) }
        let radius: (Int) -> CGFloat = { i in ink.width*size.width*(ink.tool == "pen" ? 0.35+0.65*ink.points[i].pressure : 1)/2 }
        let path = CGMutablePath()
        if points.count == 1 {
            let r = radius(0); path.addEllipse(in: CGRect(x: points[0].x-r, y: points[0].y-r, width: 2*r, height: 2*r))
        } else {
            var left: [CGPoint] = [], right: [CGPoint] = []
            for i in points.indices {
                let a = points[max(0,i-1)], b = points[min(points.count-1,i+1)]
                let dx = b.x-a.x, dy = b.y-a.y, length = hypot(dx,dy)
                let nx = length == 0 ? 0 : -dy/length, ny = length == 0 ? 0 : dx/length, r = radius(i)
                left.append(CGPoint(x: points[i].x+nx*r, y: points[i].y+ny*r))
                right.append(CGPoint(x: points[i].x-nx*r, y: points[i].y-ny*r))
            }
            path.addLines(between: left + right.reversed()); path.closeSubpath()
        }
        context.setFillColor(color.cgColor); context.addPath(path); context.fillPath()
    }
}

do {
    guard CommandLine.arguments.count == 3 else { throw ExportError.invalid("입력·출력 경로 필요") }
    let source = URL(fileURLWithPath: CommandLine.arguments[1]), output = URL(fileURLWithPath: CommandLine.arguments[2])
    guard source.standardizedFileURL != output.standardizedFileURL,
          !FileManager.default.fileExists(atPath: output.path), let document = PDFDocument(url: source), !document.isLocked,
          document.pageCount > 0 else { throw ExportError.invalid("원본 PDF 또는 새 출력 경로 확인 필요") }
    let pages = try JSONDecoder().decode([PageInk].self, from: FileHandle.standardInput.readDataToEndOfFile())
    guard pages.count == document.pageCount, pages.enumerated().allSatisfy({ $0.element.page == $0.offset+1 }) else { throw ExportError.invalid("PDF 페이지 수 불일치") }
    // Reserve the private output exclusively; the app also commits the final destination exclusively.
    let sink = try PDFSink(output)
    var complete = false
    defer { if !complete { try? FileManager.default.removeItem(at: output) } }
    var callbacks = CGDataConsumerCallbacks(putBytes: { info, bytes, count in
        guard let info = info else { return 0 }
        return Unmanaged<PDFSink>.fromOpaque(info).takeUnretainedValue().append(bytes, count)
    }, releaseConsumer: { info in
        if let info = info { Unmanaged<PDFSink>.fromOpaque(info).release() }
    })
    let info = Unmanaged.passRetained(sink).toOpaque()
    guard let consumer = CGDataConsumer(info: info, cbks: &callbacks) else {
        Unmanaged<PDFSink>.fromOpaque(info).release(); throw ExportError.invalid("PDF 출력 준비 실패")
    }
    guard let context = CGContext(consumer: consumer, mediaBox: nil, nil) else { throw ExportError.invalid("PDF 출력 준비 실패") }
    for i in 0..<document.pageCount {
        try autoreleasepool {
            guard let page = document.page(at: i) else { throw ExportError.invalid("원본 페이지 없음") }
            let crop = page.bounds(for: .cropBox), sideways = [90,270].contains((page.rotation%360+360)%360)
            let size = CGSize(width: sideways ? crop.height : crop.width, height: sideways ? crop.width : crop.height)
            guard size.width > 0, size.height > 0 else { throw ExportError.invalid("페이지 크기 오류") }
            var bounds = CGRect(origin: .zero, size: size)
            context.beginPDFPage([kCGPDFContextMediaBox as String: Data(bytes: &bounds, count: MemoryLayout<CGRect>.size)] as CFDictionary)
            guard let original = page.pageRef else { throw ExportError.invalid("원본 PDF 페이지 읽기 실패") }
            context.saveGState()
            context.concatenate(original.getDrawingTransform(.cropBox, rect: bounds, rotate: 0, preserveAspectRatio: true))
            context.drawPDFPage(original)
            context.restoreGState()
            for annotation in page.annotations where annotation.shouldDisplay { annotation.draw(with: .cropBox, in: context) }
            context.saveGState(); context.translateBy(x: 0, y: size.height); context.scaleBy(x: 1, y: -1)
            context.clip(to: CGRect(origin: .zero, size: size))
            for ink in pages[i].ink { try draw(ink, size: size, in: context) }
            context.restoreGState(); context.endPDFPage()
        }
    }
    context.closePDF(); try sink.finish(); complete = true
} catch {
    FileHandle.standardError.write(Data("\(error)".utf8)); exit(1)
}
