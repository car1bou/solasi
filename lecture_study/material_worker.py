import sys
from pathlib import Path
from .materials import Extraction, PageContent, normalize_result
from .models import SourceRef


def main():
    mode, source, output, runtime, ident, version, kind, *rest = sys.argv[1:]
    version = int(version)
    source,output,runtime = Path(source),Path(output),Path(runtime)
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
