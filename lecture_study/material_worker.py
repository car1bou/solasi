import sys
import json
import subprocess
import tempfile
from pathlib import Path
from .materials import Extraction, PageContent, normalize_result
from .models import SourceRef


def main():
    mode, source, output, runtime, ident, version, kind, *rest = sys.argv[1:]
    version = int(version)
    source,output,runtime = Path(source),Path(output),Path(runtime)
    if mode=='ink-render':
        from .materials_portable import render_ink
        encoded=sys.stdin.buffer.read(8*1024*1024+1)
        if len(encoded)>8*1024*1024:raise ValueError('필기 입력이 너무 큽니다')
        result=render_ink(json.loads(encoded),output,page_source=rest[0]or None,page=int(rest[1]))
        print(json.dumps(result));return
    if mode=='metadata':
        if sys.platform=='win32':
            from .materials_portable import read_metadata
            output.write_text(json.dumps(read_metadata(source)),encoding='utf-8');return
        if sys.platform!='darwin':raise ValueError('현재 OS의 원본 페이지 정보 엔진을 준비하세요')
        if getattr(sys,'frozen',False):
            command=[str(Path(sys.executable).parent/'MaterialMetadata'),str(source)]
        else:
            cache=Path(tempfile.gettempdir())/'solasi-swift-module-cache'
            command=['/usr/bin/swift','-module-cache-path',str(cache),str(Path(__file__).parent.parent/'macos/MaterialMetadata.swift'),str(source)]
        result=subprocess.run(command,capture_output=True,timeout=90,check=True)
        output.write_bytes(result.stdout)
        return
    if mode=='render'and sys.platform=='win32':
        from .materials_portable import render_page
        render_page(source,int(rest[0]),output);return
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
    if sys.platform=='win32':
        from .handwriting_windows import ocr_data_ready
        ready=ocr_data_ready(runtime)
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
