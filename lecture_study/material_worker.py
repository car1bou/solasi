import sys
import subprocess
import tempfile
from pathlib import Path
from .materials import Extraction, PageContent, normalize_result
from .models import SourceRef


def main():
    mode, source, output, runtime, ident, version, kind, *rest = sys.argv[1:]
    version = int(version)
    source,output,runtime = Path(source),Path(output),Path(runtime)
    if mode=='metadata':
        if sys.platform!='darwin':raise ValueError('원본 페이지 정보는 현재 Mac에서 지원합니다')
        script='''import Foundation
import PDFKit
import AppKit
let url = URL(fileURLWithPath: CommandLine.arguments.last!)
var pages: [[String: Any]] = []
if let document = PDFDocument(url: url) {
    guard !document.isLocked else { exit(2) }
    for index in 0..<document.pageCount {
        guard let page = document.page(at: index) else { exit(3) }
        let bounds = page.bounds(for: .cropBox)
        let rotation = (page.rotation % 360 + 360) % 360
        let sideways = rotation == 90 || rotation == 270
        pages.append(["page": index + 1, "width": sideways ? bounds.height : bounds.width, "height": sideways ? bounds.width : bounds.height, "rotation": rotation])
    }
} else if let data = try? Data(contentsOf: url), let image = NSBitmapImageRep(data: data) {
    pages.append(["page": 1, "width": image.pixelsWide, "height": image.pixelsHigh, "rotation": 0])
} else { exit(4) }
guard !pages.isEmpty else { exit(5) }
FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: pages))
'''
        cache=Path(tempfile.gettempdir())/'solasi-swift-module-cache'
        result=subprocess.run(['/usr/bin/swift','-module-cache-path',str(cache),'-e',script,str(source)],capture_output=True,timeout=90,check=True)
        output.write_bytes(result.stdout)
        return
    if mode=="parse" and kind in ("txt","md"):
        text = source.read_text(encoding="utf-8-sig")
        ref = SourceRef(id=f"{ident}:v{version}:page:1",kind="material",asset_id=ident,version=version,page=1)
        result = Extraction(asset_id=ident,status="ready",total_pages=1,
                            pages=[PageContent(page=1,width=0,height=0,text=text,ref=ref)])
        output.write_text(result.model_dump_json(),encoding="utf-8")
        return
    from liteparse import LiteParse
    tess = runtime/"tessdata"
    ready = all((tess/f"{language}.traineddata").is_file() for language in ("kor","eng"))
    parser = LiteParse(ocr_enabled=ready,ocr_language="kor+eng",tessdata_path=str(tess),
                       extract_images=True,continue_on_page_error=True,output_format="markdown",keep_headers_footers=True,
                       include_complexity=True,quiet=True,num_workers=1)
    if mode=="parse":
        result = normalize_result(parser.parse(source),ident,output.parent,ready,version)
        output.write_text(result.model_dump_json(),encoding="utf-8")
    elif mode=="image":
        image = parser.parse(source).images[int(rest[0])]
        output.write_bytes(image.bytes)
    elif mode=="render":
        screenshots = parser.screenshot(source,page_numbers=[int(rest[0])])
        if not screenshots:
            raise ValueError("페이지 렌더링 실패")
        output.write_bytes(screenshots[0].image_bytes)
    else:
        raise ValueError("알 수 없는 작업")


if __name__=="__main__":
    main()
