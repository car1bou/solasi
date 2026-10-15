import keyring
from keyring.errors import PasswordDeleteError

PROVIDERS=('openai','gemini','claude','exa')


def safe_backend():
    try: backend=keyring.get_keyring()
    except Exception: return None
    if type(backend).__module__ in ('keyring.backends.macOS','keyring.backends.Windows','keyring.backends.SecretService','keyring.backends.kwallet'):
        return backend
    return None


class Secrets:
    def __init__(self,service):
        self.service=service;self.memory={}

    def check(self,provider):
        if provider not in PROVIDERS: raise ValueError('지원하지 않는 제공자입니다')

    def get_secret(self,provider):
        self.check(provider)
        if provider in self.memory: return self.memory[provider]
        backend=safe_backend()
        if backend is None: return None
        try: return backend.get_password(self.service,provider)
        except Exception: raise ValueError('OS 자격증명 저장소를 읽을 수 없습니다') from None

    def set_secret(self,provider,value,persistent):
        self.check(provider)
        if not isinstance(value,str) or not value.strip() or len(value)>4096 or any(ord(c)<33 or ord(c)>126 for c in value): raise ValueError('API 키를 확인하세요')
        backend=safe_backend()
        if persistent and backend is None: raise ValueError('OS 자격증명 저장소를 사용할 수 없습니다. 실행 중 보관을 선택하세요')
        try:
            if persistent: backend.set_password(self.service,provider,value)
            elif backend:
                try: backend.delete_password(self.service,provider)
                except PasswordDeleteError: pass
        except Exception: raise ValueError('OS 자격증명 저장소에 키를 저장·삭제할 수 없습니다') from None
        if persistent: self.memory.pop(provider,None)
        else: self.memory[provider]=value

    def delete_secret(self,provider):
        self.check(provider);backend=safe_backend()
        if backend:
            try: backend.delete_password(self.service,provider)
            except PasswordDeleteError: pass
            except Exception: raise ValueError('OS 자격증명 저장소에서 키를 삭제할 수 없습니다') from None
        self.memory.pop(provider,None)

    def status(self):
        result={}
        for provider in PROVIDERS:
            try: result[provider]={'configured':bool(self.get_secret(provider)),'storage':'memory' if provider in self.memory else 'os','error':None}
            except ValueError as exc: result[provider]={'configured':False,'storage':'os','error':str(exc)}
        return result
