"""Stage bundled source and the existing frontend, never a vault, model or credential."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]


def stage(source,frontend,destination,platform):
    source,frontend,destination=map(Path,(source,frontend,destination))
    if platform not in ('android','ios'):raise ValueError('Android 또는 iOS를 선택하세요')
    if destination.exists() or destination.is_symlink():raise FileExistsError('새 모바일 출력 폴더를 지정하세요')
    if not (source/'__init__.py').is_file() or not (source/'schema.sql').is_file() or not (frontend/'index.html').is_file():
        raise ValueError('앱 소스와 빌드한 화면이 필요합니다')
    files=[]
    for root,prefix in ((source,'python/lecture_study'),(frontend,'frontend')):
        if destination.resolve().is_relative_to(root.resolve()):raise ValueError('입력 폴더 밖에 출력하세요')
        for path in sorted(root.rglob('*')):
            if path.is_symlink():raise ValueError('모바일 패키지에 심볼릭 링크를 넣을 수 없습니다')
            if not path.is_file():continue
            relative=path.relative_to(root)
            if any(part.startswith('.') or part=='__pycache__' for part in relative.parts):continue
            if root==source and path.suffix not in ('.py','.sql'):continue
            files.append((path,Path(prefix)/relative))
    destination.mkdir(parents=True)
    record={'format':1,'platform':platform,'files':[]}
    for source,relative in files:
        target=destination/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target)
        with target.open('rb') as stream:checksum=hashlib.file_digest(stream,'sha256').hexdigest()
        record['files'].append({'path':relative.as_posix(),'bytes':target.stat().st_size,'sha256':checksum})
    (destination/'manifest.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return record


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--platform',choices=('android','ios'),required=True)
    parser.add_argument('--destination',type=Path,required=True)
    parser.add_argument('--frontend',type=Path,default=ROOT/'frontend/dist')
    args=parser.parse_args()
    result=stage(ROOT/'lecture_study',args.frontend,args.destination,args.platform)
    print(json.dumps({'platform':result['platform'],'files':len(result['files']),'destination':str(args.destination)}))


if __name__=='__main__':main()
