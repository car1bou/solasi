"""Grounded map items; reduction selects them without rewriting their meaning."""
import copy,hashlib,json,re
from pydantic import Field
from typing import Literal
from .models import Input

STATES=('fact','hypothesis','condition','example','expectation','proposal','decision','unresolved','unclear')
LABELS=dict(zip(STATES,('원문상 진술','가정','조건','예시','기대','제안','결정','미결','불명확')))
INSTRUCTION=' 항목을 최대4개로 묶고 subject에 원문에 있는 주어를 그대로 쓰세요. subject는 제목이나 주제가 아니라 원문에 실제 등장한 짧은 주어 명사구입니다. 예: 어머니는 요리를 합니다 → 어머니; 제가 외동입니다 → 제가. 부모 출신지 같은 범주를 주어로 쓰지 마세요. 인물 관계가 불명확하면 불명확으로 쓰세요. event_type은 fact/hypothesis/condition/example/expectation/proposal/decision/unresolved/unclear 중 선택하세요. fact는 원문상 실제 일로 진술된 내용이며 외부 사실 확인이 아닙니다. 자기 성장담을 자녀 양육으로 바꾸지 마세요. 가정·조건·예시는 불확실함과 다릅니다. 명확한 전제와 적용 대상을 text에 보존하세요. 타인의 발언·기대·상상을 실제 사건으로 바꾸지 마세요. 절대 일어나서는 안 되지만/생각하니까 같은 문맥을 유지하세요. 말이 끊긴 시간 표현만으로 화해 같은 사건을 만들지 마세요. evidence_ids는 그 항목을 직접 뒷받침하는 최대4개 원문을 선택하세요. 원문 발췌는 서버가 인용 ID로 연결하므로 인용 문장을 새로 쓰지 마세요.'
COPY_INSTRUCTION=' 이 구간의 핵심을 최대8개 항목으로 작성하세요. 먼저 항목의 직접 근거 evidence_ids를 최대4개 고르세요. subject_source_id는 그중 주어·대상이 명시된 원문 ID입니다. subject_quote는 해당 원문에서 복사한 짧은 인물·개념·대상 이름이며 제목·조건절·완성 문장은 쓰지 마세요. 복사 예: 마찰이 없다고 가정하면 → {"subject_quote":"마찰"}; 행렬 A에 2를 대입 → {"subject_quote":"행렬 A"}. 주어가 생략됐으면 두 주어 칸을 빈 문자열로 두세요. 한 항목은 인물·대상 하나와 주요 사건 성격 하나만 다룹니다. event_type은 fact/hypothesis/condition/example/expectation/proposal/decision/unresolved/unclear입니다. fact는 원문상 실제 일로 진술했다는 뜻이며 외부 사실 확인이 아닙니다. text에 주어·전제·부정·정정과 적용 대상을 유지하세요. 명확한 가정·조건·예시는 unclear가 아닙니다. 인물의 행동·관계·생각·기대를 다른 인물이나 실제 사건으로 바꾸지 마세요. 직접 근거로 해석할 수 없으면 unclear로 남기세요. title은 text가 말하는 내용만 짧게 쓰세요. 인용 문장은 서버가 원문에서 연결하므로 새로 작성하지 마세요.'


MODES={'lecture':' 강의에서는 개념의 주어·전제·정의·예시·반례와 정정 경위를 보존하세요. 명확한 조건을 불확실하다고 취급하지 마세요.','meeting':' 회의에서는 제안·검토·확정 결정·담당 후보·담당 확정·미결을 구분하세요. 후보나 미정 담당을 확정 담당자로 만들지 마세요.'}
CONDITION=re.compile(r'만약|(?<=[^\W_])(?:다면|라면|으면|이면)(?=\s|[,.!?。]|$)|(?:때|경우)(?:에)?만|인\s*경우|(?:라고|다고|것으로)\s*가정|가정(?:을\s*)?(?:하면|하자|하겠습니다|하에|하에서|하의|된)')
NONFACT=re.compile(r'절대.{0,20}(?:일어나|발생|생기).{0,20}(?:안|않)|상상(?:하면|하자|해)')
NEGATION=re.compile(r'않|아니|아닙|아닌|아님|아닐|못|없|미확정|미정|취소|보류|불참|미참석|불가|금지|거절|제외')
PENDING=re.compile(r'미확정|미정|보류|담당.{0,10}후보|(?:확정|승인|결정|합의|담당|배정|맡).{0,10}(?:않|못|아니|아닙|아님|아닌|아닐|아냐|취소)|(?:안|못)\s*(?:맡|담당|배정)')
ASSIGNED=re.compile(r'담당(?:자)?(?:입니다|이다|합니다|한다)|맡(?:습니다|는다)|담당(?:자)?(?:로|으로)?\s*(?:확정|지정|배정)')
CONFIRMED=re.compile(r'(?:확정|결정|합의)(?:했|하였|됐|되었|합니다|한다)|하기로\s*(?:했|하였)')

