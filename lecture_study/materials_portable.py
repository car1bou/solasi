"""Pillow/PDFium operations, called only inside an isolated material worker."""
import math
from contextlib import closing
from pathlib import Path
from PIL import Image,ImageDraw,ImageOps


def _is_pdf(source):
    with Path(source).open('rb') as handle:return handle.read(5)==b'%PDF-'


def _image(source):
    with Image.open(source) as image:
        if image.width>12000 or image.height>12000:raise ValueError('이미지 크기를 확인하세요')
        oriented=ImageOps.exif_transpose(image).convert('RGBA')
        background=Image.new('RGBA',oriented.size,'white');background.alpha_composite(oriented)
        return background.convert('RGB')


def read_metadata(source):
    if not _is_pdf(source):
        with _image(source) as image:return [{'page':1,'width':image.width,'height':image.height,'rotation':0}]
    import pypdfium2 as pdfium
    pages=[]
    with pdfium.PdfDocument(source) as document:
        for index in range(len(document)):
            with closing(document[index]) as page:
                width,height=page.get_size()
                if not all(math.isfinite(v) and 0<v<=100000 for v in (width,height)):raise ValueError('원본 페이지 크기를 확인하세요')
                pages.append({'page':index+1,'width':width,'height':height,'rotation':page.get_rotation()})
    if not pages:raise ValueError('원본 페이지를 확인하세요')
    return pages


def page_image(source,number,*,size=None):
    if not isinstance(number,int) or number<1:raise ValueError('원본 페이지를 확인하세요')
    if _is_pdf(source):
        import pypdfium2 as pdfium
        with pdfium.PdfDocument(source) as document:
            if number>len(document):raise ValueError('원본 페이지를 확인하세요')
            with closing(document[number-1]) as page:
                width,height=page.get_size()
                scale=max(size[0]/width,size[1]/height) if size else 150/72
                if max(width*scale,height*scale)>12000:raise ValueError('페이지 이미지 크기를 확인하세요')
                with closing(page.render(scale=scale)) as bitmap:image=bitmap.to_pil().convert('RGB')
    else:
        if number!=1:raise ValueError('원본 페이지를 확인하세요')
        image=_image(source)
    if size and image.size!=size:
        resized=image.resize(size,Image.Resampling.LANCZOS);image.close();image=resized
    return image


def render_page(source,number,output,*,size=None):
    with page_image(source,number,size=size) as image:
        image.save(output,format='PNG')
        return {'renderer':'pillow-pdfium-v1','width':image.width,'height':image.height}


def render_ink(payload,output,*,page_source=None,page=1):
    width,height=payload['page_width'],payload['page_height'];strokes=payload['strokes']
    if not all(isinstance(v,(int,float)) and math.isfinite(v) and 0<v<=100000 for v in (width,height)) or not isinstance(strokes,list) or len(strokes)>2000 or sum(len(s['points'])for s in strokes)>100000:raise ValueError('페이지·필기 크기를 확인하세요')
    scale=min(3,2400/max(width,height));size=(max(1,int(width*scale)),max(1,int(height*scale)))
    with page_image(page_source,page,size=size) if page_source else Image.new('RGB',size,'white') as image:
        draw=ImageDraw.Draw(image)
        for stroke in strokes:
            if stroke['tool']!='pen':continue
            points=stroke['points'];line_width=stroke['width']
            if not isinstance(line_width,(int,float)) or not math.isfinite(line_width) or not .0002<=line_width<=.1 or not points or any(not isinstance(p.get(key),(int,float)) or not math.isfinite(p[key]) or not 0<=p[key]<=1 for p in points for key in ('x','y','pressure')):raise ValueError('획 좌표를 확인하세요')
            for index,point in enumerate(points):
                before=points[max(0,index-1)]
                diameter=max(1,line_width*size[0]*(.35+.65*(before['pressure']+point['pressure'])/2))
                a=(before['x']*size[0],before['y']*size[1]);b=(point['x']*size[0],point['y']*size[1]);radius=diameter/2
                if index:draw.line((a,b),fill='black',width=round(diameter))
                # Pillow lines have square ends; round both endpoints like CoreGraphics.
                for x,y in (a,b):draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill='black')
        image.save(output,format='PNG')
    return {'renderer':'pillow-pdfium-v1','width':size[0],'height':size[1]}
