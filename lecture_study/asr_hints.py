"""Bounded vocabulary inputs and evidence checks for transcription hints."""


def validate_hotwords(words):
    if not isinstance(words,list):raise ValueError('전사 용어 목록을 입력하세요')
    selected=[]
    for word in words:
        if not isinstance(word,str)or any(ord(c)<32 or ord(c)==127 for c in word)or '<|'in word or '|>'in word:raise ValueError('전사 용어의 제어 문자·특수 토큰을 제거하세요')
        word=' '.join(word.split())
        if word and word not in selected:selected.append(word)
    if len(', '.join(selected).encode('utf-8'))>200:raise ValueError('용어가 너무 많습니다. 핵심 명칭 몇 개만 입력하세요')
    return selected


def hint_snapshot(db,sid):
    from fastapi import HTTPException
    from .db import now,session
    from .models import Scope,SourceRef
    from .retrieval import list_terms,scope_ids,scope_assets,ref_in_scope
    from .materials import require_reviewed_material,material_sha256
    from .course_materials import current_document
    from .transcription import get_asr_terms
    session(db,sid);scope=Scope(session_id=sid);ids=scope_ids(db,scope);assets=scope_assets(db,scope,ids)
    documents={};selected=[];excluded=[];words=[]
    def current(evidence):
        ref=SourceRef.model_validate(evidence)
        row=db.execute('SELECT ref FROM searchable_chunks WHERE source_id=? LIMIT 1',(ref.id,)).fetchone()
        if not row or SourceRef.model_validate_json(row[0])!=ref or not ref_in_scope(db,ref,scope,ids,assets):return False
        require_reviewed_material(db,ref)
        if ref.asset_id:
            if ref.asset_id not in documents:
                documents[ref.asset_id]=None
                _,asset,inspected=current_document(db,ref.asset_id);documents[ref.asset_id]=(asset,inspected['sha256'])
            if documents[ref.asset_id]is None:return False
            asset,digest=documents[ref.asset_id]
            if material_sha256(asset,ref)!=digest:return False
        return True
    candidates=[{'term':word,'origin':'manual','evidence':[]}for word in get_asr_terms(db,sid)]
    candidates += [{'term':t['canonical'],'origin':'registered','term_id':t['id'],'term_revision':t['revision'],'evidence':t['evidence']}for t in list_terms(db,sid)]
    candidates += [{'term':r[0],'origin':'participant','evidence':[]}for r in db.execute('SELECT name FROM participants WHERE session_id=? AND active=1 ORDER BY name',(sid,))]
    for item in candidates:
        try:names=validate_hotwords([item['term']])
        except ValueError:excluded.append({'term':item['term'],'reason':'입력 형식·길이 확인 필요'});continue
        if not names or names[0]in words:continue
        word=names[0]
        try:validate_hotwords([*words,word])
        except ValueError:excluded.append({'term':word,'reason':'200바이트 한도'});continue
        try:valid=all(current(ref)for ref in item['evidence'])
        except (KeyError,ValueError,OSError,HTTPException):valid=False
        if not valid:excluded.append({'term':word,'reason':'근거 재검토 필요'});continue
        words.append(word);selected.append({**item,'term':word})
    # File hashes run off the event loop; edits and detachments may finish meanwhile.
    ids=scope_ids(db,scope);assets=scope_assets(db,scope,ids)
    revisions={t['id']:t['revision']for t in list_terms(db,sid)}
    checked=[]
    for item in selected:
        try:valid=(item['origin']!='registered'or revisions.get(item['term_id'])==item['term_revision'])and all(current(ref)for ref in item['evidence'])
        except (KeyError,ValueError,OSError,HTTPException):valid=False
        if valid:checked.append(item)
        else:excluded.append({'term':item['term'],'reason':'근거 재검토 필요'})
    selected=checked;words=[item['term']for item in selected]
    return {'prompt':', '.join(words),'hotwords':words,'selected':selected,'excluded':excluded,'documents':[{'asset_id':ident,'sha256':value[1]}for ident,value in documents.items()if value is not None],'prepared_at':now()}
