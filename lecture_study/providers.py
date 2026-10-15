import base64
import json
import re
import time
from contextlib import asynccontextmanager
from urllib.parse import urlparse,quote
import httpx
from .models import ProviderConfig,ProviderResult
from .retrieval import model_digest

ENDPOINTS={'openai':'https://api.openai.com/v1','gemini':'https://generativelanguage.googleapis.com/v1beta','claude':'https://api.anthropic.com/v1'}
# shortcut: unknown API model modalities stay disabled; add exact model families after official capability checks.
VISION={'openai':('gpt-4.1','gpt-4.1-mini'),
        'gemini':('gemini-3.8-flash','gemini-2.5-flash','gemini-2.5-flash-lite','gemini-2.5-pro'),
        'claude':('claude-sonnet-4','claude-opus-4','claude-haiku-4-5','claude-3-7-sonnet','claude-3-5-haiku')}


def known_vision(provider,model):
    return any(model==name or re.fullmatch(re.escape(name)+r'-\d{8}',model) for name in VISION.get(provider,()))


def local_url(value):
    parsed=urlparse(value)
    if parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','localhost','::1') or parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment:
        raise ValueError('Ollama의 http loopback 주소를 입력하세요')
    try: port=parsed.port
    except ValueError: raise ValueError('Ollama 포트를 확인하세요') from None
    if port is None or not 1<=port<=65535: raise ValueError('Ollama 포트를 확인하세요')
    return value.rstrip('/')


@asynccontextmanager
async def http_client(client=None):
    if client is not None: yield client
    else:
        async with httpx.AsyncClient(timeout=httpx.Timeout(180,connect=10),trust_env=False) as owned: yield owned


def headers(provider,secret):
    if not secret: raise ValueError('API 키를 먼저 연결하세요')
    if provider=='openai': return {'Authorization':'Bearer '+secret}
    if provider=='gemini': return {'x-goog-api-key':secret}
    return {'x-api-key':secret,'anthropic-version':'2023-06-01'}


def checked_body(response):
    if response.status_code==401: raise ValueError('API 인증 실패 · 키와 접근 권한을 확인하세요')
    if response.status_code==403: raise ValueError('모델 접근 권한이 없습니다')
    if response.status_code==429: raise ValueError('API 사용 한도 또는 요청 한도를 초과했습니다')
    if response.status_code>=400: raise ValueError('모델 요청 실패 · HTTP '+str(response.status_code)+' · 모델·입력·구조화 출력 지원을 확인하세요')
    if len(response.content)>8*1024*1024: raise ValueError('모델 응답이 너무 큽니다')
    try: body=response.json()
    except ValueError: raise ValueError('모델 응답이 JSON이 아닙니다') from None
    if not isinstance(body,dict): raise ValueError('모델 응답 형식을 확인하세요')
    return body


def claude_schema(schema):
    result=json.loads(json.dumps(schema))
    def adjust(node):
        if isinstance(node,dict):
            if node.get('type')=='array':
                node.pop('maxItems',None)
                if node.get('minItems',0)>1:node.pop('minItems')
            for value in node.values():adjust(value)
        elif isinstance(node,list):
            for value in node:adjust(value)
    adjust(result)
    return result


def usage_numbers(value):
    if not isinstance(value,dict): return {}
    return {key:(usage_numbers(item) if isinstance(item,dict) else item) for key,item in value.items() if isinstance(key,str) and len(key)<100 and (isinstance(item,dict) or type(item) is int and item>=0)}


