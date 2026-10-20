CREATE TABLE IF NOT EXISTS courses (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('lecture','meeting')),
 course_id TEXT REFERENCES courses(id), title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
 lecture_no INTEGER, started_at TEXT NOT NULL, created_at TEXT NOT NULL, recording_status TEXT NOT NULL DEFAULT 'idle',
 deleted INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS assets (
 id TEXT PRIMARY KEY,filename TEXT NOT NULL,kind TEXT NOT NULL,sha256 TEXT NOT NULL,size INTEGER NOT NULL,
 status TEXT NOT NULL,extraction TEXT,error TEXT,created_at TEXT NOT NULL,external_path TEXT,mtime_ns INTEGER,version INTEGER NOT NULL DEFAULT 1,extraction_sha256 TEXT
);
CREATE TABLE IF NOT EXISTS session_assets (
 session_id TEXT NOT NULL REFERENCES sessions(id),asset_id TEXT NOT NULL REFERENCES assets(id),PRIMARY KEY(session_id,asset_id)
);
CREATE TABLE IF NOT EXISTS course_assets (
 course_id TEXT NOT NULL REFERENCES courses(id),asset_id TEXT NOT NULL REFERENCES assets(id),PRIMARY KEY(course_id,asset_id)
);
CREATE TABLE IF NOT EXISTS handwritten_assets(asset_id TEXT PRIMARY KEY REFERENCES assets(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS sources (id TEXT PRIMARY KEY,ref TEXT NOT NULL,text_snapshot TEXT NOT NULL,deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS asset_documents (
 asset_id TEXT NOT NULL REFERENCES assets(id),sha256 TEXT NOT NULL,metadata TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(asset_id,sha256)
);
CREATE TABLE IF NOT EXISTS page_documents (
 id TEXT PRIMARY KEY,course_id TEXT NOT NULL REFERENCES courses(id),asset_id TEXT NOT NULL REFERENCES assets(id),document_sha256 TEXT NOT NULL,
 page INTEGER NOT NULL CHECK(page>0),revision INTEGER NOT NULL DEFAULT 0,UNIQUE(course_id,asset_id,document_sha256,page),
 FOREIGN KEY(asset_id,document_sha256) REFERENCES asset_documents(asset_id,sha256)
);
CREATE TABLE IF NOT EXISTS page_document_revisions (
 document_id TEXT NOT NULL REFERENCES page_documents(id),revision INTEGER NOT NULL,text TEXT NOT NULL,ink TEXT NOT NULL,
 source_id TEXT NOT NULL REFERENCES sources(id),updated_at TEXT NOT NULL,PRIMARY KEY(document_id,revision)
);
CREATE TABLE IF NOT EXISTS notes (
 session_id TEXT NOT NULL REFERENCES sessions(id),version INTEGER NOT NULL,text TEXT NOT NULL,source_id TEXT NOT NULL REFERENCES sources(id) DEFERRABLE INITIALLY DEFERRED,created_at TEXT NOT NULL,anchor_ms INTEGER,PRIMARY KEY(session_id,version)
);
CREATE TABLE IF NOT EXISTS jobs (
 id TEXT PRIMARY KEY,session_id TEXT REFERENCES sessions(id),kind TEXT NOT NULL,status TEXT NOT NULL,
 request TEXT NOT NULL,result TEXT,error TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL
 ,course_id TEXT REFERENCES courses(id)
);
CREATE TABLE IF NOT EXISTS recordings (
 id TEXT PRIMARY KEY,session_id TEXT NOT NULL REFERENCES sessions(id),kind TEXT NOT NULL DEFAULT 'live',
 sample_rate INTEGER NOT NULL,status TEXT NOT NULL,started_at TEXT NOT NULL,ended_at TEXT,
 offset_ms INTEGER NOT NULL DEFAULT 0,stored_frames INTEGER NOT NULL DEFAULT 0,source_frames INTEGER NOT NULL DEFAULT 0,
 last_seq INTEGER NOT NULL DEFAULT -1,gaps TEXT NOT NULL DEFAULT '[]',stop_job_id TEXT,error TEXT,external_path TEXT,
 transcription_mode TEXT NOT NULL DEFAULT 'realtime' CHECK(transcription_mode IN ('realtime','after_stop')),
 transcription_released INTEGER NOT NULL DEFAULT 1 CHECK(transcription_released IN (0,1)),
 capture_id TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS pcm_packets (
 recording_id TEXT NOT NULL REFERENCES recordings(id),seq INTEGER NOT NULL,first_frame INTEGER NOT NULL,
 frame_count INTEGER NOT NULL,stored_start INTEGER NOT NULL,sha256 TEXT NOT NULL,received_at TEXT NOT NULL,
 PRIMARY KEY(recording_id,seq)
);




CREATE TABLE IF NOT EXISTS transcript_ranges (
 id TEXT PRIMARY KEY,recording_id TEXT NOT NULL REFERENCES recordings(id),start_frame INTEGER NOT NULL,end_frame INTEGER NOT NULL,
 stored_start INTEGER NOT NULL,stored_end INTEGER NOT NULL,final INTEGER NOT NULL,revision INTEGER NOT NULL,status TEXT NOT NULL,
 quiet INTEGER NOT NULL DEFAULT 0,error TEXT,prompt TEXT NOT NULL DEFAULT '',model TEXT
);
CREATE TABLE IF NOT EXISTS recording_scan (
 recording_id TEXT PRIMARY KEY REFERENCES recordings(id),state TEXT NOT NULL,remainder BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS transcripts (
 id TEXT PRIMARY KEY,session_id TEXT NOT NULL REFERENCES sessions(id),recording_id TEXT NOT NULL REFERENCES recordings(id),
 chunk_id TEXT NOT NULL REFERENCES transcript_ranges(id),start_ms INTEGER NOT NULL,end_ms INTEGER NOT NULL,
 original_text TEXT NOT NULL,text TEXT NOT NULL,revision INTEGER NOT NULL,final INTEGER NOT NULL,created_at TEXT NOT NULL,superseded_by TEXT REFERENCES transcripts(id)
);

CREATE TABLE IF NOT EXISTS audio_files (recording_id TEXT PRIMARY KEY REFERENCES recordings(id),filename TEXT NOT NULL,size INTEGER NOT NULL,mtime_ns INTEGER NOT NULL,sha256 TEXT NOT NULL,channels INTEGER NOT NULL,duration_ms INTEGER NOT NULL);



CREATE TABLE IF NOT EXISTS file_cleanup(kind TEXT NOT NULL,resource_id TEXT NOT NULL,error TEXT,PRIMARY KEY(kind,resource_id));
CREATE TABLE IF NOT EXISTS chunks(id TEXT PRIMARY KEY,source_id TEXT NOT NULL REFERENCES sources(id),ordinal INTEGER NOT NULL,text TEXT NOT NULL,search_text TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS chunks_source ON chunks(source_id,ordinal);
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_search USING fts5(chunk_id UNINDEXED,search_text,tokenize='trigram');
CREATE TRIGGER IF NOT EXISTS chunks_deleted AFTER DELETE ON chunks BEGIN DELETE FROM chunk_search WHERE chunk_id=old.id; END;
CREATE TABLE IF NOT EXISTS ink_recognitions (
 id TEXT PRIMARY KEY,document_id TEXT NOT NULL REFERENCES page_documents(id),course_id TEXT NOT NULL REFERENCES courses(id),asset_id TEXT NOT NULL REFERENCES assets(id),
 document_sha256 TEXT NOT NULL,page INTEGER NOT NULL,page_revision INTEGER NOT NULL,ink_hash TEXT NOT NULL,engine TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('candidate','approved','rejected','stale')),text TEXT NOT NULL,result TEXT NOT NULL,approved_text TEXT,source_id TEXT REFERENCES sources(id),created_at TEXT NOT NULL,approved_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ink_recognitions_current ON ink_recognitions(document_id,ink_hash,engine) WHERE status!='stale';
CREATE TABLE IF NOT EXISTS brain_work(key TEXT PRIMARY KEY,kind TEXT NOT NULL,source_id TEXT,state TEXT NOT NULL,request TEXT NOT NULL,result TEXT,error TEXT,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS concept_proposals(id TEXT PRIMARY KEY,source_id TEXT NOT NULL REFERENCES sources(id),scope_key TEXT NOT NULL,canonical TEXT NOT NULL,quote TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE VIEW IF NOT EXISTS searchable_chunks AS
 SELECT c.*,s.ref FROM chunks c JOIN sources s ON s.id=c.source_id
 WHERE s.deleted=0 AND (
 (json_extract(s.ref,'$.kind')='material' AND json_extract(s.ref,'$.document_sha256') IS NULL AND NOT EXISTS(SELECT 1 FROM handwritten_assets h WHERE h.asset_id=json_extract(s.ref,'$.asset_id')) AND EXISTS(SELECT 1 FROM assets a WHERE a.id=json_extract(s.ref,'$.asset_id') AND a.version=json_extract(s.ref,'$.version') AND a.extraction_sha256=a.sha256 AND a.status IN ('ready','partial')))
 OR (json_extract(s.ref,'$.kind')='page_note' AND EXISTS(SELECT 1 FROM page_documents d JOIN page_document_revisions r ON r.document_id=d.id AND r.revision=d.revision JOIN assets a ON a.id=d.asset_id WHERE r.source_id=s.id AND d.document_sha256=a.sha256))
 OR (json_extract(s.ref,'$.kind')='ink_note' AND EXISTS(SELECT 1 FROM ink_recognitions i JOIN assets a ON a.id=i.asset_id WHERE i.source_id=s.id AND i.status='approved' AND i.document_sha256=a.sha256))
 OR (json_extract(s.ref,'$.kind')='note' AND EXISTS(SELECT 1 FROM notes n WHERE n.source_id=s.id AND n.version=(SELECT max(version) FROM notes WHERE session_id=n.session_id)))
 OR (json_extract(s.ref,'$.kind')='transcript' AND EXISTS(SELECT 1 FROM transcripts t WHERE s.id=t.id||':v'||t.revision AND t.final=1 AND t.superseded_by IS NULL))
 );
CREATE TABLE IF NOT EXISTS terms(id TEXT PRIMARY KEY,scope_key TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS term_versions(term_id TEXT NOT NULL REFERENCES terms(id) ON DELETE CASCADE,revision INTEGER NOT NULL,canonical TEXT NOT NULL,aliases TEXT NOT NULL,explanation TEXT NOT NULL,evidence TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(term_id,revision));
CREATE TABLE IF NOT EXISTS embedding_sets(id TEXT PRIMARY KEY,model TEXT NOT NULL,digest TEXT NOT NULL,dim INTEGER,format TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS embeddings(index_id TEXT NOT NULL REFERENCES embedding_sets(id) ON DELETE CASCADE,chunk_id TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,part_no INTEGER NOT NULL,vector BLOB NOT NULL,PRIMARY KEY(index_id,chunk_id,part_no));
CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY,job_id TEXT NOT NULL UNIQUE REFERENCES jobs(id) ON DELETE CASCADE,session_id TEXT REFERENCES sessions(id),kind TEXT NOT NULL,body TEXT NOT NULL,evidence TEXT NOT NULL,metadata TEXT NOT NULL,edited INTEGER NOT NULL DEFAULT 0,confirmed INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,course_id TEXT REFERENCES courses(id),CHECK((session_id IS NULL)!=(course_id IS NULL)));
CREATE TABLE IF NOT EXISTS ai_attempts(id TEXT PRIMARY KEY,job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,provider TEXT NOT NULL,model TEXT NOT NULL,status TEXT NOT NULL,error TEXT,usage TEXT,elapsed_ms INTEGER,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS web_sources(source_id TEXT PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,title TEXT NOT NULL,retrieved_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS artifact_parts(job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,part_no INTEGER NOT NULL,body TEXT NOT NULL,metadata TEXT NOT NULL,PRIMARY KEY(job_id,part_no));
CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY,quiz_id TEXT NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,question_id TEXT NOT NULL,submitted_answer TEXT NOT NULL,grade TEXT,explanation TEXT NOT NULL,evidence_ids TEXT NOT NULL,metadata TEXT NOT NULL,status TEXT NOT NULL,error TEXT,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS attempt_revisions(attempt_id TEXT NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,revision INTEGER NOT NULL,grade TEXT NOT NULL,explanation TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(attempt_id,revision));
CREATE TABLE IF NOT EXISTS participants(id TEXT PRIMARY KEY,session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,name TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,UNIQUE(session_id,name));
CREATE TABLE IF NOT EXISTS artifact_revisions(artifact_id TEXT NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,revision INTEGER NOT NULL,body TEXT NOT NULL,confirmed INTEGER NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(artifact_id,revision));
CREATE TABLE IF NOT EXISTS question_card_preferences(session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,card_id TEXT NOT NULL,state TEXT NOT NULL,PRIMARY KEY(session_id,card_id));
PRAGMA user_version=19;
