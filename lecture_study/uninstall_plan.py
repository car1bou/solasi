"""Build a narrowly scoped removal inventory; never delete here."""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import stat

from .uninstall_export import identity, regular_file


def snapshot(path,mutable=False,allow_link=False):
    path=Path(path)
    if not (allow_link and path.is_symlink()) and (path.resolve()!=path or path.is_symlink()):raise ValueError('삭제 대상에 외부 파일 연결이 있습니다: '+str(path))
    info=path.lstat();entries=[]
    def visit(item):
        info=item.lstat();kind='link' if stat.S_ISLNK(info.st_mode) else 'directory' if stat.S_ISDIR(info.st_mode) else 'file' if stat.S_ISREG(info.st_mode) else 'other'
        if kind=='other' or info.st_uid!=os.getuid():raise ValueError('삭제 대상의 소유권·종류를 확인할 수 없습니다: '+str(item))
        entries.append({'name':str(item.relative_to(path)),'device':info.st_dev,'inode':info.st_ino,'kind':kind,'bytes':info.st_size,'mtime':info.st_mtime_ns})
        if kind=='directory':
            for child in sorted(item.iterdir()):visit(child)
    visit(path)
    return {'path':str(path),'device':info.st_dev,'inode':info.st_ino,'mutable':mutable,'entries':entries}


