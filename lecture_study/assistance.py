"""Evidence-bound memo proposals and optional question candidates."""
import hashlib,json
from pydantic import Field
from .models import Input,Evidence
from .db import session,now
from .providers import generate
from .answers import checked_evidence,save_artifact,get_artifact,evidence_schema
from .outputs import object_schema,IDS,parsed,check_ids,output_messages,check_budget,metadata_for

NOTE_SCHEMA=object_schema({'addition':{'type':'string'},'evidence_ids':IDS|{'minItems':1,'maxItems':32}})
CARD_SCHEMA=object_schema({'cards':{'type':'array','maxItems':3,'items':object_schema({'prompt':{'type':'string'},'quote':{'type':'string'},'source_id':{'type':'string'}})}})
NOTE_INSTRUCTION='메모에 덧붙일 인근 확정 전사의 핵심 사건·개념을 한국어 1~3문장 addition으로 작성하세요. 원래 메모가 작성 요청이면 그 요청에 맞는 인근 전사 내용을 간결하게 정리하세요. 인근 확정 전사에 명시된 내용만 쓰고 원래 메모의 추측을 사실로 바꾸지 마세요. evidence_ids는 보강에 사용한 확정 전사만 인용하세요. 숫자가 가리키는 대상·단위·주체·부정·시점을 바꾸지 마세요. 원문에 없는 영문명·번역·오늘·다음 같은 표현을 추가하지 마세요. 요청을 복사하거나 정리했다·보존했다 같은 작업 설명을 쓰지 마세요.'
CARD_INSTRUCTION='확정 전사에서 답변하면 유용한 질문 후보를 최대 3개 추출하세요. 명시적 질문·설명이 필요한 주제만 사용하고 후보가 없으면 cards를 빈 배열로 반환하세요. quote는 해당 source_id 원문에 그대로 있는 구절이어야 합니다. 질문에도 원문에 없는 사실·오늘·다음 같은 시점·전제를 넣지 말고 질문에 답하지 마세요.'

class NoteProposal(Input):
    addition:str=Field(min_length=1,max_length=20000)
    evidence_ids:list[str]=Field(min_length=1,max_length=32)
class Candidate(Input):
    prompt:str=Field(min_length=1,max_length=2000)
    quote:str=Field(min_length=1,max_length=2000)
    source_id:str
class Candidates(Input):
    cards:list[Candidate]=Field(max_length=3)


def snapshot_details(db,request):
    if request.scope.mode!='current' or request.scope.lecture_ids:
        raise ValueError('현재 기록의 확정 전사만 사용하세요')
    if request.kind!='note':return {}
    row=db.execute('SELECT anchor_ms FROM notes WHERE session_id=? AND source_id=?',(request.session_id,request.note_source_id)).fetchone()
    if row is None:raise ValueError('저장한 메모 버전을 선택하세요')
    anchor=request.anchor_ms if request.anchor_ms is not None else row['anchor_ms']
    if anchor is None:raise ValueError('메모의 녹음 시점을 지정하세요')
    end=db.execute('SELECT max(offset_ms+source_frames*1000/sample_rate) FROM recordings WHERE session_id=?',(request.session_id,)).fetchone()[0]
    if end is None or not 0<=anchor<=end:raise ValueError('메모 시점이 원음 범위를 벗어납니다')
    return {'note_anchor_ms':anchor}


def scoped_evidence(db,request,snapshot):
    from .answers import snapshot_evidence
    all_items=snapshot_evidence(db,request,snapshot['cutoff_ms'],snapshot['search'])
    speech=[e for e in all_items if e.ref.kind=='transcript' and e.ref.session_id==request.session_id]
    if request.kind=='note':
        note=next((e for e in all_items if e.ref.id==request.note_source_id),None)
        if note is None:raise ValueError('선택한 메모가 요청 범위에 없습니다')
        anchor=snapshot['note_anchor_ms']
        speech=[e for e in speech if e.ref.end_ms>=anchor-90000 and e.ref.start_ms<=anchor+90000]
        speech.sort(key=lambda e:abs((e.ref.start_ms+e.ref.end_ms)/2-anchor))
        if not speech:raise ValueError('메모 인근의 확정 전사가 없습니다')
        return [note,*sorted(speech[:8],key=lambda e:e.ref.start_ms)]
    end=snapshot['cutoff_ms'] or 0
    return sorted((e for e in speech if e.ref.end_ms>=end-120000),key=lambda e:e.ref.start_ms,reverse=True)[:16]