class GroundedItem(Input):
    title:str=Field(min_length=1,max_length=200)
    text:str=Field(min_length=1,max_length=50000)
    evidence_ids:list[str]=Field(min_length=1,max_length=4)
    subject:str=Field(min_length=1,max_length=200)
    event_type:Literal['fact','hypothesis','condition','example','expectation','proposal','decision','unresolved','unclear']


def grounded_schema(schema,*,copy_subject=False):
    schema=copy.deepcopy(schema);items=schema['properties']['sections']['items'];items['properties']={'subject':{'type':'string'},'event_type':{'type':'string','enum':list(STATES)},**items['properties']};items['required']+=['subject','event_type'];items['properties']['evidence_ids']['maxItems']=4;schema['properties']['sections']['maxItems']=8 if copy_subject else 4
    if copy_subject:
        props=items['properties'];items['properties']={'evidence_ids':props['evidence_ids'],'subject_source_id':{'type':'string'},'subject_quote':{'type':'string','maxLength':80,'description':'원문의 짧은 이름만: 마찰, 행렬 A, 김민수. 조건절·문장 제외. 생략은 빈 문자열.'},'event_type':props['event_type'],'text':props['text'],'title':props['title']};items['required']=list(items['properties'])
    return schema


def grounded_units(evidence,aliases):
    units=[];restore={}
    for item in evidence:
        segments=[text for sentence in re.split(r'(?<=[.!?。])\s+|\n+',item.text) if sentence.strip() for text in (sentence[n:n+320] for n in range(0,len(sentence),320))]
        for n,text in enumerate(segments):
            ident=aliases[item.ref.id]+('u'+str(n)if len(segments)>1 else '')
            units.append(item.model_copy(update={'ref':item.ref.model_copy(update={'id':ident}),'text':text}));restore[ident]=item.ref.id
    return units,restore


def copied_span(quote,source):
    if not quote.strip() or len(quote)>80:return ''
    if quote in source:return quote
    wanted=re.sub(r'\s+','',quote);positions=[n for n,c in enumerate(source)if not c.isspace()]
    if not wanted:return ''
    compact=''.join(source[n]for n in positions);start=compact.find(wanted)
    if start<0 or compact.find(wanted,start+1)>=0:return ''
    exact=source[positions[start]:positions[start+len(wanted)-1]+1]
    return exact if len(exact)<=80 else ''


