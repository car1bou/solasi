import asyncio
import json
import math
import re
import struct
import sqlite3
from contextlib import closing
import unicodedata
from .db import now,new_id,session,data_dir,course
from .models import Scope,SourceRef,Evidence,SearchResult
from .direct_models import DirectEmbeddings, EmbeddingInputTooLong, EMBEDDING_FORMAT


def normalize(text):
    return ''.join(unicodedata.normalize('NFKC',text).lower().split())


def index_source(db,ref,text):
    if ref.kind not in ('material','note','page_note','transcript') or not text.strip(): return
    saved=db.execute('SELECT ref,text_snapshot FROM sources WHERE id=? AND deleted=0',(ref.id,)).fetchone()
    if not saved or SourceRef.model_validate_json(saved['ref'])!=ref or saved['text_snapshot']!=text:
        raise ValueError('출처 스냅샷이 일치하지 않습니다')
    ordinal=0
    for paragraph in re.split(r'\n\s*\n|(?=^#{1,6}\s)',text,flags=re.M):
        blocks=paragraph.splitlines() if paragraph.lstrip().startswith('|') else [paragraph]
        for block in blocks:
            block=block.strip()
            for start in range(0,len(block),512):
                chunk=block[start:start+512];ident=ref.id+':chunk:'+str(ordinal)
                if db.execute('INSERT OR IGNORE INTO chunks VALUES (?,?,?,?,?)',(ident,ref.id,ordinal,chunk,normalize(chunk))).rowcount:
                    db.execute('INSERT INTO chunk_search(chunk_id,search_text) VALUES (?,?)',(ident,normalize(chunk)))
                ordinal+=1


def backfill_sources(db):
    with db:
        for row in db.execute("SELECT * FROM sources WHERE deleted=0 AND text_snapshot!='' AND NOT EXISTS(SELECT 1 FROM chunks WHERE source_id=sources.id)").fetchall():
            index_source(db,SourceRef.model_validate_json(row['ref']),row['text_snapshot'])


def scope_ids(db,scope):
    if scope.course_id:
        course(db,scope.course_id)
        return []
    owner=session(db,scope.session_id)
    ids=[owner['id']]
    if owner['kind']=='lecture' and owner['course_id']:
        ids=[r[0] for r in db.execute("SELECT id FROM sessions WHERE course_id=? AND kind='lecture' AND deleted=0 ORDER BY lecture_no,started_at,id",(owner['course_id'],))]
    if scope.mode=='current': return [owner['id']]
    if scope.mode=='selected':
        selected=list(dict.fromkeys(scope.lecture_ids))
        if not selected or not set(selected)<=set(ids): raise ValueError('같은 과목의 회차를 선택하세요')
        return selected
    return ids


def scope_course(db,scope):
    if scope.course_id:
        course(db,scope.course_id)
        return scope.course_id
    return session(db,scope.session_id)['course_id']


def scope_assets(db,scope,ids=None):
    ids=scope_ids(db,scope) if ids is None else ids
    cid=scope_course(db,scope)
    assets={r[0] for r in db.execute('SELECT asset_id FROM session_assets WHERE session_id IN (SELECT value FROM json_each(?)) UNION SELECT asset_id FROM course_assets WHERE course_id=?',(json.dumps(ids),cid))}
    if scope.asset_id:
        if scope.asset_id not in assets:raise ValueError('범위 밖의 자료입니다')
        return {scope.asset_id}
    return assets


def ref_in_scope(db,ref,scope,ids=None,assets=None):
    ids=scope_ids(db,scope) if ids is None else ids
    assets=scope_assets(db,scope,ids) if assets is None else assets
    if ref.kind in ('material','page_note'):
        if ref.asset_id not in assets:return False
        if ref.kind=='page_note' and ref.course_id!=scope_course(db,scope):return False
    elif ref.session_id not in ids:return False
    if scope.asset_id and ref.asset_id!=scope.asset_id:return False
    if scope.page is not None and ref.page!=scope.page:return False
    if scope.document_sha256:
        digest=ref.document_sha256
        if ref.kind=='material' and not digest:
            asset=db.execute('SELECT extraction_sha256 FROM assets WHERE id=?',(ref.asset_id,)).fetchone()
            digest=asset[0] if asset else None
        if digest!=scope.document_sha256:return False
    return True


