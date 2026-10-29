import asyncio
import json
from pathlib import Path
from fastapi import HTTPException
from .db import course,data_dir,new_id,now
from .models import SourceRef
from .materials import asset_dir,inspect_file,public_asset,worker
from .retrieval import index_source


def linked_asset(db,course_id,asset_id):
    course(db,course_id)
    if not db.execute('SELECT 1 FROM course_assets WHERE course_id=? AND asset_id=?',(course_id,asset_id)).fetchone():
        raise KeyError('과목에 연결된 자료가 아닙니다')
    return asset_dir(db,asset_id)


def list_course_materials(db,course_id):
    course(db,course_id)
    return {'assets':[public_asset(db,dict(row)) for row in db.execute('SELECT a.* FROM assets a JOIN course_assets c ON c.asset_id=a.id WHERE c.course_id=? ORDER BY a.created_at',(course_id,))]}


def current_document(db,asset_id):
    folder,asset=asset_dir(db,asset_id)
    path=Path(asset['external_path']) if asset['external_path'] else folder/f"original.{asset['kind']}"
    try:inspected=inspect_file(path)
    except (OSError,ValueError) as exc:raise HTTPException(409,'원본 파일 접근·내용을 확인하세요: '+str(exc)[:200]) from None
    return path,asset,inspected


def checked_document_path(db,asset_id,sha256):
    path,_,inspected=current_document(db,asset_id)
    if inspected['sha256']!=sha256:raise HTTPException(409,'원본 문서가 변경되었습니다. 이전 문서의 메모·필기는 보존됩니다')
    return path


async def document_metadata(db,asset_id,runtime_dir):
    # Keep the shared SQLite connection on the request thread during page refresh.
    source,asset,inspected=current_document(db,asset_id)
    if inspected['kind'] not in ('pdf','png','jpg'):raise ValueError('페이지 이미지가 없는 자료입니다')
    digest=inspected['sha256'];folder=data_dir(db)/'assets'/asset_id
    saved=db.execute('SELECT metadata FROM asset_documents WHERE asset_id=? AND sha256=?',(asset_id,digest)).fetchone()
    if saved:
        metadata=json.loads(saved[0])
    else:
        folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        output=folder/('metadata-'+new_id()+'.json')
        try:
            await worker(['metadata',source,output,runtime_dir,asset_id,asset['version'],inspected['kind']])
            pages=json.loads(output.read_text())
        finally:output.unlink(missing_ok=True)
        if not pages or any(p['page']!=i+1 or p['width']<=0 or p['height']<=0 for i,p in enumerate(pages)):
            raise ValueError('원본 페이지 정보를 읽을 수 없습니다')
        metadata={'asset_id':asset_id,'sha256':digest,'total_pages':len(pages),'pages':[]}
        for p in pages:
            ref=SourceRef(id=f'{asset_id}:document:{digest}:page:{p["page"]}',kind='material',asset_id=asset_id,page=p['page'],document_sha256=digest,coord_system='pdf_points' if inspected['kind']=='pdf' else 'pixels',source_width=p['width'],source_height=p['height'])
            metadata['pages'].append({**p,'ref':ref.model_dump()})
    checked_document_path(db,asset_id,digest)
    with db:
        db.execute('INSERT OR IGNORE INTO asset_documents VALUES (?,?,?,?)',(asset_id,digest,json.dumps(metadata,ensure_ascii=False),now()))
        for p in metadata['pages']:
            ref=SourceRef.model_validate(p['ref'])
            db.execute('INSERT OR IGNORE INTO sources(id,ref,text_snapshot) VALUES (?,?,?)',(ref.id,ref.model_dump_json(),''))
        db.execute("UPDATE assets SET sha256=?,size=?,mtime_ns=?,kind=?,status=CASE WHEN extraction IS NOT NULL AND coalesce(extraction_sha256,'')!=? THEN 'stale' ELSE status END WHERE id=?",(digest,inspected['size'],inspected['mtime_ns'],inspected['kind'],digest,asset_id))
    return metadata


