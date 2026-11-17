"""Windows ink renderer and bundled Korean/English Tesseract OCR adapter."""
import asyncio,csv,io,json,math,subprocess,tempfile
from pathlib import Path
from PIL import Image
from .execution import worker_command
from .transcription import stop_process


def ocr_data_ready(runtime_dir):
    from .runtime import manifest,matches
    spec=manifest()
    return all(matches(Path(runtime_dir)/spec['assets'][key]['path'],spec['assets'][key])for key in spec['components']['ocr']['assets'])


def parse_tsv(text,width,height):
    lines={}
    try:
        reader=csv.DictReader(io.StringIO(text),delimiter='\t',quoting=csv.QUOTE_NONE)
        if not {'level','page_num','block_num','par_num','line_num','left','top','width','height','conf','text'}<=set(reader.fieldnames or []):raise ValueError('OCR 결과 형식을 확인하세요')
        for row in reader:
            if row['level']!='5' or not row['text'].strip():continue
            x,y,w,h,confidence=(float(row[k])for k in ('left','top','width','height','conf'))
            if not all(math.isfinite(v)for v in (x,y,w,h,confidence)) or w<0 or h<0 or not 0<=confidence<=100:raise ValueError('OCR 영역을 확인하세요')
            left,top=max(0,x),max(0,y);right,bottom=min(width,x+w),min(height,y+h)
            if right<=left or bottom<=top:continue
            key=tuple(row[k]for k in ('page_num','block_num','par_num','line_num'))
            lines.setdefault(key,[]).append((left,top,right,bottom,row['text'].strip(),confidence/100))
            if len(lines)>500:raise ValueError('인식 영역이 너무 많습니다')
    except (KeyError,TypeError,csv.Error):raise ValueError('OCR 결과 형식을 확인하세요')from None
    regions=[]
    for words in lines.values():
        x=min(w[0]for w in words)/width;y=min(w[1]for w in words)/height
        right=max(w[2]for w in words)/width;bottom=max(w[3]for w in words)/height
        content=' '.join(w[4]for w in words)
        if len(content)>20000:raise ValueError('인식문이 너무 깁니다')
        regions.append({'bbox':[x,y,right-x,bottom-y],'text':content,'edge_touching':x<.015 or y<.015 or right>.985 or bottom>.985,'candidates':[{'text':content,'score':sum(w[5]for w in words)/len(words)}]})
    return regions


async def render_ink(payload,image_path,*,page_source=None,page=1):
    encoded=json.dumps(payload).encode()
    if len(encoded)>8*1024*1024:raise ValueError('필기 입력이 너무 큽니다')
    process=await asyncio.create_subprocess_exec(*worker_command('material-worker',['ink-render','-',image_path,'-','-',1,'png',page_source or '',page]),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        output,error=await asyncio.wait_for(process.communicate(encoded),90)
        if process.returncode:raise ValueError('로컬 필기 이미지 생성 실패: '+error.decode(errors='replace')[-200:])
        return json.loads(output)
    finally:await stop_process(process)


async def recognize_image(image_path,*,runtime_dir=None):
    if runtime_dir is None:raise ValueError('한국어·영어 OCR 런타임 경로를 확인하세요')
    from .runtime import ocr_binary
    binary=await asyncio.to_thread(ocr_binary,runtime_dir)
    if not await asyncio.to_thread(ocr_data_ready,runtime_dir):raise ValueError('한국어·영어 OCR 데이터 검증 실패 · 엔진 준비를 다시 실행하세요')
    image_path=Path(image_path).resolve(strict=True)
    if image_path.stat().st_size>20*1024*1024:raise ValueError('이미지 크기를 확인하세요')
    with Image.open(image_path)as image:
        width,height=image.size
        if width>12000 or height>12000:raise ValueError('이미지 크기를 확인하세요')
    with tempfile.TemporaryFile()as output,tempfile.TemporaryFile()as error:
        process=await asyncio.create_subprocess_exec(str(binary),str(image_path),'stdout','--tessdata-dir',str(Path(runtime_dir)/'tessdata'),'-l','kor+eng','--psm','3','-c','tessedit_create_tsv=1',stdout=output,stderr=error,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            await asyncio.wait_for(process.wait(),90)
            if process.returncode:raise ValueError('한국어·영어 OCR 처리 실패 · 엔진과 원본 이미지를 확인하세요')
            if output.tell()>16*1024*1024:raise ValueError('OCR 결과가 너무 큽니다')
            output.seek(0);text=output.read().decode('utf-8-sig')
        finally:await stop_process(process)
    return {'engine':'tesseract-5/kor+eng/tsv-v1','languages':['ko-KR','en-US'],'regions':parse_tsv(text,width,height)}
