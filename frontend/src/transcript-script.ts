export type TranscriptSegment={id:string;chunk_id:string;recording_id:string;start_ms:number;end_ms:number;text:string;original_text:string;revision:number;final:number};
export type TranscriptAudio={id:string;open_url:string;seek_seconds:number;end_seconds:number};
type SourceAudio={open_url:string|null;seek_seconds:number|null;end_seconds:number|null};

export const transcriptStamp=(ms:number)=>{ms=Math.round(ms);return Math.floor(ms/60000)+':'+String(Math.floor(ms/1000)%60).padStart(2,'0')+'.'+String(ms%1000).padStart(3,'0');};

export function transcriptFocusIndex(event:Pick<KeyboardEvent,'key'|'shiftKey'|'altKey'|'ctrlKey'|'metaKey'>,index:number,count:number):number|null{
  if(!count||event.shiftKey||event.altKey||event.ctrlKey||event.metaKey)return null;
  if(event.key==='Home')return 0;
  if(event.key==='End')return count-1;
  if(['ArrowLeft','ArrowUp'].includes(event.key))return Math.max(0,index-1);
  if(['ArrowRight','ArrowDown'].includes(event.key))return Math.min(count-1,index+1);
  return null;
}

export function enforceTranscriptBounds(audio:Pick<HTMLMediaElement,'currentTime'|'paused'>,clip:TranscriptAudio,seeking=false):boolean{
  if(audio.currentTime<clip.seek_seconds||seeking&&audio.paused&&audio.currentTime>=clip.end_seconds)audio.currentTime=clip.seek_seconds;
  return audio.currentTime>=clip.end_seconds;
}

export function selectTranscriptRange(segments:TranscriptSegment[],start:number,end:number):TranscriptSegment[]{
  if(start>=end)return [];
  let offset=0;
  return segments.filter(s=>s.final).filter(s=>{
    const first=offset;offset+=s.text.length+1;
    return start<offset-1&&end>first;
  }).map(s=>({...s}));
}

export async function resolveTranscriptAudio(segments:TranscriptSegment[],resolve:(id:string)=>Promise<SourceAudio>):Promise<TranscriptAudio[]>{
  if(!segments.length||segments.some(s=>!s.final))throw new Error('확정 전사 구간을 선택하세요');
  return Promise.all(segments.map(async segment=>{
    const id=segment.id+':v'+segment.revision;
    const source=await resolve(id);
    if(!source.open_url||source.seek_seconds===null||source.end_seconds===null||!Number.isFinite(source.seek_seconds)||!Number.isFinite(source.end_seconds)||source.seek_seconds<0||source.end_seconds<=source.seek_seconds)throw new Error('선택 구간의 원음을 재생할 수 없습니다');
    return {id,open_url:source.open_url,seek_seconds:source.seek_seconds,end_seconds:source.end_seconds};
  }));
}
