import asyncio
import hashlib
import json
import sys
from pathlib import Path
from fastapi import HTTPException
from pydantic import BaseModel, Field
from .db import data_dir, new_id, now, session,course
from .models import SourceRef
from .retrieval import index_source
from .execution import worker_command

MAX_MATERIAL_BYTES = 256*1024*1024
MAX_CACHE_BYTES = 256*1024*1024


class PageContent(BaseModel):
    page: int
    width: float
    height: float
    text: str
    items: list[dict] = Field(default_factory=list)
    ref: SourceRef


class ImageContent(BaseModel):
    id: str
    ref: SourceRef
    path: str
    width: int
    height: int


class Extraction(BaseModel):
    asset_id: str
    status: str
    total_pages: int
    pages: list[PageContent]
    images: list[ImageContent] = Field(default_factory=list)
    page_errors: list[dict] = Field(default_factory=list)


def asset_dir(db, ident):
    row = db.execute("SELECT * FROM assets WHERE id=?",(ident,)).fetchone()
    if row is None:
        raise KeyError("자료를 찾을 수 없습니다")
    return data_dir(db)/"assets"/row["id"],dict(row)


def detect_kind(head, filename):
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    suffix = Path(filename).suffix.lower()
    if suffix in (".txt",".md"):
        return suffix[1:]
    raise ValueError("PDF·PNG·JPG·TXT·MD 파일을 선택하세요")


def inspect_file(path):
    import stat
    path = path.resolve(strict=True)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("일반 파일만 연결할 수 있습니다")
    if info.st_size>MAX_MATERIAL_BYTES:
        raise HTTPException(413,"자료는 256 MiB까지 처리할 수 있습니다")
    if not info.st_size:
        raise ValueError("빈 파일입니다")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        kind = detect_kind(handle.read(16),path.name)
        handle.seek(0)
        while chunk:=handle.read(65536):
            digest.update(chunk)
    if kind in ("txt","md"):
        try:
            with path.open(encoding="utf-8-sig") as handle:
                while handle.read(65536):
                    pass
        except UnicodeError:
            raise ValueError("TXT·MD 파일은 UTF-8이어야 합니다")
    after = path.stat()
    if (info.st_mtime_ns,info.st_size)!=(after.st_mtime_ns,after.st_size):
        raise ValueError("파일이 변경되었습니다. 다시 연결하세요")
    return {"path":str(path),"filename":path.name,"kind":kind,"sha256":digest.hexdigest(),"size":info.st_size,"mtime_ns":info.st_mtime_ns}


def register_file(db,session_id,inspected,course_id=None,*,handwritten=False):
    owner=session(db,session_id) if session_id else course(db,course_id)
    course_id=owner.get('course_id') if session_id else course_id
    if handwritten and (not course_id or inspected['kind'] not in ('pdf','png','jpg')):
        raise ValueError('손글씨 노트는 과목에 PDF·PNG·JPEG로 연결하세요')
    if Path(inspected["path"]).is_relative_to(data_dir(db).resolve()):
        raise ValueError("앱 관리 폴더 밖의 원본 파일을 선택하세요")
    existing = db.execute("SELECT id FROM assets WHERE external_path=?",(inspected["path"],)).fetchone()
    ident = existing["id"] if existing else new_id()
    if not existing:
        (data_dir(db)/"assets"/ident).mkdir(parents=True,mode=0o700)
    with db:
        if not existing:
            db.execute("INSERT INTO assets(id,filename,kind,sha256,size,status,created_at,external_path,mtime_ns) VALUES (?,?,?,?,?,'queued',?,?,?)",
                       (ident,inspected["filename"],inspected["kind"],inspected["sha256"],inspected["size"],now(),inspected["path"],inspected["mtime_ns"]))
        if session_id:db.execute("INSERT OR IGNORE INTO session_assets VALUES (?,?)",(session_id,ident))
        if course_id:db.execute('INSERT OR IGNORE INTO course_assets VALUES (?,?)',(course_id,ident))
        if handwritten:
            db.execute('INSERT OR IGNORE INTO handwritten_assets VALUES (?)',(ident,))
            db.execute("UPDATE assets SET status='ready',error=NULL WHERE id=? AND status!='running'",(ident,))
    return asset_dir(db,ident)[1]


