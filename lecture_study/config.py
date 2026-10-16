from dataclasses import dataclass
from pathlib import Path


@dataclass
class AppConfig:
    data_dir: Path
    runtime_dir: Path
    host: str = "127.0.0.1"
    port: int = 8765
    embedded: bool = False

    def __post_init__(self):
        self.data_dir=self.data_dir.resolve()
        self.runtime_dir=self.runtime_dir.resolve()


def acquire_data_lock(directory):
    import os
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    handle=(directory/'instance.lock').open('a+b')
    try:
        if os.name=='nt':
            import msvcrt
            if handle.seek(0,2)==0:handle.write(b'\0');handle.flush()
            handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        handle.close();raise ValueError('이 데이터 폴더의 앱이 이미 실행 중입니다') from None
    return handle
