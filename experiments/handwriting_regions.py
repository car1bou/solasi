"""Strict geometry for local OCR comparisons, not a product segmentation engine."""
import json,math
from PIL import ImageOps

CATEGORIES=('Caption','Footnote','Formula','List-item','Page-footer','Page-header','Picture','Section-header','Table','Text','Title')


def crop_regions(image,rows):
    image=ImageOps.exif_transpose(image).convert('RGB')
    if not isinstance(rows,list)or not 0<len(rows)<=64:raise ValueError('Invalid region count')
    result=[];seen=set()
    for row in rows:
        if not isinstance(row,dict):raise ValueError('Invalid region')
        ident=row.get('id');bbox=row.get('bbox')
        if not isinstance(ident,str)or not ident or ident in seen:raise ValueError('Invalid region ID')
        if row.get('kind')not in('text','formula','mixed','unsupported'):raise ValueError('Invalid region kind')
        if not isinstance(bbox,list)or len(bbox)!=4 or any(type(x)is not int for x in bbox):raise ValueError('Invalid region coordinates')
        x1,y1,x2,y2=bbox
        if not(0<=x1<x2<=image.width and 0<=y1<y2<=image.height):raise ValueError('Region outside source image')
        seen.add(ident);result.append((dict(row),image.crop(tuple(bbox))))
    return result


def parse_layout(raw,source_size,processed_size):
    try:rows=json.loads(raw)
    except (ValueError,TypeError):raise ValueError('Invalid layout JSON')from None
    if not isinstance(rows,list)or not 0<len(rows)<=64:raise ValueError('Invalid layout list')
    if any(type(n)is not int or n<=0 for n in(*source_size,*processed_size)):raise ValueError('Invalid image dimensions')
    width,height=source_size;pw,ph=processed_size;result=[]
    for index,row in enumerate(rows):
        if not isinstance(row,dict)or row.get('category')not in CATEGORIES:raise ValueError('Invalid layout category')
        box=row.get('bbox')
        if not isinstance(box,list)or len(box)!=4 or any(type(n)not in(int,float)or not math.isfinite(n)for n in box):raise ValueError('Invalid layout coordinates')
        x1,y1,x2,y2=box
        if not(0<=x1<x2<=pw and 0<=y1<y2<=ph):raise ValueError('Layout outside processed image')
        kind='formula'if row['category']=='Formula'else'unsupported'if row['category']in('Picture','Table')else'mixed'
        result.append({'id':f'auto_{index:02d}','kind':kind,'category':row['category'],
                       'bbox':[math.floor(x1*width/pw),math.floor(y1*height/ph),math.ceil(x2*width/pw),math.ceil(y2*height/ph)]})
    return result
