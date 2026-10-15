import httpx
from urllib.parse import urlsplit
from .models import Evidence,SourceRef
from .db import new_id,now
from .providers import http_client,checked_body


def web_url(value):
    if not isinstance(value,str) or len(value)>4096 or any(ord(c)<=32 for c in value): return False
    try:
        parsed=urlsplit(value)
        return parsed.scheme in ('http','https') and bool(parsed.hostname) and not parsed.username and not parsed.password
    except ValueError: return False


async def search_web(query,limit=5,*,secret=None,client=None,session_id=None):
    if not secret: raise ValueError('웹 검색 미연결 · Exa 키를 설정하세요')
    if not isinstance(query,str) or not query.strip() or len(query)>500 or not 1<=limit<=5: raise ValueError('전송할 웹 검색어를 입력하세요 · 최대 500자')
    async with http_client(client) as transport:
        try:
            response=await transport.post('https://api.exa.ai/search',headers={'x-api-key':secret},json={'query':query.strip(),'type':'auto','numResults':limit,'contents':{'highlights':True}},timeout=30)
            if response.status_code==429: raise ValueError('웹 검색 요청 한도 초과 · 잠시 후 새 질문에서 재시도하세요')
            if response.status_code==504: raise ValueError('웹 검색 서버 처리 시간 초과')
            if response.status_code==401: raise ValueError('웹 검색 인증 실패 · Exa 키를 확인하세요')
            if response.status_code==402: raise ValueError('웹 검색 크레딧·사용 예산을 확인하세요')
            if response.status_code>=400: raise ValueError('웹 검색 요청 실패 · HTTP '+str(response.status_code))
            body=checked_body(response)
        except httpx.TimeoutException: raise ValueError('웹 검색 제한 시간 초과') from None
        except httpx.HTTPError: raise ValueError('웹 검색에 연결할 수 없습니다') from None
    rows=body.get('results')
    if not isinstance(rows,list): raise ValueError('웹 검색 응답 형식이 유효하지 않습니다')
    evidence=[];retrieved=now()
    for row in rows[:limit]:
        if not isinstance(row,dict) or not web_url(row.get('url')): continue
        excerpts=row.get('highlights',[])
        if not isinstance(excerpts,list) or any(not isinstance(item,str) for item in excerpts): continue
        text='\n\n'.join(item.strip() for item in excerpts if item.strip())[:6000]
        if not text: continue
        title=row.get('title') if isinstance(row.get('title'),str) else row['url']
        ref=SourceRef(id='web:'+new_id(),kind='web',session_id=session_id,url=row['url'])
        evidence.append(Evidence(ref=ref,text=text,label='웹 참고 · '+title[:300],retrieved_at=retrieved))
    return evidence
