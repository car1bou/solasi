"""Small fixed speech/noise evaluation set; stream only two leading Seoul Corpus files."""
import argparse,binascii,hashlib,io,json,re,struct,subprocess,tarfile,urllib.request,wave,zlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];RUNTIME=ROOT/'.local-state/runtime';FOLDER=RUNTIME/'speech-conditions-20261014'
URL='https://openslr.trmal.net/resources/113/'

def zip_prefix(handle,suffix,count,*,names=None,max_bytes=128*1024**2):
    pending=b'';consumed=0;found=[];visited=0
    def read(n,exact=True):
        nonlocal pending,consumed
        out=pending[:n];pending=pending[n:]
        while len(out)<n:
            chunk=handle.read(n-len(out))
            if not chunk:
                if exact:raise ValueError('Truncated ZIP prefix')
                break
            out+=chunk;consumed+=len(chunk)
            if consumed>max_bytes:raise ValueError('Sample prefix exceeds transfer limit')
        return out
    while visited<count:
        assert read(4)==b'PK\x03\x04','Expected ZIP local entry'
        _,flags,method,_,_,crc,csize,usize,nlen,xlen=struct.unpack('<HHHHHIIIHH',read(26))
        assert method in (0,8) and not flags&1 and nlen<=256 and xlen<=65535,'Unsupported ZIP entry'
        name=read(nlen).decode('utf-8');read(xlen);decoder=zlib.decompressobj(-15);data=bytearray();compressed=0
        if method==0:
            assert not flags&8 and csize<=64*1024**2
            data.extend(read(csize));compressed=csize
        while method==8 and not decoder.eof:
            chunk=read(4096,False)
            if not chunk:raise ValueError('Truncated deflate entry')
            decoded=decoder.decompress(chunk,64*1024**2-len(data)+1);data.extend(decoded)
            if len(data)>64*1024**2:raise ValueError('Entry exceeds 64MiB')
            compressed+=len(chunk)-len(decoder.unused_data);pending=decoder.unused_data+pending
        if flags&8:
            first=read(4)
            crc,csize,usize=struct.unpack('<III',read(12)) if first==b'PK\x07\x08' else struct.unpack('<III',first+read(8))
        assert (csize,usize,crc)==(compressed,len(data),binascii.crc32(data)&0xffffffff),'ZIP entry checksum/size differs'
        if name.startswith('__MACOSX/') or name.endswith('/'):continue
        assert re.fullmatch(r'(?:[a-zA-Z0-9_-]+/)?[a-zA-Z0-9_-]+\.'+re.escape(suffix),name),name
        visited+=1
        if names is None or name in names:found.append((name,bytes(data)))
    return found,consumed

def fetch(kind,suffix):
    with urllib.request.urlopen(URL+kind+'.tgz',timeout=120) as response:
        assert response.status==200
        with tarfile.open(fileobj=response,mode='r|gz') as archive:
            item=next(iter(archive));assert item.isfile() and item.name.endswith('.zip')
            with archive.extractfile(item) as handle:files,size=zip_prefix(handle,suffix,2)
    return files,{'url':URL+kind+'.tgz','outer_member':item.name,'zip_prefix_read_bytes':size,'archive_completed':False}

def utterances(text):
    blocks=re.split(r'\n\s*item \[\d+\]:',text)
    assert len(blocks)==8 and 'name = "utt.ortho."' in blocks[7]
    rows=[{'start':float(a),'end':float(b),'reference':t.replace('""','"')} for a,b,t in re.findall(r'intervals \[\d+\]:\s+xmin = (\S+)\s+xmax = (\S+)\s+text = "((?:[^"\n]|"")*)"',blocks[7])]
    assert rows and all(0<=r['start']<r['end'] for r in rows)
    return rows

