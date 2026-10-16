"""The desktop server belongs to the native app that launched it."""
import asyncio
import os
import signal


def native_owner():
    value=os.environ.get('SOLASI_OWNER_PID')
    if value is None:return None
    try:owner=int(value)
    except ValueError:raise ValueError('앱 실행 프로세스 설정이 유효하지 않습니다') from None
    if owner<=1:raise ValueError('앱 실행 프로세스 설정이 유효하지 않습니다')
    return owner


async def watch_owner(owner):
    while os.getppid()==owner:
        await asyncio.sleep(1)
    # Uvicorn owns SIGTERM handling and closes sockets, saved audio and model tasks.
    os.kill(os.getpid(),signal.SIGTERM)