async def model_status(config,*,client=None,secret=None,ollama_url=None):
    async with http_client(client) as transport:
        try:
            if config.provider=='ollama':
                if not ollama_url: raise ValueError('로컬 엔진을 먼저 연결하세요')
                url=local_url(ollama_url)
                digest=await model_digest(transport,config.model,url)
                body=checked_body(await transport.post(url+'/api/show',json={'model':config.model}))
                if body.get('remote_model') or body.get('remote_host'): raise ValueError('다운로드한 로컬 모델을 선택하세요')
                capabilities=body.get('capabilities',[])
                return {'accessible':True,'vision':'vision' in capabilities,'embedding':'embedding' in capabilities,'completion':'completion' in capabilities,'digest':digest,'context_limit':config.context_limit}
            provider=config.provider;auth=headers(provider,secret)
            body=checked_body(await transport.get(ENDPOINTS[provider]+'/models/'+quote(config.model,safe=''),headers=auth))
            limit=body.get('inputTokenLimit') if provider=='gemini' else body.get('max_input_tokens')
            if type(limit) is not int or limit<512: limit=config.context_limit
            if not isinstance(body.get('name' if provider=='gemini' else 'id'),str): raise ValueError('모델 조회 응답이 유효하지 않습니다')
            if body.get('lifecycle')=='retired': raise ValueError('종료된 모델입니다')
            capabilities=body.get('capabilities') or {}
            vision=(capabilities.get('image_input') or {}).get('supported') is True if provider=='claude' else known_vision(provider,config.model)
            return {'accessible':True,'vision':vision,'embedding':False,'completion':provider!='gemini' or 'generateContent' in body.get('supportedGenerationMethods',[]),'context_limit':min(config.context_limit,limit)}
        except httpx.TimeoutException: raise ValueError('모델 연결 제한 시간 초과') from None
        except httpx.HTTPError: raise ValueError('모델에 연결할 수 없습니다') from None
        except (KeyError,TypeError,AttributeError): raise ValueError('모델 조회 응답 형식을 확인하세요') from None


