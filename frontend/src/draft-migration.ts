import {api} from './api.ts';

export async function transferDraft(value:unknown,kind:'write'|'import',journalKey?:string){
  const bytes=new TextEncoder().encode(JSON.stringify(value));
  const upload=await api<{id:string;chunk_size:number}>('/native/drafts/uploads',{method:'POST',body:JSON.stringify({size:bytes.length,kind,...(journalKey?{journal_key:journalKey}:{})})});
  try{
    if(!Number.isInteger(upload.chunk_size)||upload.chunk_size<1||upload.chunk_size>256*1024)throw new Error('초안 전송 크기가 올바르지 않습니다.');
    for(let offset=0;offset<bytes.length;offset+=upload.chunk_size){
      const part=bytes.subarray(offset,offset+upload.chunk_size);
      let binary='';for(let start=0;start<part.length;start+=8192)binary+=String.fromCharCode(...part.subarray(start,start+8192));
      const result=await api<{received:number}>('/native/drafts/uploads/'+upload.id,{method:'PUT',body:JSON.stringify({offset,data:btoa(binary)})});
      if(result.received!==offset+part.length)throw new Error('초안 전송 확인 길이가 다릅니다.');
    }
    return await api<{sha256:string;count:number;conflicts?:number}>('/native/drafts/uploads/'+upload.id+'/commit',{method:'POST'});
  }catch(error){await api('/native/drafts/uploads/'+upload.id,{method:'DELETE'}).catch(()=>{});throw error;}
}

export async function readNativeDrafts<T extends {key:string}>(key:string):Promise<T[]>{
  const rows:T[]=[];let after='';
  for(;;){
    const page=await api<T[]>('/native/drafts/read?key='+encodeURIComponent(key)+'&after='+encodeURIComponent(after));
    if(!page.length)return rows;
    if(page.length!==1||page[0].key<=after||!(page[0].key===key||page[0].key.startsWith(key+'::')))throw new Error('초안 조회 응답이 올바르지 않습니다.');
    rows.push(page[0]);after=page[0].key;
  }
}

export type DraftExport={version:1;vault_id:string;origin:string;theme:'system'|'light'|'dark';drafts:unknown[];unsaved_inputs:unknown[]};