def page_document(db,course_id,asset_id,page,digest,revision=None):
    linked_asset(db,course_id,asset_id)
    metadata=db.execute('SELECT metadata FROM asset_documents WHERE asset_id=? AND sha256=?',(asset_id,digest)).fetchone()
    if metadata is None:raise HTTPException(409,'원본 페이지 정보를 다시 여세요')
    if not 1<=page<=json.loads(metadata[0])['total_pages']:raise KeyError('페이지를 찾을 수 없습니다')
    if revision is not None and revision<1:raise ValueError('메모 버전을 확인하세요')
    row=db.execute('SELECT d.id,d.course_id,d.asset_id,d.document_sha256,d.page,r.revision,r.text,r.ink,r.source_id,r.updated_at FROM page_documents d JOIN page_document_revisions r ON r.document_id=d.id AND r.revision=coalesce(?,d.revision) WHERE d.course_id=? AND d.asset_id=? AND d.document_sha256=? AND d.page=?',(revision,course_id,asset_id,digest,page)).fetchone()
    if revision is not None and not row:raise KeyError('메모 버전을 찾을 수 없습니다')
    if not row:return {'id':None,'course_id':course_id,'asset_id':asset_id,'document_sha256':digest,'page':page,'revision':0,'text':'','ink':[],'source_id':None,'updated_at':None}
    result=dict(row);result['ink']=json.loads(result['ink'])
    return result


def save_page_document(db,course_id,asset_id,page,body):
    linked_asset(db,course_id,asset_id)
    checked_document_path(db,asset_id,body.document_sha256)
    page_document(db,course_id,asset_id,page,body.document_sha256)
    # A writer lock makes the revision comparison and snapshot insertion atomic across app windows.
    db.execute('BEGIN IMMEDIATE')
    try:
        row=db.execute('SELECT id,revision FROM page_documents WHERE course_id=? AND asset_id=? AND document_sha256=? AND page=?',(course_id,asset_id,body.document_sha256,page)).fetchone()
        if (row['revision'] if row else 0)!=body.expected_revision:raise HTTPException(409,'다른 창에서 페이지를 저장했습니다. 현재 메모와 초안을 비교하세요')
        ident=row['id'] if row else new_id();revision=body.expected_revision+1
        ref=SourceRef(id=f'{ident}:page-note:{revision}',kind='page_note',course_id=course_id,asset_id=asset_id,document_id=ident,document_sha256=body.document_sha256,page=page,version=revision)
        source_text='\n'.join(text for text in [body.text,*[item.text for item in body.ink if item.tool=='text']] if text)
        db.execute('INSERT INTO sources(id,ref,text_snapshot) VALUES (?,?,?)',(ref.id,ref.model_dump_json(),source_text))
        if not row:db.execute('INSERT INTO page_documents VALUES (?,?,?,?,?,?)',(ident,course_id,asset_id,body.document_sha256,page,revision))
        else:db.execute('UPDATE page_documents SET revision=? WHERE id=?',(revision,ident))
        ink=json.dumps([s.model_dump(exclude_none=True) for s in body.ink],ensure_ascii=False,separators=(',',':'))
        db.execute('INSERT INTO page_document_revisions VALUES (?,?,?,?,?,?)',(ident,revision,body.text,ink,ref.id,now()))
        from .handwriting import ink_hash
        db.execute("UPDATE ink_recognitions SET status='stale' WHERE document_id=? AND ink_hash!=? AND status!='stale'",(ident,ink_hash(json.loads(ink))))
        index_source(db,ref,source_text)
        checked_document_path(db,asset_id,body.document_sha256)
        db.commit()
    except BaseException:db.rollback();raise
    return page_document(db,course_id,asset_id,page,body.document_sha256)