async def create_assistance(db,frozen,job_id,**kwargs):
    request,evidence=checked_evidence(db,frozen)
    is_note=request.kind=='note';schema=NOTE_SCHEMA if is_note else CARD_SCHEMA;instruction=NOTE_INSTRUCTION if is_note else CARD_INSTRUCTION
    schema=evidence_schema(schema,[e for e in evidence if not is_note or e.ref.kind=='transcript'])
    if is_note and request.provider.provider in ('ollama','local'):schema['properties']['addition'].update(minLength=1,maxLength=20000)
    if not is_note:schema['properties']['cards']['items']['properties']['source_id']['enum']=[e.ref.id for e in evidence]
    messages=output_messages(request,evidence,instruction);check_budget(request.provider,messages,schema)
    result=await generate(request.provider,messages,[],schema,**kwargs)
    body=parsed(NoteProposal if is_note else Candidates,result.text)
    if is_note:
        if not body['addition'].strip():raise ValueError('보강 메모 내용이 비어 있습니다')
        check_ids(body['evidence_ids'],[e for e in evidence if e.ref.kind=='transcript'])
    else:
        by_id={e.ref.id:e for e in evidence};seen=set();cards=[]
        for card in body['cards']:
            source=by_id.get(card['source_id'])
            if source is None or card['quote'] not in source.text:raise ValueError('질문 후보의 원문 인용이 유효하지 않습니다')
            ident=hashlib.sha256((card['source_id']+'\0'+card['quote']).encode()).hexdigest()[:32]
            if ident not in seen:cards.append(card|{'id':ident});seen.add(ident)
        body['cards']=cards
    checked_evidence(db,frozen)
    info=metadata_for(request,frozen,result,request.kind)
    if is_note:info.update(note_source_id=request.note_source_id,anchor_ms=frozen['note_anchor_ms'])
    return save_artifact(db,job_id,body,evidence,info)


def apply_note(db,ident,addition):
    from .materials import save_note,list_materials
    saved=get_artifact(db,ident)
    if saved['kind']!='note':raise ValueError('메모 보강안을 선택하세요')
    if not isinstance(addition,str) or not addition.strip() or len(addition)>20000:raise ValueError('보강 메모 길이를 확인하세요')
    if saved['metadata'].get('applied_note_source_id'):
        return dict(db.execute('SELECT text,version,source_id,anchor_ms FROM notes WHERE source_id=?',(saved['metadata']['applied_note_source_id'],)).fetchone())
    frozen=json.loads(db.execute('SELECT request FROM jobs WHERE id=?',(saved['job_id'],)).fetchone()[0]);checked_evidence(db,frozen)
    current=list_materials(db,saved['session_id'])['note']
    if current is None or current['source_id']!=saved['metadata']['note_source_id']:raise ValueError('메모가 변경되었습니다. 새 보강안을 검토하세요')
    text=current['text']+'\n\n보강 메모\n'+addition.strip()
    if len(text)>2_000_000:raise ValueError('노트가 최대 길이를 초과합니다. 보강 메모를 줄이세요')
    ref=save_note(db,saved['session_id'],text,anchor_ms=saved['metadata']['anchor_ms'])
    metadata=saved['metadata']|{'applied_note_source_id':ref.id,'original_addition':saved['body']['addition']}
    body=saved['body']|{'addition':addition.strip()}
    with db:db.execute('UPDATE artifacts SET body=?,metadata=?,confirmed=1,edited=? WHERE id=?',(json.dumps(body,ensure_ascii=False),json.dumps(metadata,ensure_ascii=False),int(addition.strip()!=saved['body']['addition']),ident))
    return list_materials(db,saved['session_id'])['note']


def question_cards(db,sid):
    session(db,sid);cards={}
    preferences={r['card_id']:json.loads(r['state']) for r in db.execute('SELECT card_id,state FROM question_card_preferences WHERE session_id=?',(sid,))}
    for row in db.execute("SELECT id,body FROM artifacts WHERE session_id=? AND kind='candidates' ORDER BY created_at DESC",(sid,)):
        for card in json.loads(row['body'])['cards']:
            if card['id'] in cards:continue
            source=db.execute('SELECT deleted,ref FROM sources WHERE id=?',(card['source_id'],)).fetchone()
            if source is None or source['deleted']:continue
            state=preferences.get(card['id'],{})
            ref=json.loads(source['ref']);current=db.execute('SELECT revision AS version FROM transcripts WHERE id=? AND superseded_by IS NULL',(card['source_id'].rsplit(':v',1)[0],)).fetchone()
            if not any(state.get(k) for k in ('pinned','edited','answer_job_id')) and (current is None or current['version']!=ref['version']):continue
            cards[card['id']]=card|{'artifact_id':row['id'],'pinned':False,'dismissed':False,'edited':False,'answer_job_id':None}|state
    return sorted(cards.values(),key=lambda c:not c['pinned'])


def update_card(db,sid,ident,change):
    card=next((c for c in question_cards(db,sid) if c['id']==ident),None)
    if card is None:raise KeyError('질문 후보를 찾을 수 없습니다')
    old=db.execute('SELECT state FROM question_card_preferences WHERE session_id=? AND card_id=?',(sid,ident)).fetchone();state=json.loads(old['state']) if old else {}
    if 'prompt' in change:
        if card['answer_job_id']:raise ValueError('답변을 실행한 질문은 고정됩니다. 새 질문으로 실행하세요')
        if not isinstance(change['prompt'],str) or not change['prompt'].strip() or len(change['prompt'])>2000:raise ValueError('질문 길이를 확인하세요')
        change=change|{'prompt':change['prompt'].strip(),'edited':True}
    state.update(change)
    with db:db.execute('INSERT OR REPLACE INTO question_card_preferences VALUES (?,?,?)',(sid,ident,json.dumps(state,ensure_ascii=False)))
    return card|state
