"""Read-only saved notebook snapshot and Mac vector PDF export."""
import asyncio,json,sys,tempfile
from pathlib import Path
from fastapi import HTTPException
from .course_materials import linked_asset,checked_document_path
from .models import PageDocumentInput
from .transcription import stop_process


def saved_pages(db,course_id,asset_id,digest):
    _,asset=linked_asset(db,course_id,asset_id)
    source=checked_document_path(db,asset_id,digest)
    if asset['kind']!='pdf':raise ValueError('PDF 자료에서 PDF 내보내기를 사용하세요')
    metadata=db.execute('SELECT metadata FROM asset_documents WHERE asset_id=? AND sha256=?',(asset_id,digest)).fetchone()
    if not metadata:raise HTTPException(409,'원본 페이지 정보를 다시 여세요')
    count=json.loads(metadata[0])['total_pages']
    # One SELECT snapshots every saved revision before asynchronous generation starts.
    rows=db.execute('SELECT d.page,r.ink FROM page_documents d JOIN page_document_revisions r ON r.document_id=d.id AND r.revision=d.revision WHERE d.course_id=? AND d.asset_id=? AND d.document_sha256=?',(course_id,asset_id,digest)).fetchall()
    ink={row['page']:json.loads(row['ink'])for row in rows}
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_drafts'").fetchone():
        prefix=json.dumps([course_id,asset_id,digest],separators=(',',':'))[:-1]+','
        for row in db.execute('SELECT key,value FROM native_drafts WHERE substr(key,1,?)=?',(len(prefix),prefix)):
            if not row['key'].endswith(']'):continue
            draft=json.loads(row['value']);page=json.loads(row['key'])[-1]
            if draft.get('dirty') is not False:
                saved=db.execute('SELECT r.text,r.ink FROM page_documents d JOIN page_document_revisions r ON r.document_id=d.id AND r.revision=d.revision WHERE d.course_id=? AND d.asset_id=? AND d.document_sha256=? AND d.page=?',(course_id,asset_id,digest,page)).fetchone()
                if draft.get('text','')!=(saved['text']if saved else '') or draft.get('ink',[])!=ink.get(page,[]):
                    raise HTTPException(409,f'{page}쪽의 미저장 초안을 확인하고 저장한 뒤 PDF를 내보내세요')
    pages=[]
    for page in range(1,count+1):
        value=PageDocumentInput(document_sha256=digest,expected_revision=0,text='',ink=ink.get(page,[]))
        pages.append(dict(page=page,ink=[item.model_dump(exclude_none=True)for item in value.ink]))
    return source,asset,pages


async def export_pdf(source,destination,pages):
    if sys.platform!='darwin':raise ValueError('현재 PDF 내보내기는 Mac 앱에서 사용할 수 있습니다')
    binary=Path(sys.executable).parent/'NotebookPDF'
    command=[str(binary)]if getattr(sys,'frozen',False)else['/usr/bin/swift','-module-cache-path',str(Path(tempfile.gettempdir())/'solasi-pdf-swift-cache'),str(Path(__file__).parent.parent/'macos/NotebookPDF.swift')]
    # Stream the input from disk: a long notebook need not fit the bridge's JSON limit.
    with tempfile.TemporaryFile()as payload:
        payload.write(json.dumps(pages,ensure_ascii=False).encode());payload.seek(0)
        process=await asyncio.create_subprocess_exec(*command,str(source),str(destination),stdin=payload,stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.PIPE)
        try:
            _,error=await asyncio.wait_for(process.communicate(),300)
            if process.returncode:raise ValueError('PDF 내보내기 실패: '+error.decode(errors='replace')[-300:])
        finally:await stop_process(process)
