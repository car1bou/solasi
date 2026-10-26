"""Mac image rendering and Vision adapters; neither calls the other."""
import asyncio,json,sys,tempfile
from pathlib import Path
from .transcription import stop_process


async def _call(arguments,payload=None):
    if sys.platform!='darwin':raise ValueError('현재 OS의 필기 이미지 생성기·인식 엔진을 준비하세요')
    encoded=json.dumps(payload).encode()if payload is not None else b''
    if len(encoded)>8*1024*1024:raise ValueError('필기 입력이 너무 큽니다')
    binary=Path(sys.executable).parent/'HandwritingRecognition'
    command=[str(binary)]if getattr(sys,'frozen',False)else['/usr/bin/swift','-module-cache-path',str((Path(tempfile.gettempdir())/'solasi-handwriting-swift-cache').resolve()),str(Path(__file__).parent.parent/'macos/HandwritingRecognition.swift')]
    process=await asyncio.create_subprocess_exec(*command,*map(str,arguments),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    try:
        output,error=await asyncio.wait_for(process.communicate(encoded),90)
        if process.returncode:raise ValueError('로컬 손글씨 처리 실패: '+error.decode(errors='replace')[-200:])
        return json.loads(output)
    finally:await stop_process(process)


async def render_ink(payload,image_path,*,page_source=None,page=1):
    arguments=['--render-only','--image',image_path]
    if page_source:arguments+=['--page-source',page_source,str(page)]
    return await _call(arguments,payload)


async def recognize_image(image_path):
    return await _call(['--recognize-image',image_path])