def main():
    FOLDER.mkdir(parents=True,exist_ok=True);proof=FOLDER/'seoul-prefix.json'
    if proof.exists():
        collected=json.loads(proof.read_text());assert collected['ready']
        for row in collected['files']:assert hashlib.sha256(Path(row['path']).read_bytes()).hexdigest()==row['sha256']
    else:
        labels,label_transfer=fetch('label','TextGrid');sounds,sound_transfer=fetch('sound','flac');assert [Path(n).stem for n,_ in labels]==[Path(n).stem for n,_ in sounds]
        collected={'ready':True,'source':'https://www.openslr.org/113/','license':'CC BY-NC 2.0; local noncommercial evaluation only; not bundled or redistributed','transfers':[label_transfer,sound_transfer],'files':[]}
        for name,data in labels+sounds:
            path=FOLDER/name;path.write_bytes(data);collected['files'].append({'name':name,'path':str(path),'bytes':len(data),'zip_crc_verified':True,'sha256':hashlib.sha256(data).hexdigest()})
        proof.write_text(json.dumps(collected,ensure_ascii=False,indent=2))
    manifest=json.loads((RUNTIME/'diverse-audio-20261014/manifest.json').read_text());clips=manifest['clips'];selected=[c for c in clips if c['group'] in ('lowgain5','snr105')]
    bases={c['derived_from'] for c in selected};selected=[c|{'group':'clean5'} for c in clips if c['id'] in bases]+selected
    selected += [c|{'group':'rooms6'} for c in clips if c['group']=='deeply18' and c['paired_group_id'] in ('pair1','pair4')]
    selected += [c|{'group':'talk6'} for c in clips if c['group']=='pansori24'][::4]
    for name in ('s01m16f1','s01m16f2'):
        rows=utterances((FOLDER/(name+'.TextGrid')).read_text(encoding='utf-16'))
        eligible=[r for i,r in enumerate(rows) if 2<=r['end']-r['start']<=15 and len(r['reference'].replace(' ',''))>=12 and '<' not in r['reference'] and not any('<LAUGH-' in near['reference'] for near in rows[max(0,i-1):i+2])]
        assert len(eligible)>=6
        chosen=[eligible[round(i*(len(eligible)-1)/5)] for i in range(6)]
        marker='친할 아' if name.endswith('f1') else '그러니깐 뭐 그러니깐'
        marked=next(r for r in eligible if marker in r['reference'])
        if marked not in chosen:chosen[-1]=marked
        for r in sorted(chosen,key=lambda r:r['start']):
            ident=name+'-'+str(round(r['start']*1000));wav=FOLDER/(ident+'.wav')
            subprocess.run([str(RUNTIME/'ffmpeg/bin/ffmpeg'),'-v','error','-nostdin','-y','-i',str(FOLDER/(name+'.flac')),'-ss',str(r['start']),'-t',str(r['end']-r['start']),'-ar','16000','-ac','1','-c:a','pcm_s16le',str(wav)],check=True)
            with wave.open(str(wav)) as audio:duration=audio.getnframes()/audio.getframerate()
            assert abs(duration-(r['end']-r['start']))<.001
            selected.append(r|{'id':ident,'group':'spontaneous12','path':str(wav),'sha256':hashlib.sha256(wav.read_bytes()).hexdigest(),'duration_seconds':duration,'speaker_id':'s01m16','license':'CC BY-NC 2.0','source_url':URL+'sound.tgz','label_tier':7,'filler_and_repetition_preserved':True})
    for c in selected:c['row_idx']=c['id'];c['reference_raw_transcription']=c['reference']
    assert len(selected)==39 and all(0<c['duration_seconds']<=30 and Path(c['path']).is_file() for c in selected)
    report={'ready':True,'selection_before_inference':'Fixed five FLEURS clean/gain0.1/SNR10 pairs; Deeply pair1+pair4 in three rooms; every fourth of fixed24 TED excerpts; Seoul leading two files, six evenly spaced qualifying utterances each with one fixed self-correction/filler example, chosen before inference','clips':selected,'datasets':manifest['datasets']|{'seoul':collected},'limitations':['Small diagnostic sample, not representative meeting benchmark','Gaussian noise differs from real environmental noise','Read room sentences and TED excerpts are not spontaneous dialogue','Seoul12 uses one male16 speaker in two recording parts; interviewer/private/unknown/tagged speech excluded, filler/repetition retained','No redistribution of NC/ND audio; evaluation only']}
    (FOLDER/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({'selected_cached_clips':len(selected),'seoul_files':[r['name'] for r in collected['files']]},ensure_ascii=False))
if __name__=='__main__':main()
