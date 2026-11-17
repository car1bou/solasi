"""Add uninstall modules to a verified deployed engine without reverting newer modules."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import types

ROOT=Path(__file__).resolve().parents[1]
REPLACE=('lecture_study.native_worker','lecture_study.config')
ADD=('lecture_study.uninstall_export','lecture_study.uninstall_plan')


def code_shape(code):
    return (code.co_code,code.co_names,code.co_varnames,code.co_argcount,code.co_posonlyargcount,code.co_kwonlyargcount,
            code.co_flags,code.co_freevars,code.co_cellvars,code.co_exceptiontable,
            tuple(code_shape(value) if isinstance(value,types.CodeType) else value for value in code.co_consts))


def nested(code, names):
    if not names:return code
    found=[value for value in code.co_consts if isinstance(value,types.CodeType) and value.co_name==names[0]]
    if len(found)!=1:raise ValueError('교체할 함수가 유일하지 않습니다: '+'.'.join(names))
    return nested(found[0],names[1:])


def replace_nested(code,names,replacement):
    if not names:return replacement
    return code.replace(co_consts=tuple(replace_nested(value,names[1:],replacement) if isinstance(value,types.CodeType) and value.co_name==names[0] else value for value in code.co_consts))


def patch(source,destination):
    from PyInstaller.archive.readers import CArchiveReader
    from PyInstaller.archive.writers import CArchiveWriter,ZlibArchiveWriter
    from PyInstaller.utils.osx import fix_exe_for_code_signing
    from scripts.install_macos_app import verify_engine,clone_copy
    source=source.resolve(strict=True);destination=destination.absolute()
    if destination.exists():raise ValueError('새 엔진 후보 위치를 지정하세요')
    if shutil.disk_usage(destination.parent if destination.parent.exists() else ROOT).free < 512*1024**2:raise OSError('엔진 후보를 만들려면 최소 512 MiB의 여유 공간이 필요합니다')
    manifest=verify_engine(source)
    archive=CArchiveReader(str(source/'solasi-engine'));pyz=archive.open_embedded_archive('PYZ.pyz')
    for name in REPLACE:
        path=name.replace('.','/')+'.py'
        baseline=subprocess.run(['git','show','HEAD:'+path],cwd=ROOT,capture_output=True,text=True,check=True).stdout
        if code_shape(pyz.extract(name))!=code_shape(compile(baseline,path,'exec')):
            raise ValueError('설치 엔진의 해당 모듈이 기본 소스와 다릅니다. 보안·기능 차이를 먼저 합쳐야 합니다: '+name)
    destination.parent.mkdir(parents=True,exist_ok=True)
    shutil.copytree(source,destination,symlinks=True,copy_function=clone_copy)
    binary=destination/'solasi-engine'
    subprocess.run(['/usr/bin/codesign','--remove-signature',str(binary)],check=True)
    unsigned=CArchiveReader(str(binary))
    with binary.open('rb') as handle:
        prefix=handle.read(unsigned._start_offset)
        handle.seek(unsigned._end_offset-unsigned._COOKIE_LENGTH)
        cookie=struct.unpack(unsigned._COOKIE_FORMAT,handle.read(unsigned._COOKIE_LENGTH))
        pylib=cookie[-1].rstrip(b'\0').decode()
    with tempfile.TemporaryDirectory(prefix='solasi-engine-patch-',dir=destination.parent) as tmp:
        temporary=Path(tmp);entries=[];codes={}
        for name,(kind,_,_) in pyz.toc.items():
            if kind==3:entries.append((name,'-','PYMODULE'));continue
            codes[name]=pyz.extract(name)
            path=name.replace('.','/')+('/__init__.py' if kind==1 else '.py')
            entries.append((name,path,'PYMODULE'))
        server_name='lecture_study.server';function_path=('create_app','knowledge_loop')
        baseline_source=subprocess.run(['git','show','HEAD:lecture_study/server.py'],cwd=ROOT,capture_output=True,text=True,check=True).stdout
        # The deployed egress fix passes the dedicated offline runtime into handwriting.
        baseline_source=baseline_source.replace('await recognize_ink(snapshot))','await recognize_ink(snapshot,runtime_dir=config.runtime_dir))')
        original_function=nested(codes[server_name],function_path)
        if code_shape(original_function)!=code_shape(nested(compile(baseline_source,'lecture_study/server.py','exec'),function_path)):
            raise ValueError('설치된 자동 처리 함수가 기본 소스와 다릅니다. 먼저 차이를 합쳐야 합니다')
        replacement=nested(compile((ROOT/'lecture_study/server.py').read_text(),'lecture_study/server.py','exec'),function_path)
        if replacement.co_freevars!=original_function.co_freevars:raise ValueError('자동 처리 함수의 클로저 계약이 다릅니다')
        codes[server_name]=replace_nested(codes[server_name],function_path,replacement)
        for name in (*REPLACE,*ADD):
            path=name.replace('.','/')+'.py'
            codes[name]=compile((ROOT/path).read_text(),path,'exec')
            if name not in pyz.toc:entries.append((name,path,'PYMODULE'))
        zpath=temporary/'PYZ.pyz';ZlibArchiveWriter(str(zpath),entries,codes)
        c_entries=[]
        for index,(name,item) in enumerate(unsigned.toc.items()):
            kind=item[-1];compress=item[-2]
            if kind=='z':path=zpath
            elif kind in ('s','m','M'):
                path=temporary/(str(index)+'.pyc')
                path.write_bytes(importlib.util.MAGIC_NUMBER+b'\0'*12+unsigned.extract(name))
            else:
                path=temporary/str(index);path.write_bytes(unsigned.extract(name))
            c_entries.append((name,str(path),compress,kind))
        for option in unsigned.options:c_entries.append((option,'',False,'o'))
        package=temporary/'engine.pkg';CArchiveWriter(str(package),c_entries,pylib)
        with binary.open('wb') as handle:
            handle.write(prefix)
            with package.open('rb') as payload:shutil.copyfileobj(payload,handle)
        fix_exe_for_code_signing(str(binary))
    subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(binary)],check=True)
    # Prove every other module still has the deployed behavior, including egress guards.
    rebuilt=CArchiveReader(str(binary)).open_embedded_archive('PYZ.pyz')
    unchanged=0
    for name,(kind,_,_) in pyz.toc.items():
        if name in REPLACE or kind==3:continue
        expected=codes[name] if name=='lecture_study.server' else pyz.extract(name)
        if code_shape(expected)!=code_shape(rebuilt.extract(name)):raise ValueError('예상하지 않은 모듈 변경: '+name)
        if name!='lecture_study.server':unchanged+=1
    subprocess.run(['/usr/bin/xcrun','swiftc','-O','-target','arm64-apple-macosx'+manifest['minimum_macos'],'-module-cache-path',str(ROOT/'.local-state/swift-cache'),str(ROOT/'macos/NotebookPDF.swift'),'-o',str(destination/'NotebookPDF')],check=True)
    for name in ('solasi-engine','NotebookPDF'):
        path=destination/name
        with path.open('rb') as handle:digest=hashlib.file_digest(handle,'sha256').hexdigest()
        manifest['files'][name]={'bytes':path.stat().st_size,'sha256':digest}
    (destination/'bundle-manifest.json').write_text(json.dumps(manifest,indent=2))
    proof={'format':1,'source':str(source),'replaced':REPLACE,'added':ADD,'unchanged_modules':unchanged,
           'patched_functions':['lecture_study.server.create_app.knowledge_loop'],'method':'original deployed PYZ code objects retained except explicitly checked modules'}
    (destination/'uninstall-patch-proof.json').write_text(json.dumps(proof,indent=2))
    subprocess.run([str(binary),'--self-check'],cwd=destination,check=True)
    verify_engine(destination)
    return proof


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-engine',type=Path,required=True);parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(patch(args.source_engine,args.destination),indent=2))

if __name__=='__main__':main()
