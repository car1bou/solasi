"""Patch verified deployed engine modules, retaining unrelated deployed fixes."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
from scripts.patch_macos_engine import code_shape, nested, replace_nested
from scripts.install_macos_app import verify_engine, clone_copy

ROOT=Path(__file__).resolve().parents[1]
REPLACE=('lecture_study.server','lecture_study.lifecycle','lecture_study.db','lecture_study.uninstall_export')
ADD=('lecture_study.study_memory','lecture_study.study_memory_api')


def original_source(name, source):
    if name=='lecture_study.server':
        source=source.replace('                if await app.state.study_background_tick():\n                    await asyncio.sleep(3)\n                    continue\n','')
        source=source.replace('    from .study_memory_api import attach_study_memory\n    attach_study_memory(app,db,config,provider_config,generation_slot,local_embedding_client)\n','')
        source=source.replace('        result=override_attempt(db,ident,body.grade,body.explanation)\n        from .study_memory import sync_quizzes\n        sync_quizzes(db)\n        await app.state.study_cancel_obsolete()\n        return result\n','        return override_attempt(db,ident,body.grade,body.explanation)\n')
    elif name=='lecture_study.lifecycle':
        source=source.replace('        from .study_memory import remove_session_context\n        remove_session_context(db,sid)\n','')
    elif name=='lecture_study.db':
        source=source.replace('if version>20:', 'if version>19:')
    elif name=='lecture_study.uninstall_export':
        start=source.index('        from .study_memory import export_records\n')
        end=source.index('        from .transcription import list_transcripts\n',start)
        source=source[:start]+source[end:]
        start=source.index("    if receipt.get('study'):\n")
        end=source.index("    for source in receipt['sources']:\n",start)
        source=source[:start]+source[end:]
    return source


def patch(source, destination):
    from PyInstaller.archive.readers import CArchiveReader
    from PyInstaller.archive.writers import CArchiveWriter,ZlibArchiveWriter
    from PyInstaller.utils.osx import fix_exe_for_code_signing
    source=source.resolve(strict=True);destination=destination.absolute()
    if destination.exists():raise ValueError('새 후보 엔진 위치를 사용하세요')
    manifest=verify_engine(source)
    archive=CArchiveReader(str(source/'solasi-engine'));pyz=archive.open_embedded_archive('PYZ.pyz')
    replacements={}
    for name in REPLACE:
        path=name.replace('.','/')+'.py';current=(ROOT/path).read_text()
        if code_shape(pyz.extract(name))!=code_shape(compile(original_source(name,current),path,'exec')):
            raise ValueError('설치 모듈과 기반 소스가 다릅니다. 덮어쓰지 않습니다: '+name)
        replacements[name]=compile(current,path,'exec')
    name='lecture_study.direct_models';path=name.replace('.','/')+'.py'
    current=(ROOT/path).read_text()
    baseline=current.replace("                manifest_url=base+('/blobs/sha256:'+expected['digest'] if runner=='mlx' else '/manifests/'+tag)\n                async with transport.stream('GET',manifest_url) as response:","                async with transport.stream('GET',base+'/manifests/'+tag) as response:")
    names=('DirectModels','pull');old=pyz.extract(name)
    if code_shape(nested(old,names))!=code_shape(nested(compile(baseline,path,'exec'),names)):
        raise ValueError('설치된 모델 다운로드 함수가 예상 기반과 다릅니다')
    replacement=nested(compile(current,path,'exec'),names)
    if replacement.co_freevars!=nested(old,names).co_freevars:raise ValueError('모델 다운로드 클로저가 다릅니다')
    replacements[name]=replace_nested(old,names,replacement)
    old_schema=(source/'_internal/lecture_study/schema.sql').read_text()
    schema=(ROOT/'lecture_study/schema.sql').read_text()
    baseline=schema[:schema.index('CREATE TABLE IF NOT EXISTS study_threads')]+ 'PRAGMA user_version=19;\n'
    if old_schema.strip()!=baseline.strip():raise ValueError('배포된 DB 스키마가 예상 기반과 다릅니다')
    destination.parent.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(destination.parent).free<256*1024**2:raise OSError('후보 엔진 패치에 최소 256 MiB가 필요합니다')
    shutil.copytree(source,destination,symlinks=True,copy_function=clone_copy)
    binary=destination/'solasi-engine'
    subprocess.run(['/usr/bin/codesign','--remove-signature',str(binary)],check=True)
    unsigned=CArchiveReader(str(binary))
    with binary.open('rb') as handle:
        prefix=handle.read(unsigned._start_offset);handle.seek(unsigned._end_offset-unsigned._COOKIE_LENGTH)
        cookie=struct.unpack(unsigned._COOKIE_FORMAT,handle.read(unsigned._COOKIE_LENGTH));pylib=cookie[-1].rstrip(b'\0').decode()
    with tempfile.TemporaryDirectory(prefix='study-patch-',dir=destination.parent) as tmp:
        tmp=Path(tmp);entries=[];codes={}
        for name,(kind,_,_) in pyz.toc.items():
            if kind==3:entries.append((name,'-','PYMODULE'));continue
            codes[name]=replacements.get(name,pyz.extract(name))
            entries.append((name,name.replace('.','/')+('/__init__.py' if kind==1 else '.py'),'PYMODULE'))
        for name in ADD:
            path=name.replace('.','/')+'.py';codes[name]=compile((ROOT/path).read_text(),path,'exec')
            if name not in pyz.toc:entries.append((name,path,'PYMODULE'))
        zpath=tmp/'PYZ.pyz';ZlibArchiveWriter(str(zpath),entries,codes)
        c_entries=[]
        for index,(name,item) in enumerate(unsigned.toc.items()):
            kind=item[-1];compress=item[-2]
            if kind=='z':path=zpath
            elif kind in ('s','m','M'):
                path=tmp/(str(index)+'.pyc');path.write_bytes(importlib.util.MAGIC_NUMBER+b'\0'*12+unsigned.extract(name))
            else:path=tmp/str(index);path.write_bytes(unsigned.extract(name))
            c_entries.append((name,str(path),compress,kind))
        for option in unsigned.options:c_entries.append((option,'',False,'o'))
        package=tmp/'engine.pkg';CArchiveWriter(str(package),c_entries,pylib)
        with binary.open('wb') as handle:
            handle.write(prefix)
            with package.open('rb') as payload:shutil.copyfileobj(payload,handle)
        fix_exe_for_code_signing(str(binary))
    subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(binary)],check=True)
    (destination/'_internal/lecture_study/schema.sql').write_text(schema)
    rebuilt=CArchiveReader(str(binary)).open_embedded_archive('PYZ.pyz');unchanged=0
    for name,(kind,_,_) in pyz.toc.items():
        if kind==3:continue
        expected=codes[name]
        if code_shape(expected)!=code_shape(rebuilt.extract(name)):raise ValueError('엔진 모듈 검증 실패: '+name)
        if name not in replacements:unchanged+=1
    for name in ('solasi-engine','_internal/lecture_study/schema.sql'):
        path=destination/name
        with path.open('rb') as handle:digest=hashlib.file_digest(handle,'sha256').hexdigest()
        manifest['files'][name]={'bytes':path.stat().st_size,'sha256':digest}
    (destination/'bundle-manifest.json').write_text(json.dumps(manifest,indent=2))
    proof={'replaced':REPLACE,'patched_functions':['lecture_study.direct_models.DirectModels.pull'],'added':ADD,'unchanged_modules':unchanged,'schema':20,'all_module_code_objects_verified':True}
    (destination/'study-memory-patch-proof.json').write_text(json.dumps(proof,indent=2))
    subprocess.run([str(binary),'--self-check'],cwd=destination,check=True)
    verify_engine(destination)
    return proof


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-engine',type=Path,required=True);parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(patch(args.source_engine,args.destination),indent=2))