def source_status(db,asset):
    path = Path(asset["external_path"]) if asset["external_path"] else data_dir(db)/"assets"/asset["id"]/f'original.{asset["kind"]}'
    try:
        info = path.stat()
    except FileNotFoundError:
        return "missing"
    except PermissionError:
        return "denied"
    return "changed" if info.st_size!=asset["size"] or (asset["external_path"] and info.st_mtime_ns!=asset["mtime_ns"]) else "current"


def original_path(db,asset):
    state = source_status(db,asset)
    if state!="current":
        labels = {"missing":"원본 파일을 찾을 수 없습니다","denied":"파일 접근 권한이 없습니다","changed":"원본 파일이 변경되었습니다. 재추출하세요"}
        raise HTTPException(409,labels[state])
    return Path(asset["external_path"]) if asset["external_path"] else data_dir(db)/"assets"/asset["id"]/f'original.{asset["kind"]}'


def material_sha256(asset,ref=None):
    if ref and ref.document_sha256:return ref.document_sha256
    return asset['extraction_sha256'] if ref is None or ref.version==asset['version'] else None


def checked_material_path(db,asset,ref=None):
    from .course_materials import checked_document_path
    digest=material_sha256(asset,ref)
    if not digest:raise HTTPException(409,'추출 자료의 원본 버전을 확인할 수 없습니다. 페이지를 다시 선택하세요')
    return checked_document_path(db,asset['id'],digest)


def is_handwritten(db,asset_id):
    return bool(db.execute('SELECT 1 FROM handwritten_assets WHERE asset_id=?',(asset_id,)).fetchone())


def require_reviewed_material(db,ref):
    if ref.kind not in ('material','ink_note') or not ref.asset_id or not is_handwritten(db,ref.asset_id):return
    if ref.kind=='material':
        raise ValueError('손글씨 노트는 페이지 인식문을 확인·승인한 뒤 질문·요약에 사용하세요')
    _,asset=asset_dir(db,ref.asset_id)
    if asset['sha256']!=ref.document_sha256 or source_status(db,asset)!='current' or not db.execute("SELECT 1 FROM ink_recognitions WHERE source_id=? AND status='approved'",(ref.id,)).fetchone():
        raise ValueError('손글씨 노트의 원본·승인문이 변경되었습니다. 최신 페이지를 다시 검토하세요')


def public_asset(db,asset):
    value = {key:item for key,item in asset.items() if key not in ("external_path","mtime_ns")}
    value["source_status"] = source_status(db,asset)
    value['handwritten']=is_handwritten(db,asset['id'])
    value["extraction"] = json.loads(value["extraction"]) if value["extraction"] else None
    return value


