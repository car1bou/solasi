export type Course = {id: string; title: string; description: string};
export type Session = {id: string; kind: 'lecture' | 'meeting'; title: string; course_id: string | null; lecture_no: number | null; started_at: string; recording_status: string};

export type PageContent = {ref:SourceRef;page:number;width:number;height:number;text:string;items:{text:string;bbox:number[];confidence:number|null}[]};
export type Asset = {handwritten?:boolean;id:string;filename:string;kind:string;version:number;status:string;source_status:string;error:string|null;extraction:{total_pages:number;images:{id:string;ref:SourceRef}[];pages:PageContent[];page_errors:{page:number|null;message:string}[]}|null};

export type SourceRef = {bbox?:number[]|null;coord_system?:string|null;source_width?:number|null;source_height?:number|null;id:string;course_id?:string|null;document_id?:string|null;document_sha256?:string|null;kind:'material'|'transcript'|'note'|'page_note'|'ink_note'|'web'|'ai_interpretation';version:number;session_id?:string|null;asset_id?:string|null;page?:number|null;start_ms?:number|null;end_ms?:number|null;url?:string|null};
export type Evidence = {ref:SourceRef;text:string;label:string;retrieved_at:string|null};
export type SearchResult = {evidence:Evidence[];mode:'keyword'|'hybrid';warning:string|null};
export type Term = {id:string;canonical:string;aliases:string[];explanation:string;evidence:SourceRef[];revision:number};
export type Job<T> = {id:string;kind:string;status:string;error:string|null;result:(T&{paused_reason?:string})|null};

export type DocumentPage = {page:number;width:number;height:number;rotation:number;ref:SourceRef};
export type DocumentMetadata = {asset_id:string;sha256:string;total_pages:number;pages:DocumentPage[]};
export type InkPoint = {x:number;y:number;pressure:number;tilt_x?:number;tilt_y?:number};
type InkBase = {id:string;color:string;width:number;opacity:number;input:'mouse'|'pen'|'touch';points:InkPoint[]};
export type InkText = InkBase&{tool:'text';text:string};
export type InkStroke = (InkBase&{tool:'pen'|'highlighter'})|InkText;
export type PageDocument = {id:string|null;course_id:string;asset_id:string;document_sha256:string;page:number;revision:number;text:string;ink:InkStroke[];source_id:string|null;updated_at:string|null};
export type CourseScope = {course_id:string;mode:'course';asset_id?:string;page?:number;document_sha256?:string};

export type SessionScope = {session_id:string;mode:'current'|'selected'|'course';lecture_ids?:string[];asset_id?:string;page?:number;document_sha256?:string};
