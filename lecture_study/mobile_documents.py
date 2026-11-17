"""Native-only freshness checks for document-provider working copies."""

_provider=None


def install(provider):
    global _provider
    if provider is not None and not callable(provider):raise TypeError('문서 제공자 연결을 확인하세요')
    _provider=provider


def status(path):
    if _provider is None:return None
    try:result=_provider(path)
    except OSError:return 'denied'
    if result not in (None,'current','changed','missing','denied'):
        raise ValueError('원본 문서 접근 상태를 확인하지 못했습니다')
    return result