def normalize_result(result, ident, folder, ocr_ready, version=1):
    pages = []
    errors = [{"page":e.page_num,"message":e.message} for e in result.page_errors]
    for p in result.pages:
        ref = SourceRef(id=f"{ident}:v{version}:page:{p.page_num}",kind="material",asset_id=ident,version=version,page=p.page_num,
                        coord_system="pdf_points",source_width=p.width,source_height=p.height)
        # shortcut: OCR boxes retain upstream coordinates, revisit when LiteParse fixes overlapping boxes.
        items = [{"text":t.text,"bbox":[t.x,t.y,t.width,t.height],"confidence":t.confidence} for t in p.text_items]
        pages.append(PageContent(page=p.page_num,width=p.width,height=p.height,text=getattr(p,"markdown","") or p.text,items=items,ref=ref))
        if not ocr_ready and getattr(getattr(p,"complexity",None),"needs_ocr",False):
            errors.append({"page":p.page_num,"message":"한국어·영어 OCR 데이터가 필요합니다"})
    present = {p.page for p in pages}
    errors.extend({"page":p,"message":"페이지 추출 실패"} for p in range(1,result.total_pages+1) if p not in present and not any(e["page"]==p for e in errors))
    images = []
    page_sizes = {p.page:(p.width,p.height) for p in pages}
    for i, img in enumerate(result.images):
        suffix = img.format.lower().replace("jpeg","jpg")
        if suffix not in ("png","jpg","webp"):
            continue
        name = f"v{version}-image-{i}.{suffix}"
        width,height = page_sizes.get(img.page,(0,0))
        b = img.bbox
        ref = SourceRef(id=f"{ident}:v{version}:image:{i}",kind="material",asset_id=ident,version=version,page=img.page,
                        bbox=(b.x,b.y,b.width,b.height),coord_system="pdf_points",source_width=width,source_height=height)
        images.append(ImageContent(id=str(i),ref=ref,path=name,width=img.width,height=img.height))
    if getattr(result,"image_error_count",0):
        errors.append({"page":None,"message":"일부 이미지 추출 실패"})
    return Extraction(asset_id=ident,status="failed" if not pages else "partial" if errors else "ready",
                      total_pages=result.total_pages,pages=pages,images=images,page_errors=errors)


async def worker(args, timeout=120):
    process = await asyncio.create_subprocess_exec(*worker_command('material-worker',args),
                                                   stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
    try:
        code = await asyncio.wait_for(process.wait(),timeout)
        if code:
            raise ValueError("자료 처리에 실패했습니다. 원본을 확인하세요")
    except (TimeoutError,asyncio.CancelledError):
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(),2)
            except TimeoutError:
                process.kill()
                await process.wait()
        raise


async def ingest_asset(db, asset_id, runtime_dir):
    folder,asset = asset_dir(db,asset_id)
    try:
        source = Path(asset["external_path"]) if asset["external_path"] else folder/f'original.{asset["kind"]}'
        inspected = await asyncio.to_thread(inspect_file,source)
        version = asset["version"]+bool(asset["extraction"])
        await worker(["parse",source,folder/"extraction.json",runtime_dir,asset_id,version,inspected["kind"]])
        after = await asyncio.to_thread(inspect_file,source)
        if after["sha256"]!=inspected["sha256"]:
            raise ValueError("추출 중 원본이 변경되었습니다. 재추출하세요")
        result = Extraction.model_validate_json((folder/"extraction.json").read_text())
        with db:
            db.execute("UPDATE assets SET status=?,extraction=?,error=NULL,sha256=?,size=?,mtime_ns=?,version=?,kind=?,extraction_sha256=? WHERE id=?",
                       (result.status,result.model_dump_json(),inspected["sha256"],inspected["size"],inspected["mtime_ns"],version,inspected["kind"],inspected['sha256'],asset_id))
            for p in result.pages:
                db.execute("INSERT OR REPLACE INTO sources(id,ref,text_snapshot) VALUES (?,?,?)",
                           (p.ref.id,p.ref.model_dump_json(),p.text))
                index_source(db,p.ref,p.text)
            for i in result.images:
                db.execute("INSERT OR REPLACE INTO sources(id,ref,text_snapshot) VALUES (?,?,?)",(i.ref.id,i.ref.model_dump_json(),""))
        if result.status=="failed":
            raise ValueError("페이지를 추출하지 못했습니다")
        return result
    except BaseException as exc:
        with db:
            db.execute("UPDATE assets SET status='failed',error=? WHERE id=?",("추출 중단" if isinstance(exc,asyncio.CancelledError) else str(exc)[:500],asset_id))
        raise


