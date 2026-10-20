"""Local ink recognition proposals, separate from user notes and approved sources."""
import asyncio,hashlib,json,math,sys,tempfile
from pathlib import Path
from fastapi import HTTPException
from .db import data_dir,new_id,now
from .course_materials import page_document,checked_document_path
from .models import SourceRef,PageDocumentInput
from .retrieval import index_source


def ink_hash(ink):
    return hashlib.sha256(json.dumps(ink,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def capture_ink(db,course_id,asset_id,page,digest):
    doc=page_document(db,course_id,asset_id,page,digest)
    source=checked_document_path(db,asset_id,digest)
    if not doc['id']:raise ValueError('필기를 먼저 저장하세요')
    meta=json.loads(db.execute('SELECT metadata FROM asset_documents WHERE asset_id=? AND sha256=?',(asset_id,digest)).fetchone()[0])
    size=next(p for p in meta['pages'] if p['page']==page)
    from .materials import is_handwritten
    return doc|{'ink_hash':ink_hash(doc['ink']),'page_width':size['width'],'page_height':size['height'],'page_source':str(source) if is_handwritten(db,asset_id) else None}


def ink_payload(snapshot):
    ink=PageDocumentInput(document_sha256=snapshot['document_sha256'],expected_revision=snapshot['revision'],text='',ink=snapshot['ink']).ink
    width,height=snapshot['page_width'],snapshot['page_height']
    if not all(isinstance(v,(int,float)) and math.isfinite(v) and 0<v<=100000 for v in (width,height)):raise ValueError('페이지 크기를 확인하세요')
    return {'page_width':width,'page_height':height,'strokes':[s.model_dump(exclude_none=True) for s in ink if s.tool=='pen']}


def get_recognition(db,ident):
    row=db.execute('SELECT * FROM ink_recognitions WHERE id=?',(ident,)).fetchone()
    if row is None:raise KeyError('인식 후보를 찾을 수 없습니다')
    item=dict(row);item['result']=json.loads(item['result']);return item


def list_recognitions(db,course_id,asset_id,page,digest):
    page_document(db,course_id,asset_id,page,digest)
    return [get_recognition(db,r[0]) for r in db.execute('SELECT id FROM ink_recognitions WHERE course_id=? AND asset_id=? AND page=? AND document_sha256=? ORDER BY created_at DESC LIMIT 30',(course_id,asset_id,page,digest))]


def save_recognition(db,snapshot,result):
    engine=result.get('engine');regions=result.get('regions')
    if not isinstance(engine,str) or not 1<=len(engine)<=200 or not isinstance(regions,list) or len(regions)>500:raise ValueError('인식 결과 형식을 확인하세요')
    for r in regions:
        b=r.get('bbox');t=r.get('text')
        if not isinstance(b,list) or len(b)!=4 or any(not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 or v>1 for v in b) or b[0]+b[2]>1.001 or b[1]+b[3]>1.001:raise ValueError('인식 영역을 확인하세요')
        if not isinstance(t,str) or len(t)>20000:raise ValueError('인식문 길이를 확인하세요')
    text='\n'.join(r['text'] for r in regions).strip()
    if len(text)>200000:raise ValueError('인식문이 너무 깁니다')
    current=capture_ink(db,snapshot['course_id'],snapshot['asset_id'],snapshot['page'],snapshot['document_sha256'])
    stale=current['ink_hash']!=snapshot['ink_hash']
    old=db.execute("SELECT id FROM ink_recognitions WHERE document_id=? AND ink_hash=? AND engine=? AND status!='stale'",(snapshot['id'],snapshot['ink_hash'],engine)).fetchone()
    if old:return get_recognition(db,old[0])
    ident=new_id()
    with db:db.execute('INSERT INTO ink_recognitions(id,document_id,course_id,asset_id,document_sha256,page,page_revision,ink_hash,engine,status,text,result,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',(ident,snapshot['id'],snapshot['course_id'],snapshot['asset_id'],snapshot['document_sha256'],snapshot['page'],snapshot['revision'],snapshot['ink_hash'],engine,'stale' if stale else 'candidate',text,json.dumps(result,ensure_ascii=False),now()))
    return get_recognition(db,ident)


def approve_recognition(db,ident,text,expected_ink_hash):
    if not isinstance(text,str) or not text.strip() or len(text)>200000:raise ValueError('확인한 인식문을 입력하세요')
    db.execute('BEGIN IMMEDIATE')
    try:
        r=get_recognition(db,ident)
        current=capture_ink(db,r['course_id'],r['asset_id'],r['page'],r['document_sha256'])
        if current['ink_hash']!=expected_ink_hash or r['ink_hash']!=expected_ink_hash or r['status']=='stale':raise HTTPException(409,'필기가 변경되었습니다. 최신 인식문을 검토하세요')
        if r['status']=='approved':
            if text.strip()!=r['approved_text']:raise HTTPException(409,'이미 적용한 인식문입니다. 새 후보를 검토하세요')
            return SourceRef.model_validate_json(db.execute('SELECT ref FROM sources WHERE id=?',(r['source_id'],)).fetchone()[0])
        if r['status']=='rejected':raise HTTPException(409,'거절한 후보입니다. 다시 인식하세요')
        regions=r['result']['regions'];bbox=None
        if regions:
            xs=[a['bbox'] for a in regions];x=min(a[0] for a in xs);y=min(a[1] for a in xs)
            bbox=(x,y,min(1-x,max(a[0]+a[2] for a in xs)-x),min(1-y,max(a[1]+a[3] for a in xs)-y))
        ref=SourceRef(id=ident+':ink:1',kind='ink_note',course_id=r['course_id'],asset_id=r['asset_id'],document_id=r['document_id'],document_sha256=r['document_sha256'],page=r['page'],version=r['page_revision'],bbox=bbox,coord_system='normalized',source_width=current['page_width'],source_height=current['page_height'])
        db.execute('INSERT INTO sources(id,ref,text_snapshot) VALUES (?,?,?)',(ref.id,ref.model_dump_json(),text.strip()))
        db.execute("UPDATE ink_recognitions SET status='approved',approved_text=?,source_id=?,approved_at=? WHERE id=?",(text.strip(),ref.id,now(),ident))
        index_source(db,ref,text.strip());db.commit();return ref
    except BaseException:db.rollback();raise
    finally:
        if db.in_transaction:db.rollback()


def reject_recognition(db,ident):
    r=get_recognition(db,ident)
    if r['status']!='candidate':raise HTTPException(409,'검토 대기 후보만 거절할 수 있습니다')
    with db:db.execute("UPDATE ink_recognitions SET status='rejected' WHERE id=?",(ident,))
    return get_recognition(db,ident)


async def recognize_ink(snapshot,image_path=None):
    payload=ink_payload(snapshot)
    if not payload['strokes'] and not snapshot.get('page_source'):return {'engine':'apple-vision-accurate-v3','regions':[]}
    if sys.platform!='darwin':raise ValueError('손글씨 인식은 현재 Mac에서 지원합니다')
    binary=Path(sys.executable).parent/'HandwritingRecognition'
    command=[str(binary)] if getattr(sys,'frozen',False) else ['/usr/bin/swift','-module-cache-path',str((Path(tempfile.gettempdir())/'solasi-handwriting-swift-cache').resolve()),str(Path(__file__).parent.parent/'macos/HandwritingRecognition.swift')]
    if image_path is not None:command+=['--image',str(image_path)]
    if snapshot.get('page_source'):command+=['--page-source',snapshot['page_source'],str(snapshot['page'])]
    process=await asyncio.create_subprocess_exec(*command,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    try:
        output,error=await asyncio.wait_for(process.communicate(json.dumps(payload).encode()),90)
        if process.returncode:raise ValueError('로컬 손글씨 인식 실패: '+error.decode(errors='replace')[-200:])
        return json.loads(output)
    finally:
        if process.returncode is None:
            process.kill();await process.wait()


async def recognize_local_ink(snapshot,manager,before_local=None,model='qwen3.5:4b'):
    from .models import ProviderConfig
    if model not in ('qwen3.5:4b','gemma4:12b'):raise ValueError('비교한 손글씨 인식 모델을 선택하세요')
    strokes=ink_payload(snapshot)['strokes']
    if not strokes and not snapshot.get('page_source'):return {'engine':model,'regions':[]}
    with tempfile.TemporaryDirectory(prefix='solasi-ink-') as folder:
        image=Path(folder)/'ink.png'
        vision=await recognize_ink(snapshot,image_path=image)
        from PIL import Image,ImageOps,UnidentifiedImageError
        source=snapshot.get('page_source')
        if source and not strokes:
            try:
                with Image.open(source)as original:
                    if max(original.size)<2048:ImageOps.exif_transpose(original).convert('RGB').save(image)
            except UnidentifiedImageError:pass  # PDF pages use the native renderer, regardless of extension.
        with Image.open(image)as original:
            if model=='qwen3.5:4b' and max(original.size)<2048:
                scale=min(3,2048/max(original.size))
                original.resize(tuple(round(d*scale)for d in original.size),Image.Resampling.LANCZOS).save(image)
        identity=await manager.status(model)
        result=await manager.generate(ProviderConfig(provider='local',model=model,vision=True,context_limit=8192),[{'role':'system','content':'보이는 문자와 수식만 그대로 전사하세요. 설명하거나 문장을 완성하지 마세요. 이미지 가장자리에서 잘렸거나 판독할 수 없는 부분은 [판독 불가]로 남기세요. 수학 지식으로 기호·단어를 정정하거나 추가하지 마세요. 부호·첨자·분수·극한의 방향을 원본 그대로 보존하고, 도형의 관계는 추측하지 마세요.'},{'role':'user','content':'이 이미지의 글을 읽는 순서대로 그대로 전사하세요.'}],[image],None,output_limit=2048,before_local=before_local)
    metadata={'finish_reason':result.get('finish_reason'),'usage':result.get('usage',{}),'edge_touching':any(r.get('edge_touching')for r in vision.get('regions',[]))}
    engine=model+'/'+identity['digest']+'/literal-v2'
    if snapshot.get('page_source'):
        return {'engine':engine+'/page','regions':[{'bbox':[0,0,1,1],'text':result['text'],'candidates':[]}],**metadata}
    points=[p for s in strokes for p in s['points']];padding=max(s['width'] for s in strokes)
    x=max(0,min(p['x'] for p in points)-padding);y=max(0,min(p['y'] for p in points)-padding)
    right=min(1,max(p['x'] for p in points)+padding);bottom=min(1,max(p['y'] for p in points)+padding)
    return {'engine':engine,'regions':[{'bbox':[x,y,right-x,bottom-y],'text':result['text'],'candidates':[]}],**metadata}
