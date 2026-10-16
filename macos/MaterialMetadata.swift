import AppKit
import Foundation
import PDFKit

guard CommandLine.arguments.count == 2 else { exit(1) }
let url = URL(fileURLWithPath: CommandLine.arguments[1])
var pages: [[String: Any]] = []
if let document = PDFDocument(url: url) {
    guard !document.isLocked else { exit(2) }
    for index in 0..<document.pageCount {
        guard let page = document.page(at: index) else { exit(3) }
        let bounds = page.bounds(for: .cropBox)
        let rotation = (page.rotation % 360 + 360) % 360
        let sideways = rotation == 90 || rotation == 270
        pages.append(["page": index + 1, "width": sideways ? bounds.height : bounds.width,
                      "height": sideways ? bounds.width : bounds.height, "rotation": rotation])
    }
} else if let data = try? Data(contentsOf: url), let image = NSBitmapImageRep(data: data) {
    pages.append(["page": 1, "width": image.pixelsWide, "height": image.pixelsHigh, "rotation": 0])
} else { exit(4) }
guard !pages.isEmpty else { exit(5) }
FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: pages))