def ground_sections(body,evidence,mode='lecture',*,copy_subject=False):
    from .outputs import parsed
    refs={e.ref.id:e for e in evidence};positions={e.ref.id:i for i,e in enumerate(evidence)};sections=[]
    copied_subjects=set()
    if copy_subject:
        for section in body['sections']:
            quote=section.get('subject_quote');source=section.get('subject_source_id')
            if isinstance(quote,str)and isinstance(source,str)and quote and len(quote)<=80 and source in section.get('evidence_ids',[])and source in refs and (exact:=copied_span(quote,refs[source].text)):copied_subjects.add(exact)
    for supplied in body['sections']:
        supplied=dict(supplied)
        if copy_subject:
            quote=supplied.pop('subject_quote',None);source=supplied.pop('subject_source_id',None)
            if not isinstance(quote,str)or not isinstance(source,str)or 'subject'in supplied:raise ValueError('주어 원문 형식이 유효하지 않습니다')
            supplied['subject']=(copied_span(quote,refs[source].text)if source in supplied.get('evidence_ids',[])and source in refs else '')or '불명확'
        item=parsed(GroundedItem,json.dumps({k:v for k,v in supplied.items()if k not in ('quotes','review_required','grounding_reason')}))
        ids=list(dict.fromkeys(item['evidence_ids']))
        if any(i not in refs for i in ids):raise ValueError('전달되지 않은 근거를 인용했습니다')
        ids.sort(key=positions.__getitem__)
        indexes=sorted({n for i in ids for n in range(max(0,positions[i]-2),min(len(evidence),positions[i]+3)) if (n==positions[i] or refs[i].ref.kind=='transcript' and evidence[n].ref.kind=='transcript' and evidence[n].ref.session_id==refs[i].ref.session_id and evidence[n].ref.start_ms is not None and refs[i].ref.start_ms is not None and abs(evidence[n].ref.start_ms-refs[i].ref.start_ms)<=15000)})
        context=' '.join(evidence[n].text for n in indexes);raw=' '.join(refs[i].text for i in ids);subject=item['subject'];state=item['event_type'];reasons=[]
        if subject in ('불명확','알 수 없음') or subject not in raw:
            reasons.append('주어 근거 확인');item['subject']='불명확'
        conditional=bool(CONDITION.search(raw)or NONFACT.search(raw))
        fragment=bool(re.search(r'을\s*때[.!?。]?\s*$',raw))
        if conditional or fragment and (CONDITION.search(context)or NONFACT.search(context)):
            if not (CONDITION.search(item['text'])or NONFACT.search(item['text'])):
                reasons.append('가정·조건의 전제 보존 확인')
                if state in ('fact','decision'):item['event_type']='hypothesis'
            elif state in ('fact','decision'):item['event_type']='condition'
        # shortcut: polarity cues detect dropped qualifications, not clause-level logical equivalence.
        if NEGATION.search(raw)and not NEGATION.search(item['text']):reasons.append('부정·유보 표현 보존 확인')
        if CONFIRMED.search(item['title']+' '+item['text'])and not CONFIRMED.search(raw):reasons.append('결정·확정의 원문 근거 확인')
        if mode=='meeting' and (state=='decision'or CONFIRMED.search(item['title']+' '+item['text'])or ASSIGNED.search(item['title']+' '+item['text'])):
            tail=re.split(r'(?<=[.!?。])\s+|[,;]|으나|지만|그러나|하지만',raw)[-1]
            # shortcut: an explicit object after the actor can be the assignee; do not treat that actor as confirmed.
            after_subject=tail.split(subject,1)[1]if subject in tail else ''
            supported=subject!='불명확'and subject in tail and CONFIRMED.search(tail)and not PENDING.search(tail)and not re.search(r'\S+(?:을|를|에게|한테)',after_subject)
            if not supported and (PENDING.search(raw)or re.search(r'제안|검토',raw)and not CONFIRMED.search(raw)):
                reasons.append('제안·미결 또는 담당 후보 확인');item['event_type']='unclear'if CONFIRMED.search(raw)else'unresolved'
        # shortcut: literal numeric exclusive-condition values, not general condition entailment.
        source_values=set(re.findall(r'(\d+)\s*(?:일\s*때|인\s*경우)(?:에)?만',raw));output_values=set(re.findall(r'(\d+)\s*(?:일\s*때|인\s*경우)(?:에)?만',item['text']))
        if source_values and output_values and source_values!=output_values:reasons.append('조건의 적용 값 확인')
        # shortcut: explicit existence premises only; negation in a different clause cannot justify their reversal.
        premise=re.compile(re.escape(subject)+r'(?:이|가)\s*(없|있)(?:다고\s*가정|는\s*가정|다면|으면|는\s*경우)')
        original_premises=set(premise.findall(raw));generated_premises=set(premise.findall(item['text']))
        if original_premises and generated_premises and original_premises.isdisjoint(generated_premises):reasons.append('가정·조건 전제의 긍정·부정 확인')
        if state=='unclear':reasons.append('해석 확인')
        if copy_subject and re.sub(r'\s+','',subject)not in re.sub(r'\s+','',item['text']):reasons.append('설명문의 주어 근거 확인')
        # shortcut: explicit Korean particles/spatial phrases flag role reversals, not general semantic entailment.
        if copy_subject and subject!='불명확':
            actor=re.compile(re.escape(subject)+r'(?:은|는|이|가)(?=\s|[,;.!?。]|$)')
            target=re.compile(re.escape(subject)+r'(?:(?:을|를|에게|한테|에서|으로|로|에|의)|\s+(?:앞|옆|뒤)에(?:서)?(?:는|도)?)(?=\s|[,;.!?。]|$)')
            direct=refs[source].text;generated=item['title']+' '+item['text']
            if target.search(direct) and not actor.search(direct) and actor.search(generated):reasons.append('원문 대상이 행동 주체로 바뀌었는지 확인')
            recipient=re.compile(re.escape(subject)+r'(?:에게|한테)(?=\s|[,;.!?。]|$)')
            if actor.search(direct) and not recipient.search(direct) and recipient.search(item['text']) and not actor.search(item['text']):reasons.append('원문 주체가 수신자로 바뀌었는지 확인')
        # shortcut: catches other copied subjects leaking across items, not every invented person or relation.
        if any(name not in raw and name in item['title']+' '+item['text']for name in copied_subjects):reasons.append('다른 항목의 주어 혼입 확인')
        # shortcut: literal digit groups catch introduced numbers, not changed targets or Korean numeral paraphrases.
        if set(re.findall(r'\d+',item['title'].replace(',','')+' '+item['text'].replace(',','')))-set(re.findall(r'\d+',raw.replace(',',''))):reasons.append('원문에 없는 숫자 확인')
        item['review_required']=bool(reasons)
        if reasons:
            ids=[evidence[n].ref.id for n in indexes];item['title']='원문 가정·조건 발췌'if reasons==['설명문의 주어 근거 확인']and item['event_type']in ('condition','hypothesis')else '원문 발췌 · 해석 확인 필요';item['text']='\n'.join(refs[i].text for i in ids)
        item['evidence_ids']=ids;item['quotes']=[{'text':refs[i].text,'evidence_ids':[i]}for i in ids];item['grounding_reason']=' · '.join(reasons);sections.append(item)
    # shortcut: source length is a coverage proxy, not a semantic importance score; replace with annotated discourse units when available.
    meaningful=[i for i,e in enumerate(evidence)if len(re.sub(r'\W','',e.text))>=8]
    bands={evidence[n].ref.id:min(2,i*3//len(meaningful))for i,n in enumerate(meaningful)}if len(meaningful)>=3 else {e.ref.id:0 for e in evidence}
    for section in sections:section['coverage_groups']=sorted({bands[i]for i in section['evidence_ids']if i in bands})
    present={g for section in sections for g in section['coverage_groups']}
    # shortcut: only short, single-sentence writing requests may be empty; mixed or ambiguous notes retain excerpts.
    writing_only=all(e.ref.kind=='note' and len(e.text)<200 and len(re.split(r'[.!?。]\s*',e.text.rstrip('.!?。 ')))==1 and re.search(r'원문|전사|자료',e.text) and re.search(r'정리|요약',e.text) and re.search(r'대조|비교',e.text) and re.search(r'(?:정리|요약|대조|비교)(?:한다|하세요|해줘|해 주세요|해주세요|하기)[.!?。 ]*$',e.text) and not re.search(r'\S+(?:은|는|이|가)\s|\d|했|였|됐다|되었다|아니다|않|없',e.text) for e in evidence)
    if sections or not writing_only:
        for band in sorted(set(bands.values())-present):
            entries=[e for e in evidence if bands.get(e.ref.id)==band];ids=[e.ref.id for e in entries]
            sections.append({'title':'원문 발췌 · 구간 확인 필요','text':'\n'.join(e.text for e in entries),'subject':'불명확','event_type':'unclear','evidence_ids':ids,'quotes':[{'text':e.text,'evidence_ids':[e.ref.id]}for e in entries],'review_required':True,'grounding_reason':'구간 요약에서 앞·중간·뒤 근거가 빠져 원문을 보존했습니다.','coverage_groups':[band]})
    return {'sections':list({json.dumps(item,ensure_ascii=False,sort_keys=True):item for item in sections}.values())}


def unquoted_sources(sections,evidence):
    units,restore=grounded_units(evidence,{e.ref.id:e.ref.id for e in evidence});quoted={}
    for section in sections:
        for quote in section.get('quotes',[]):
            for ident in quote['evidence_ids']:quoted.setdefault(ident,[]).append(quote['text'])
    # These excerpts lack a direct quote; that does not establish a semantic omission.
    return [{'text':unit.text,'evidence_ids':[restore[unit.ref.id]]}for unit in units if not any(unit.text in text for text in quoted.get(restore[unit.ref.id],[]))]


async def merge_grounded(db,frozen,job_id,pieces,**kwargs):
    from .answers import checked_evidence,SYSTEM
    from .outputs import generate,check_budget
    request,_=checked_evidence(db,frozen);candidates={f'p{p}:{s}':{'part_no':p,'section':section}for p,piece in enumerate(pieces)for s,section in enumerate(piece['sections'])};parts={v['part_no']for v in candidates.values()};limit=frozen.get('summary_selection_limit',max(6,3*len(parts)));infos=[]
    def result(ids,incomplete):return {'sections':[v['section']for i,v in candidates.items()if i in ids],'selection_incomplete_parts':incomplete,'selection_limit':limit}
    protected=[i for i,v in candidates.items()if v['section'].get('review_required') or v['section'].get('event_type','fact')!='fact']
    selectable={i:v for i,v in candidates.items()if i not in protected}
    if len(selectable)<=limit:return result(list(candidates),[]),[]
    schema={'type':'object','properties':{'selected_ids':{'type':'array','items':{'type':'string','enum':list(selectable)},'minItems':1,'maxItems':max(limit,len(parts))}},'required':['selected_ids'],'additionalProperties':False}
    instruction=SYSTEM+' 원문 구절·주어·발언 성격을 보존한 요약 항목을 선택하세요. 문장을 다시 쓰지 말고 selected_ids만 반환하세요. 모든 part_no의 coverage_groups를 각각 적어도 한 번 포함하도록 선택하고 후반 사건·정정·조건을 빠뜨리지 마세요. 같은 주제여도 주어·사건상태가 다르면 합치지 마세요.'
    instruction+=' 가정·조건·예시·기대·제안·결정·미결과 확인 필요 항목은 서버가 별도 보존합니다. preserved_groups로 이미 보존한 범위를 확인하고 나머지 일반 설명을 선택하세요.'
    data={'candidates':{i:{'part_no':v['part_no'],**{k:v['section'][k]for k in ('subject','event_type','title','text','coverage_groups')if k in v['section']}}for i,v in selectable.items()},'preserved_groups':[{'part_no':candidates[i]['part_no'],'coverage_groups':candidates[i]['section'].get('coverage_groups',[0])}for i in protected],'required_parts':sorted(parts),'target_items':max(limit,len(parts))};messages=[{'role':'system','content':instruction},{'role':'user','content':json.dumps(data,ensure_ascii=False,separators=(',',':'))}];output_limit=min(1024,frozen.get('summary_output_limit',2048));profile=frozen.get('summary_tokenizer');signature=[messages,schema,profile,output_limit,'quotes-selection-v4']
    if frozen.get('source_sampling'):signature.append(frozen['source_sampling'])
    digest=hashlib.sha256(json.dumps(signature,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    required={(v['part_no'],g)for v in candidates.values()for g in v['section'].get('coverage_groups',[0])}
    def missing_groups(ids):
        covered={(candidates[i]['part_no'],g)for i in ids for g in candidates[i]['section'].get('coverage_groups',[0])}
        return sorted({p for p,g in required-covered}|(parts-{candidates[i]['part_no']for i in ids}))
    saved=db.execute('SELECT body,metadata FROM artifact_parts WHERE job_id=? AND part_no=-1',(job_id,)).fetchone()
    if saved and json.loads(saved['metadata']).get('input_digest')==digest:
        body=json.loads(saved['body']);ids=body['selected_ids']
        if not isinstance(ids,list)or any(i not in candidates for i in ids)or not set(protected)<=set(ids)or missing_groups(ids):raise ValueError('보존한 요약 선택의 근거가 유효하지 않습니다')
        return result(ids,body['incomplete_parts']),json.loads(saved['metadata'])['calls']
    ids=protected[:];missing=missing_groups(ids);selected_once=False
    for attempt in range(2):
        checked_evidence(db,frozen)
        try:bound=check_budget(request.provider,messages,schema,output_limit=output_limit,tokenizer_profile=profile)
        except ValueError as exc:
            if '예산'not in str(exc):raise
            missing=sorted({v['part_no']for v in selectable.values()});break
        local_kwargs=kwargs|({'expected_digest':profile['model_digest']}if profile else {})
        response=await generate(request.provider,messages,[],schema,output_limit=output_limit,**local_kwargs)
        if profile and response.usage.get('prompt_eval_count',bound+1)>bound:raise ValueError('모델 입력 토큰이 계산 상한을 넘었습니다')
        infos.append({'provider':request.provider.provider,'model':response.model,'digest':response.digest,'usage':response.usage,'elapsed_ms':response.elapsed_ms})
        try:
            value=json.loads(response.text);selected=value['selected_ids']
            if set(value)!={'selected_ids'}or not isinstance(selected,list)or not selected or len(selected)>max(limit,len(parts))or any(not isinstance(i,str)or i not in selectable for i in selected):raise ValueError()
            ids=list(dict.fromkeys(ids+selected));selected_once=True
        except (ValueError,KeyError,TypeError):missing=(missing_groups(ids)or sorted(parts))if selected_once else sorted({v['part_no']for v in selectable.values()})
        else:missing=missing_groups(ids)
        if not missing:break
        messages=messages[:2]+[{'role':'user','content':'기존 선택 '+json.dumps(ids)+'는 보존됩니다. 빠진 구간 '+json.dumps(missing)+'의 핵심 항목 ID를 추가로 선택하세요. 원문과 이미 제시한 후보에서만 선택하세요.'}]
    incomplete=missing
    if missing:ids+=[i for i,v in candidates.items()if v['part_no']in missing and i not in ids]
    checked_evidence(db,frozen)
    with db:db.execute('INSERT OR REPLACE INTO artifact_parts VALUES (?,?,?,?)',(job_id,-1,json.dumps({'selected_ids':ids,'incomplete_parts':incomplete}),json.dumps({'input_digest':digest,'calls':infos})))
    return result(ids,incomplete),infos


def checked_grounded(body,evidence,allow_empty=False,*,copy_subject=False):
    from .outputs import parsed,Summary,SummaryPart
    refs={e.ref.id:e.text for e in evidence}
    parsed(SummaryPart if allow_empty else Summary,json.dumps({'sections':[{k:s[k]for k in ('title','text','evidence_ids')}for s in body['sections']]}))
    for section in body['sections']:
        ids=section['evidence_ids']
        if any(i not in refs for i in ids):raise ValueError('보존한 요약의 근거가 유효하지 않습니다')
        quotes=section.get('quotes',[])
        valid=bool(quotes)and all(set(q)=={'text','evidence_ids'} and len(q['evidence_ids'])==1 and q['evidence_ids'][0]in ids and isinstance(q['text'],str)and bool(q['text'])and q['text']in refs[q['evidence_ids'][0]]for q in quotes) and {i for q in quotes for i in q['evidence_ids']}==set(ids)
        if valid and not section.get('review_required') and (not section.get('subject') or not (any(section['subject']in q['text']for q in quotes)if copy_subject else section['subject']in ' '.join(refs[i]for i in ids))):valid=False
        if not valid or section.get('event_type')not in STATES or type(section.get('review_required'))is not bool or not isinstance(section.get('subject'),str):raise ValueError('보존한 요약의 원문·주어·사건 상태가 유효하지 않습니다')
    return body