def scope_key(db,sid):
    if isinstance(sid,Scope):
        if sid.course_id:course(db,sid.course_id);return 'course:'+sid.course_id
        sid=sid.session_id
    owner=session(db,sid)
    return 'course:'+owner['course_id'] if owner['kind']=='lecture' and owner['course_id'] else 'session:'+sid


def list_terms(db,sid):
    key=scope_key(db,sid)
    result=[]
    for row in db.execute('SELECT t.id,t.scope_key,v.* FROM terms t JOIN term_versions v ON t.id=v.term_id WHERE t.scope_key=? AND v.revision=(SELECT max(revision) FROM term_versions WHERE term_id=t.id) ORDER BY v.canonical',(key,)):
        item=dict(row)
        for field in ('aliases','evidence'): item[field]=json.loads(item[field])
        result.append(item)
    return result


def save_term(db,sid,canonical,aliases,explanation,evidence,term_id=None):
    key=scope_key(db,sid);ids=scope_ids(db,Scope(session_id=sid));canonical=canonical.strip()
    if not canonical or len(canonical)>120 or len(explanation)>10000 or len(aliases)>30: raise ValueError('용어와 설명 길이를 확인하세요')
    if any(not isinstance(alias,str) or len(alias)>120 for alias in aliases): raise ValueError('별칭을 확인하세요')
    aliases=list(dict.fromkeys(alias.strip() for alias in aliases if alias.strip()))
    if len(evidence)>32: raise ValueError('근거를 32개 이하로 선택하세요')
    checked=[]
    for ref in evidence:
        saved=db.execute('SELECT * FROM sources WHERE id=? AND deleted=0',(ref.id,)).fetchone()
        if not saved or SourceRef.model_validate_json(saved['ref'])!=ref: raise ValueError('근거가 실제 출처와 다릅니다')
        belongs=ref_in_scope(db,ref,Scope(session_id=sid),ids)
        if not belongs: raise ValueError('범위 밖의 근거입니다')
        checked.append(ref.model_dump())
    if term_id and not db.execute('SELECT 1 FROM terms WHERE id=? AND scope_key=?',(term_id,key)).fetchone(): raise KeyError('개념을 찾을 수 없습니다')
    ident=term_id or new_id()
    with db:
        db.execute('INSERT OR IGNORE INTO terms VALUES (?,?)',(ident,key))
        revision=db.execute('SELECT coalesce(max(revision),0)+1 FROM term_versions WHERE term_id=?',(ident,)).fetchone()[0]
        db.execute('INSERT INTO term_versions VALUES (?,?,?,?,?,?,?)',(ident,revision,canonical,json.dumps(aliases,ensure_ascii=False),explanation,json.dumps(checked,ensure_ascii=False),now()))
    return ident


def eligible_chunks(db,ids,cutoff,cutoff_session_id=None,scope=None):
    if scope is None:
        if not ids:return []
        scope=Scope(session_id=ids[0])
    assets=scope_assets(db,scope,ids)
    rows=db.execute("SELECT * FROM searchable_chunks WHERE json_extract(ref,'$.session_id') IN (SELECT value FROM json_each(?)) OR json_extract(ref,'$.asset_id') IN (SELECT value FROM json_each(?))",(json.dumps(ids),json.dumps(list(assets)))).fetchall()
    result=[]
    for row in rows:
        ref=SourceRef.model_validate_json(row['ref'])
        if not ref_in_scope(db,ref,scope,ids,assets):continue
        if cutoff is not None and ref.kind=='transcript' and (cutoff_session_id is None or ref.session_id==cutoff_session_id) and ref.end_ms>cutoff:continue
        result.append(dict(row))
    return result