def build_plan(db,config,bundle,receipt):
    from .runtime import manifest
    bundle=Path(bundle)
    if not bundle.is_absolute() or bundle.resolve()!=bundle or bundle.suffix!='.app':raise ValueError('앱 경로를 확인하세요')
    info=plistlib.loads((bundle/'Contents/Info.plist').read_bytes());identifier=info.get('CFBundleIdentifier')
    if identifier not in ('local.solasi.launcher','local.solasi.internal-validation') or info.get('CFBundleExecutable')!='Solasi':raise ValueError('솔라시 앱이 아닙니다')
    settings=json.loads((bundle/'Contents/Resources/launch.json').read_text())
    data=config.data_dir.resolve();runtime=config.runtime_dir.resolve()
    if settings.get('data')!=str(data) or settings.get('runtime')!=str(runtime):raise ValueError('앱의 보관함·엔진 경로가 일치하지 않습니다')
    for root in (data,runtime):
        if root in (Path('/'),Path.home(),Path.home()/'Library') or bundle.is_relative_to(root):raise ValueError('삭제 경로가 너무 넓습니다')
    export=Path(receipt['directory'])
    if any(export.is_relative_to(root) or root.is_relative_to(export) for root in (data,runtime,bundle)):raise ValueError('보존 위치와 삭제 위치가 겹칩니다')
    targets=[];preserved=[];seen=set()
    def add(path,mutable=False,allow_link=False):
        path=Path(path)
        if not path.exists() and not path.is_symlink():return
        if str(path) in seen:return
        seen.add(str(path));targets.append(snapshot(path,mutable,allow_link))
    # Checkpoint after quiescence so a normal worker close cannot change the DB proof.
    db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    database_proof=regular_file(data/'app.sqlite3')
    for name in ('app.sqlite3','app.sqlite3-wal','app.sqlite3-shm','instance.lock'):add(data/name,True)
    asset_ids={r[0] for r in db.execute('SELECT id FROM assets')}
    recording_ids={r[0] for r in db.execute('SELECT id FROM recordings')}
    managed_asset=re.compile(r'(original\.(pdf|png|jpg|txt|md)|extraction\.json|document-[a-f0-9]{64}-page-[0-9]+\.png|page-[0-9]+\.png|image-[A-Za-z0-9_.-]+\.(png|jpg))')
    for base,ids in ((data/'assets',asset_ids),(data/'audio',recording_ids)):
        if not base.exists():continue
        if base.resolve()!=base:raise ValueError('관리 폴더가 외부로 연결되어 있습니다')
        for directory in base.iterdir():
            if directory.name not in ids or not directory.is_dir() or directory.is_symlink():preserved.append(str(directory));continue
            for child in directory.iterdir():
                if (base.name=='audio' and child.name=='raw.wav') or (base.name=='assets' and managed_asset.fullmatch(child.name)):add(child)
                else:preserved.append(str(child))
    cache=data/'model-cache'
    if cache.exists():
        if cache.resolve()!=cache:raise ValueError('모델 캐시 경로가 외부로 연결되었습니다')
        cache_json={'config.json','tokenizer.json','tokenizer_config.json','generation_config.json','special_tokens_map.json','preprocessor_config.json','processor_config.json','model.safetensors.index.json'}
        for path in cache.rglob('*'):
            if path.is_dir() and not path.is_symlink():continue
            relative=path.relative_to(cache)
            known_view=bool(re.fullmatch(r'[a-f0-9]{64}',relative.parts[0]))
            if known_view and path.is_symlink() and re.fullmatch(r'model-[0-9]{5}\.safetensors',path.name) and path.resolve().is_relative_to(runtime/'ollama-models/blobs'):
                add(path,allow_link=True)
            elif known_view and path.name in cache_json and path.is_file() and not path.is_symlink():add(path)
            else:preserved.append(str(path))
    known_data={'app.sqlite3','app.sqlite3-wal','app.sqlite3-shm','instance.lock','assets','audio','model-cache'}
    preserved.extend(str(p) for p in data.iterdir() if p.name not in known_data)
    pinned=manifest()
    for item in pinned['assets'].values():add(runtime/item['path'])
    for component in pinned['components'].values():
        directory=runtime/component.get('install_dir','__missing__')
        for name in component.get('files',{}):add(directory/name)
        for name in component.get('symlinks',{}):
            # Symlink artifacts are not proof of an owned external tree.
            link=directory/name
            if link.is_symlink():preserved.append(str(link))
    for component in ('asr','direct-engines','ffmpeg'):
        directory=runtime/component;record=directory/'receipt.json'
        if record.is_file() and not record.is_symlink():
            values=json.loads(record.read_text())
            for name in values.get('files',{}):
                relative=Path(name)
                if relative.is_absolute() or '..' in relative.parts:raise ValueError('엔진 설치 기록 경로 오류')
                add(directory/relative)
            add(record)
    models=runtime/'ollama-models'
    if models.exists():
        if models.resolve()!=models:raise ValueError('모델 폴더가 외부로 연결되어 있습니다')
        for path in models.rglob('*'):
            if path.is_symlink():raise ValueError('모델 경로에 외부 파일 연결이 있습니다')
            if path.is_file():
                relative=path.relative_to(models)
                if (relative.parts[0]=='blobs' and re.fullmatch(r'sha256-[a-f0-9]{64}(?:-partial.*)?',path.name)) or (str(relative).startswith('manifests/registry.ollama.ai/library/') and len(relative.parts)==5):add(path)
                else:preserved.append(str(path))
    targeted={t['path'] for t in targets}
    for path in runtime.rglob('*'):
        if path.is_file() and str(path) not in targeted:preserved.append(str(path))
    home=Path.home()
    os_paths=[]
    for relative in (f'Library/Preferences/{identifier}.plist',f'Library/Logs/{identifier}',f'Library/Caches/{identifier}',f'Library/WebKit/{identifier}',f'Library/HTTPStorages/{identifier}',f'Library/Saved Application State/{identifier}.savedState'):
        os_paths.append(str(home/relative));add(home/relative,True)
    add(bundle)
    return {'format':1,'app':str(bundle),'data':str(data),'runtime':str(runtime),'bundle_id':identifier,
            'os_paths':os_paths,'service':'LectureStudy:'+hashlib.sha256(str(data).encode()).hexdigest()[:16],
            'receipt':receipt,'database_proof':database_proof,'targets':targets,'preserved':sorted(set(preserved)),
            'bytes':sum(entry['bytes'] for target in targets for entry in target['entries'] if entry['kind']=='file')}
