import Foundation
import AppKit
import Vision
import ImageIO
import PDFKit

struct Point: Decodable { let x: Double; let y: Double; let pressure: Double }
struct Stroke: Decodable { let tool: String; let width: Double; let points: [Point] }
struct Input: Decodable { let page_width: Double; let page_height: Double; let strokes: [Stroke] }
func fail(_ message: String) -> Never { FileHandle.standardError.write(Data(message.utf8)); exit(2) }
func sourceBox(_ box: CGRect) -> [CGFloat] {
    let b = box.intersection(CGRect(x: 0, y: 0, width: 1, height: 1))
    return [b.minX, 1-b.maxY, b.width, b.height]
}
do {
    let arguments = Array(CommandLine.arguments.dropFirst())
    func argument(_ flag: String) -> String? {
        guard let index = arguments.firstIndex(of: flag), index + 1 < arguments.count else { return nil }
        return arguments[index + 1]
    }
    let image: CGImage
    if CommandLine.arguments.count == 3 && CommandLine.arguments[1] == "--recognize-image" {
        let url = URL(fileURLWithPath: CommandLine.arguments[2])
        let attrs = try FileManager.default.attributesOfItem(atPath: url.path)
        guard (attrs[.size] as? NSNumber)?.intValue ?? Int.max <= 20 * 1024 * 1024,
              let source = CGImageSourceCreateWithURL(url as CFURL, nil),
              let loaded = CGImageSourceCreateImageAtIndex(source, 0, nil), loaded.width <= 12000, loaded.height <= 12000 else { fail("이미지 크기를 확인하세요") }
        image = loaded
    } else {
    let data = FileHandle.standardInput.readDataToEndOfFile()
    guard data.count <= 8 * 1024 * 1024 else { fail("필기 입력이 너무 큽니다") }
    let input = try JSONDecoder().decode(Input.self, from: data)
    guard input.page_width.isFinite, input.page_height.isFinite, input.page_width > 0, input.page_height > 0,
          input.page_width <= 100000, input.page_height <= 100000, input.strokes.count <= 2000,
          input.strokes.reduce(0, { $0 + $1.points.count }) <= 100000 else { fail("페이지·필기 크기를 확인하세요") }
    let scale = min(3, 2400 / max(input.page_width, input.page_height))
    let width = max(1, Int(input.page_width * scale)), height = max(1, Int(input.page_height * scale))
    guard let context = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: width * 4,
                                  space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { fail("이미지를 만들 수 없습니다") }
    context.setFillColor(NSColor.white.cgColor); context.fill(CGRect(x: 0, y: 0, width: width, height: height))
    if let source = argument("--page-source"), let index = arguments.firstIndex(of: "--page-source") {
        guard index + 2 < arguments.count, let number = Int(arguments[index + 2]), number > 0 else { fail("원본 페이지를 확인하세요") }
        let url = URL(fileURLWithPath: source)
        let background: CGImage?
        if let document = PDFDocument(url: url) {
            guard let page = document.page(at: number - 1) else { fail("원본 페이지를 열 수 없습니다") }
            background = page.thumbnail(of: NSSize(width: width, height: height), for: .cropBox).cgImage(forProposedRect: nil, context: nil, hints: nil)
        } else {
            guard number == 1, let source = CGImageSourceCreateWithURL(url as CFURL, nil) else { fail("원본 이미지를 열 수 없습니다") }
            background = CGImageSourceCreateImageAtIndex(source, 0, nil)
        }
        guard let background else { fail("원본 페이지를 그릴 수 없습니다") }
        context.draw(background, in: CGRect(x: 0, y: 0, width: width, height: height))
    }
    context.setStrokeColor(NSColor.black.cgColor); context.setFillColor(NSColor.black.cgColor)
    context.setLineCap(.round); context.setLineJoin(.round)
    for stroke in input.strokes where stroke.tool == "pen" {
        guard stroke.width.isFinite, stroke.width >= 0.0002, stroke.width <= 0.1, !stroke.points.isEmpty,
              stroke.points.allSatisfy({ $0.x.isFinite && $0.y.isFinite && $0.pressure.isFinite && (0...1).contains($0.x) && (0...1).contains($0.y) && (0...1).contains($0.pressure) }) else { fail("획 좌표를 확인하세요") }
        let points = stroke.points
        for index in points.indices {
            let p = points[index], before = points[max(0, index - 1)]
            let diameter = max(1, stroke.width * Double(width) * (0.35 + 0.65 * (before.pressure + p.pressure) / 2))
            context.setLineWidth(diameter)
            let a = CGPoint(x: before.x * Double(width), y: (1 - before.y) * Double(height))
            let b = CGPoint(x: p.x * Double(width), y: (1 - p.y) * Double(height))
            if index == 0 { context.fillEllipse(in: CGRect(x: b.x-diameter/2, y: b.y-diameter/2, width: diameter, height: diameter)) }
            else { context.move(to: a); context.addLine(to: b); context.strokePath() }
        }
    }
    guard let rendered = context.makeImage() else { fail("필기 이미지를 만들 수 없습니다") }
    image = rendered
    }
    if let output = argument("--image") {
        let rep = NSBitmapImageRep(cgImage: image)
        guard let png = rep.representation(using: .png, properties: [:]) else { fail("이미지 저장 실패") }
        try png.write(to: URL(fileURLWithPath: output), options: .atomic)
    }
    let request = VNRecognizeTextRequest(); request.recognitionLevel = .accurate; request.usesLanguageCorrection = false
    let languages = try request.supportedRecognitionLanguages()
    request.recognitionLanguages = ["ko-KR", "en-US"].filter { languages.contains($0) }
    guard request.recognitionLanguages.contains("ko-KR") else { fail("현재 OS가 한국어 인식을 지원하지 않습니다") }
    try VNImageRequestHandler(cgImage: image).perform([request])
    let regions: [[String: Any]] = (request.results ?? []).compactMap { item in
        let candidates = item.topCandidates(3)
        guard let top = candidates.first else { return nil }
        let b = item.boundingBox
        return ["bbox": sourceBox(b), "text": top.string,
                "edge_touching": b.minX < 0.015 || b.minY < 0.015 || b.maxX > 0.985 || b.maxY > 0.985,
                "candidates": candidates.map { ["text": $0.string, "score": $0.confidence] as [String: Any] }]
    }
    let suffix = argument("--page-source") == nil ? "" : "/page"
    let result: [String: Any] = ["engine": "apple-vision-accurate-v\(request.revision)/bounds-v2\(suffix)", "revision": request.revision,
                               "languages": request.recognitionLanguages, "regions": regions]
    FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: result))
} catch { fail(error.localizedDescription) }