async def render_page(db, asset_id, page, runtime_dir,document_sha256=None):
    from .course_materials import document_metadata,checked_document_path
    folder,asset = asset_dir(db,asset_id)
    if asset["kind"] not in ("pdf","png","jpg"):
        raise ValueError("페이지 이미지가 없는 자료입니다")
    metadata=await document_metadata(db,asset_id,runtime_dir)
    if document_sha256 and metadata['sha256']!=document_sha256:
        raise HTTPException(409,'원본 문서가 변경되었습니다. 이전 필기를 새 문서에 표시하지 않습니다')
    if page<1 or page>metadata['total_pages']:
        raise KeyError("페이지를 찾을 수 없습니다")
    path = folder/f"document-{metadata['sha256']}-page-{page}.png"
    if path.is_file():return path
    source = checked_document_path(db,asset_id,metadata['sha256'])
    await worker(["render",source,path,runtime_dir,asset_id,asset["version"],asset["kind"],page])
    checked_document_path(db,asset_id,metadata['sha256'])
    if not path.is_file():
        raise ValueError("페이지 렌더링 실패")
    return path



async def render_image(db,asset_id,image_id,runtime_dir):
    folder,asset = asset_dir(db,asset_id)
    source = checked_material_path(db,asset)
    images = json.loads(asset["extraction"] or "{}").get("images",[])
    item = next((i for i in images if i["id"]==image_id),None)
    if item is None:
        raise KeyError("이미지를 찾을 수 없습니다")
    path = folder/item["path"]
    if not path.is_file():
        await worker(["image",source,path,runtime_dir,asset_id,asset["version"],asset["kind"],image_id])
    checked_material_path(db,asset)
    return path


def prune_cache(db,keep=None):
    limit = MAX_CACHE_BYTES
    files = []
    for directory in (data_dir(db)/"assets").glob("*"):
        if len(directory.name)!=32 or any(c not in "0123456789abcdef" for c in directory.name):
            continue
        files.extend(directory.glob("v*-page-*.png"))
        files.extend(directory.glob("v*-image-*"))
        files.extend(directory.glob('document-*-page-*.png'))
    total = sum(file.stat().st_size for file in files if file.is_file())
    for file in sorted(files,key=lambda file:file.stat().st_mtime):
        if total<=limit:
            break
        if file==keep:
            continue
        try:
            size = file.stat().st_size
            file.unlink()
            total -= size
        except OSError:
            pass
    return bool(keep and keep.stat().st_size>limit)


def save_note(db, session_id, text,anchor_ms=None):
    session(db,session_id)
    if anchor_ms is None:
        anchor_ms=db.execute("SELECT max(offset_ms+source_frames*1000/sample_rate) FROM recordings WHERE session_id=? AND status='recording'",(session_id,)).fetchone()[0]
    version = db.execute("SELECT COALESCE(MAX(version),0)+1 FROM notes WHERE session_id=?",(session_id,)).fetchone()[0]
    ref = SourceRef(id=f"{session_id}:note:{version}",kind="note",session_id=session_id,version=version)
    with db:
        db.execute("INSERT INTO notes VALUES (?,?,?,?,?,?)",(session_id,version,text,ref.id,now(),anchor_ms))
        db.execute("INSERT INTO sources(id,ref,text_snapshot) VALUES (?,?,?)",(ref.id,ref.model_dump_json(),text))
        index_source(db,ref,text)
    return ref


def list_materials(db, session_id):
    owner=session(db,session_id)
    assets = []
    for row in db.execute("SELECT a.* FROM assets a WHERE a.id IN (SELECT asset_id FROM session_assets WHERE session_id=? UNION SELECT asset_id FROM course_assets WHERE course_id=?) ORDER BY a.created_at",(session_id,owner['course_id'])):
        item = public_asset(db,dict(row))
        assets.append(item)
    note = db.execute("SELECT text,version,source_id,anchor_ms FROM notes WHERE session_id=? ORDER BY version DESC LIMIT 1",(session_id,)).fetchone()
    return {"assets":assets,"note":dict(note) if note else None}