def label_for(db,ref,ids,course_id=None):
    if ref.kind in ('material','page_note'):
        asset=db.execute('SELECT filename FROM assets WHERE id=?',(ref.asset_id,)).fetchone()
        owner=db.execute('SELECT s.title,s.lecture_no FROM sessions s JOIN session_assets sa ON s.id=sa.session_id WHERE sa.asset_id=? AND s.id IN (SELECT value FROM json_each(?)) ORDER BY s.lecture_no,s.started_at LIMIT 1',(ref.asset_id,json.dumps(ids))).fetchone()
        if course_id:owner=db.execute('SELECT title,NULL AS lecture_no FROM courses WHERE id=?',(course_id,)).fetchone()
        if ref.course_id:owner=db.execute('SELECT title,NULL AS lecture_no FROM courses WHERE id=?',(ref.course_id,)).fetchone()
        if owner is None:owner=db.execute('SELECT c.title,NULL AS lecture_no FROM courses c JOIN course_assets ca ON ca.course_id=c.id WHERE ca.asset_id=? ORDER BY c.created_at LIMIT 1',(ref.asset_id,)).fetchone()
        tail=(asset[0] if asset else '자료')+((' · '+str(ref.page)+'쪽') if ref.page else '')
        if ref.kind=='page_note':tail+=' · 페이지 메모'
    else:
        owner=db.execute('SELECT title,lecture_no FROM sessions WHERE id=?',(ref.session_id,)).fetchone()
        tail='노트' if ref.kind=='note' else str(ref.start_ms//60000)+':'+str(ref.start_ms//1000%60).zfill(2)
    title=owner['title']+(' · '+str(owner['lecture_no'])+'회차' if owner['lecture_no'] else '') if owner else '기록'
    return title+' · '+tail


def keyword_rank(db,query,sid,rows,limit):
    terms=[normalize(token) for token in re.findall(r'\w+',query) if token]
    # shortcut: common Korean particles only; add a morphological tokenizer after observed search misses.
    for token in list(terms):
        if re.fullmatch(r'[가-힣]+',token):
            stem=re.sub(r'(?:에서|에게|으로|이란|이다|은|는|이|가|을|를|도|와|과|의|에|로|란)$','',token)
            if len(stem)>=2 and stem!=token: terms.append(stem)
    query_norm=normalize(query)
    for term in list_terms(db,sid):
        names=[term['canonical'],*term['aliases']]
        if any(normalize(name) in query_norm for name in names): terms.extend(normalize(name) for name in names)
    terms=list(dict.fromkeys(terms))[:40]
    if not terms or not rows: return []
    long=[term for term in terms if len(term)>=3]
    ranked=[]
    if long:
        match=' OR '.join('"'+term.replace('"','""')+'"' for term in long)
        ranked=[row[0] for row in db.execute('SELECT chunk_id FROM chunk_search WHERE chunk_search MATCH ? AND chunk_id IN (SELECT value FROM json_each(?)) ORDER BY bm25(chunk_search) LIMIT ?',(match,json.dumps([row['id'] for row in rows]),limit*4))]
    partial=sorted((row for row in rows if any(term in row['search_text'] for term in terms)),key=lambda row:(-sum(term in row['search_text'] for term in terms),row['id']))
    return list(dict.fromkeys(ranked+[row['id'] for row in partial]))[:limit*4]


def evidence_shape(text):
    text=unicodedata.normalize('NFKC',text).lower()
    protected=tuple(re.findall(r'[-+−]?\d+(?:[.,:/-]\d+)*|\b(?:not|no|never|without|cannot|can.t|won.t|don.t|doesn.t|didn.t)\b|[월화수목금토일]요일|주말|주중|이번|금주|차주|오늘|어제|내일|모레|지난|다음|\b(?:january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\b|[영일이삼사오육칠팔구십백천만억조]+\s*(?:개|일|명|원|회|주|년|월|분|초|시간|개월|퍼센트)|(?:스물|스무|서른|마흔|쉰|예순|일흔|여든|아흔|열|한|두|세|네|다섯|여섯|일곱|여덟|아홉)+\s*(?:개|명|번|회|주|시|시간|살|마리|장|대|권|잔|줄|달|곳|가지)|\b안[가-힣]*|[가-힣]*(?:아니|아닌|아님|아닙|아닐|않|없|못|불가|금지|취소|보류|제외|반대|무효|거절|미지원|미정|확정|완료|예정|제안|검토)[가-힣]*',text))
    compact=''.join(text.split())
    return compact,protected,{compact[i:i+3] for i in range(len(compact)-2)}


def diverse_evidence(evidence,limit):
    unique=[];deferred=[];shapes=[]
    for item in evidence:
        text,facts,grams=evidence_shape(item.text)
        # shortcut: conservative wording overlap, not a calibrated semantic equivalence classifier.
        repeated=any(text==old or facts==old_facts and len(text)>=40 and len(old)>=40 and 2*len(grams&old_grams)>=.9*(len(grams)+len(old_grams)) for old,old_facts,old_grams in shapes)
        if repeated:deferred.append(item)
        else:unique.append(item);shapes.append((text,facts,grams))
    return (unique+deferred)[:limit]


def collect_evidence(db,ranked,rows,ids,limit,course_id=None):
    by_id={row['id']:row for row in rows};selected={};by_source={}
    for row in rows: by_source.setdefault(row['source_id'],{})[row['ordinal']]=row
    for ident in ranked:
        row=by_id[ident];source=row['source_id']
        selected.setdefault(source,{})
        for ordinal in range(row['ordinal']-1,row['ordinal']+2):
            neighbor=by_source[source].get(ordinal)
            if neighbor: selected[source][ordinal]=neighbor['text']
    result=[]
    for source,chunks in selected.items():
        row=next(iter(by_source[source].values()));ref=SourceRef.model_validate_json(row['ref'])
        result.append(Evidence(ref=ref,text='\n\n'.join(chunks[n] for n in sorted(chunks)),label=label_for(db,ref,ids,course_id)))
    return diverse_evidence(result,limit)


def concept_detail(db,sid,term_id):
    term=next((term for term in list_terms(db,sid) if term['id']==term_id),None)
    if term is None: raise KeyError('개념을 찾을 수 없습니다')
    ids=scope_ids(db,Scope(session_id=sid));rows=eligible_chunks(db,ids,None)
    ranked=keyword_rank(db,' '.join([term['canonical'],*term['aliases']]),sid,rows,8)
    return {'term':term,'related_evidence':[e.model_dump() for e in collect_evidence(db,ranked,rows,ids,8)]}


def index_status(db):
    saved=db.execute("SELECT value FROM settings WHERE key='active_embedding_index'").fetchone()
    active=db.execute('SELECT * FROM embedding_sets WHERE id=? AND status=\'ready\'',(json.loads(saved[0]),)).fetchone() if saved else None
    if active is None: return {'ready':False,'index_id':None}
    missing=db.execute('SELECT count(*) FROM searchable_chunks c WHERE NOT EXISTS(SELECT 1 FROM embeddings e WHERE e.index_id=? AND e.chunk_id=c.id)',(active['id'],)).fetchone()[0]
    return {'ready':True,'index_id':active['id'],'model':active['model'],'digest':active['digest'],'dim':active['dim'],'format':active['format'],'unindexed_chunks':missing}


async def model_digest(client,model,base_url=""):
    if isinstance(client,DirectEmbeddings):return (await client.status(model))['digest']
    response=await client.get(base_url+'/api/tags');response.raise_for_status()
    models=response.json().get('models',[])
    if not isinstance(models,list) or any(not isinstance(row,dict) for row in models): raise ValueError('로컬 모델 목록이 유효하지 않습니다')
    actual=next((row for row in models if row.get('name') in (model,model+':latest')),None)
    if not actual or not isinstance(actual.get('digest'),str) or not re.fullmatch(r'[a-f0-9]{64}',actual['digest']): raise ValueError('다운로드한 로컬 모델을 선택하세요')
    if model.endswith(':cloud') or actual.get('remote_model') or actual.get('remote_host'): raise ValueError('다운로드한 로컬 모델을 선택하세요')
    return actual['digest']


def vector(values):
    if not isinstance(values,list) or not 0<len(values)<=8192 or any(type(v) not in (float,int) for v in values): raise ValueError('임베딩 벡터가 유효하지 않습니다')
    try: packed=struct.pack('<'+'f'*len(values),*values)
    except (OverflowError,struct.error): raise ValueError('임베딩 값 범위를 확인하세요') from None
    values=struct.unpack('<'+'f'*len(values),packed)
    if not all(math.isfinite(v) for v in values): raise ValueError('임베딩 값 범위를 확인하세요')
    norm=math.sqrt(sum(v*v for v in values))
    if not math.isfinite(norm) or norm==0: raise ValueError('임베딩 벡터가 유효하지 않습니다')
    return tuple(v/norm for v in values)


def embedding_format(model,client=None):
    if isinstance(client,DirectEmbeddings):return EMBEDDING_FORMAT
    family=model.split(':')[0]
    return family+'-search-v1/chunk512-v1' if family in ('embeddinggemma','embeddinggemma-2') else 'plain-v1/chunk512-v1'


async def embed_parts(client,model,text,title='',query=False):
    prefix=('task: search result | query: ' if query else 'title: '+(title or 'none')+' | text: ') if model.split(':')[0] in ('embeddinggemma','embeddinggemma-2') else ''
    if isinstance(client,DirectEmbeddings):
        try:return [vector(await client.embed(model,prefix+text))]
        except EmbeddingInputTooLong:
            if len(text)<=16:raise ValueError('임베딩 입력 한도가 너무 작습니다')
            middle=len(text)//2
            return await embed_parts(client,model,text[:middle],title,query)+await embed_parts(client,model,text[middle:],title,query)
    response=await client.post('/api/embed',json={'model':model,'input':[prefix+text],'truncate':False})
    if response.status_code in (400,413) and response.json().get('error')=='the input length exceeds the context length':
        if len(text)<=16: raise ValueError('임베딩 입력 한도가 너무 작습니다')
        middle=len(text)//2
        return await embed_parts(client,model,text[:middle],title,query)+await embed_parts(client,model,text[middle:],title,query)
    response.raise_for_status();body=response.json()
    values=body.get('embeddings')
    if not isinstance(values,list) or len(values)!=1: raise ValueError('임베딩 응답 개수가 다릅니다')
    return [vector(values[0])]


async def rebuild_embeddings(db,model,client,job_id=None):
    digest=await model_digest(client,model)
    if isinstance(client,DirectEmbeddings):
        if not (await client.status(model))['embedding']:raise ValueError('임베딩을 지원하는 로컬 모델을 선택하세요')
    else:
        response=await client.post('/api/show',json={'model':model});response.raise_for_status()
        if response.json().get('remote_model') or response.json().get('remote_host'): raise ValueError('원격 임베딩 모델은 사용할 수 없습니다')
        if 'embedding' not in response.json().get('capabilities',[]): raise ValueError('임베딩을 지원하는 로컬 모델을 선택하세요')
    rows=[dict(row) for row in db.execute('SELECT * FROM searchable_chunks ORDER BY id')]
    ident=new_id();dim=None
    with db:
        db.execute('INSERT INTO embedding_sets VALUES (?,?,?,NULL,?,\'building\',?)',(ident,model,digest,embedding_format(model,client),now()))
    try:
        for i,row in enumerate(rows):
            while db.execute("SELECT 1 FROM recordings WHERE status='recording' UNION ALL SELECT 1 FROM transcript_ranges WHERE status IN ('queued','running') LIMIT 1").fetchone():
                if job_id:
                    with db: db.execute('UPDATE jobs SET result=? WHERE id=?',(json.dumps({'paused_reason':'녹음·전사 중 · 색인 대기','completed_chunks':i,'total_chunks':len(rows)},ensure_ascii=False),job_id))
                await asyncio.sleep(.5)
            ref=SourceRef.model_validate_json(row['ref'])
            title=db.execute('SELECT filename FROM assets WHERE id=?',(ref.asset_id,)).fetchone() if ref.kind in ('material','page_note') else db.execute('SELECT title FROM sessions WHERE id=?',(ref.session_id,)).fetchone()
            parts=await embed_parts(client,model,row['text'],title[0] if title else '')
            for part in parts:
                dim=dim or len(part)
                if len(part)!=dim: raise ValueError('임베딩 차원이 변경되었습니다')
            with db:
                for n,part in enumerate(parts): db.execute('INSERT INTO embeddings VALUES (?,?,?,?)',(ident,row['id'],n,struct.pack('<'+'f'*len(part),*part)))
                if job_id: db.execute('UPDATE jobs SET result=? WHERE id=?',(json.dumps({'completed_chunks':i+1,'total_chunks':len(rows)}),job_id))
            await asyncio.sleep(0)
        if dim is None: raise ValueError('색인할 원문이 없습니다')
        if await model_digest(client,model)!=digest: raise ValueError('임베딩 모델이 변경되었습니다. 재색인하세요')
        with db:
            db.execute("UPDATE embedding_sets SET status='ready',dim=? WHERE id=?",(dim,ident))
            db.execute("INSERT OR REPLACE INTO settings VALUES ('active_embedding_index',?)",(json.dumps(ident),))
        return index_status(db)
    except BaseException:
        with db: db.execute("UPDATE embedding_sets SET status='failed' WHERE id=?",(ident,))
        raise


def semantic_rank(db,index,rows,query_vectors,limit):
    allowed=[row['id'] for row in rows];scores={}
    # A separate WAL reader keeps this query stable while a completed rebuild switches indexes.
    with closing(sqlite3.connect(data_dir(db).resolve().joinpath('app.sqlite3').as_uri()+'?mode=ro',uri=True)) as reader:
        for ident,blob in reader.execute('SELECT chunk_id,vector FROM embeddings WHERE index_id=? AND chunk_id IN (SELECT value FROM json_each(?))',(index['index_id'],json.dumps(allowed))):
            if len(blob)!=index['dim']*4: raise ValueError('색인 벡터 차원이 다릅니다. 재색인하세요')
            values=struct.unpack('<'+'f'*index['dim'],blob)
            if not all(math.isfinite(v) for v in values): raise ValueError('색인 벡터 값이 유효하지 않습니다. 재색인하세요')
            score=max(sum(a*b for a,b in zip(query,values)) for query in query_vectors)
            scores[ident]=max(score,scores.get(ident,-math.inf))
    return sorted(scores,key=lambda ident:(-scores[ident],ident))[:limit*4]


def capture_search(db,scope,cutoff_ms):
    ids=scope_ids(db,scope)
    return {'session_ids':ids,'course_id':scope_course(db,scope),'chunk_ids':[r['id'] for r in eligible_chunks(db,ids,cutoff_ms,scope.session_id,scope)]}


def snapshot_rows(db,snapshot):
    for sid in snapshot['session_ids']:session(db,sid)
    if snapshot.get('course_id'):course(db,snapshot['course_id'])
    rows=[dict(r) for r in db.execute("SELECT c.*,s.ref FROM chunks c JOIN sources s ON s.id=c.source_id WHERE s.deleted=0 AND c.id IN (SELECT value FROM json_each(?))",(json.dumps(snapshot['chunk_ids']),))]
    if len(rows)!=len(snapshot['chunk_ids']):raise ValueError('고정한 근거가 삭제되었습니다. 새 요청을 실행하세요')
    return rows


async def retrieve(db,query,scope,cutoff_ms,limit=8,client=None,snapshot=None):
    if not query.strip() or len(query)>2000 or not 1<=limit<=32: raise ValueError('검색어와 결과 수를 확인하세요')
    snapshot=snapshot or capture_search(db,scope,cutoff_ms)
    ids=snapshot['session_ids'];rows=snapshot_rows(db,snapshot)
    ranked=keyword_rank(db,query,scope,rows,limit);index=index_status(db);warning='로컬 임베딩 연결 필요 · 키워드 검색' if index['ready'] else '의미 검색 준비 전 · 키워드 검색';mode='keyword'
    if not rows: warning='검색할 자료·확정 전사 없음'
    if client is not None and index['ready'] and rows:
        try:
            if embedding_format(index['model'],client)!=index['format'] or await model_digest(client,index['model'])!=index['digest']: raise ValueError('임베딩 모델이 변경되었습니다. 재색인하세요')
            query_vectors=await embed_parts(client,index['model'],query,query=True)
            if any(len(v)!=index['dim'] for v in query_vectors): raise ValueError('임베딩 차원이 변경되었습니다. 재색인하세요')
            semantic=await asyncio.to_thread(semantic_rank,db,index,rows,query_vectors,limit)
            if not semantic: raise ValueError('현재 범위의 의미 색인이 없거나 변경됐습니다. 다시 검색하거나 재색인하세요')
            scores={}
            for ranking in (ranked,semantic):
                for position,ident in enumerate(ranking,1): scores[ident]=scores.get(ident,0)+1/(60+position)
            ranked=sorted(scores,key=lambda ident:(-scores[ident],ident));mode='hybrid'
            warning='새 원문은 키워드 검색으로 포함 · 의미 검색 재색인 필요' if index['unindexed_chunks'] else None
        except Exception as exc: warning='의미 검색 실패 · 키워드 검색: '+str(exc)[:200]
    snapshot_rows(db,snapshot)
    return SearchResult(evidence=collect_evidence(db,ranked,rows,ids,limit,snapshot.get('course_id')),mode=mode,warning=warning)