async def generate(config:ProviderConfig,messages,images,schema,*,client=None,secret=None,ollama_url=None,before_local=None,output_limit=4096,expected_digest=None,source_copy=False):
    if type(output_limit)is not int or not 1<=output_limit<=4096:raise ValueError('출력 예산은 1~4096이어야 합니다')
    if len(images)>4: raise ValueError('이미지는 한 번에 최대 4개입니다')
    if images and not config.vision: raise ValueError('선택한 모델의 이미지 지원을 먼저 확인하세요')
    if any(m.get('role') not in ('system','user','assistant') or not isinstance(m.get('content'),str) for m in messages): raise ValueError('모델 메시지를 확인하세요')
    if sum(len(m['content']) for m in messages)>1_000_000: raise ValueError('모델 입력이 너무 큽니다')
    encoded=[]
    for path in images:
        if path.stat().st_size>20*1024*1024: raise ValueError('이미지는 20MiB 이하여야 합니다')
        data=path.read_bytes()
        if data.startswith(b'\x89PNG\r\n\x1a\n'): mime='image/png'
        elif data.startswith(b'\xff\xd8\xff'): mime='image/jpeg'
        else: raise ValueError('PNG·JPEG 이미지를 선택하세요')
        encoded.append((mime,base64.b64encode(data).decode('ascii')))
    provider=config.provider;actual_digest=None
    system='\n'.join(m['content'] for m in messages if m['role']=='system')
    conversation=[m for m in messages if m['role']!='system']
    if not conversation: conversation=[{'role':'user','content':''}]
    started=time.monotonic()
    async with http_client(client) as transport:
        try:
            if provider=='ollama':
                if not ollama_url: raise ValueError('로컬 엔진을 먼저 연결하세요')
                url=local_url(ollama_url)
                status=await model_status(config,client=client,ollama_url=url)
                actual_digest=status['digest']
                if expected_digest is not None and actual_digest!=expected_digest:raise ValueError('요약용 토크나이저와 실행 모델이 다릅니다. 새 작업을 요청하세요')
                if not status['completion'] or encoded and not status['vision']: raise ValueError('로컬 모델이 요청 기능을 지원하지 않습니다')
                local_messages=[dict(m) for m in messages]
                if encoded: local_messages[-1]['images']=[data for mime,data in encoded]
                payload={'model':config.model,'messages':local_messages,'stream':False,'think':False,'options':{'num_ctx':config.context_limit,'num_predict':output_limit}}
                if schema is not None: payload['format']=schema
                if schema is not None and source_copy:payload['options'].update(temperature=0,presence_penalty=0)
                if before_local:await before_local()
                if expected_digest is not None and await model_digest(transport,config.model,url)!=expected_digest:raise ValueError('요약용 토크나이저와 실행 모델이 다릅니다. 새 작업을 요청하세요')
                body=checked_body(await transport.post(url+'/api/chat',json=payload))
                if body.get('remote_model') or body.get('remote_host'): raise ValueError('원격 로컬 모델 응답은 사용할 수 없습니다')
                if body.get('done') is not True or body.get('done_reason') in ('length','error'): raise ValueError('모델 응답이 완료되지 않았습니다')
                if await model_digest(transport,config.model,url)!=actual_digest:raise ValueError('생성 중 로컬 모델 digest가 변경되었습니다')
                text=body.get('message',{}).get('content');usage=usage_numbers({key:body[key] for key in ('prompt_eval_count','eval_count') if key in body})
            elif provider=='openai':
                inputs=[{'role':m['role'],'content':[{'type':'input_text','text':m['content']}]} for m in conversation]
                inputs[-1]['content'].extend({'type':'input_image','image_url':'data:'+mime+';base64,'+data} for mime,data in encoded)
                payload={'model':config.model,'instructions':system,'input':inputs,'store':False,'max_output_tokens':output_limit}
                if schema is not None: payload['text']={'format':{'type':'json_schema','name':'result','schema':schema,'strict':True}}
                body=checked_body(await transport.post(ENDPOINTS[provider]+'/responses',headers=headers(provider,secret),json=payload))
                if body.get('status')!='completed': raise ValueError('모델 응답이 완료되지 않았습니다')
                parts=[part for row in body.get('output',[]) if row.get('type')=='message' for part in row.get('content',[])]
                if any(p.get('type')=='refusal' for p in parts): raise ValueError('모델이 요청을 거절했습니다')
                text=''.join(p.get('text','') for p in parts if p.get('type')=='output_text');usage=usage_numbers(body.get('usage'))
            elif provider=='gemini':
                contents=[{'role':'model' if m['role']=='assistant' else 'user','parts':[{'text':m['content']}]} for m in conversation]
                contents[-1]['parts'].extend({'inlineData':{'mimeType':mime,'data':data}} for mime,data in encoded)
                payload={'contents':contents,'systemInstruction':{'parts':[{'text':system}]},'generationConfig':{'maxOutputTokens':output_limit}}
                if schema is not None: payload['generationConfig'].update(responseMimeType='application/json',responseJsonSchema=schema)
                body=checked_body(await transport.post(ENDPOINTS[provider]+'/models/'+quote(config.model,safe='')+':generateContent',headers=headers(provider,secret),json=payload))
                candidates=body.get('candidates',[])
                if not candidates or candidates[0].get('finishReason')!='STOP': raise ValueError('모델 응답이 완료되지 않았거나 거절됐습니다')
                text=''.join(p.get('text','') for p in candidates[0].get('content',{}).get('parts',[]) if not p.get('thought'));usage=usage_numbers(body.get('usageMetadata'))
            else:
                contents=[{'role':m['role'],'content':[{'type':'text','text':m['content']}]} for m in conversation]
                contents[-1]['content'].extend({'type':'image','source':{'type':'base64','media_type':mime,'data':data}} for mime,data in encoded)
                payload={'model':config.model,'system':system,'messages':contents,'max_tokens':output_limit}
                if schema is not None: payload['output_config']={'format':{'type':'json_schema','schema':claude_schema(schema)}}
                body=checked_body(await transport.post(ENDPOINTS[provider]+'/messages',headers=headers(provider,secret),json=payload))
                if body.get('stop_reason')!='end_turn': raise ValueError('모델 응답이 완료되지 않았거나 거절됐습니다')
                text=''.join(p.get('text','') for p in body.get('content',[]) if p.get('type')=='text');usage=usage_numbers(body.get('usage'))
        except httpx.TimeoutException: raise ValueError('모델 응답 제한 시간 초과') from None
        except httpx.HTTPError: raise ValueError('모델에 연결할 수 없습니다') from None
        except (KeyError,TypeError,AttributeError): raise ValueError('모델 응답 형식을 확인하세요') from None
    if not isinstance(text,str) or not text.strip(): raise ValueError('모델의 텍스트 응답이 없습니다')
    if schema is not None:
        try: json.loads(text)
        except ValueError: raise ValueError('모델이 유효한 JSON 결과를 반환하지 않았습니다') from None
    return ProviderResult(digest=actual_digest,text=text,model=body.get('model') or body.get('modelVersion') or config.model,usage=usage,elapsed_ms=round((time.monotonic()-started)*1000))
