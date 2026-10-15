def legacy_fixture(db, version):
    """Restore the pre-course table shapes before exercising an older migration."""
    assert 6 <= version <= 16
    assert not db.execute('SELECT 1 FROM jobs WHERE course_id IS NOT NULL').fetchone()
    assert not db.execute('SELECT 1 FROM artifacts WHERE course_id IS NOT NULL').fetchone()
    db.commit()
    db.execute('PRAGMA foreign_keys=OFF')
    db.execute('DROP VIEW IF EXISTS searchable_chunks')
    definitions = {
        'jobs': "id TEXT PRIMARY KEY,session_id TEXT " + ('NOT NULL ' if version < 13 else '') + "REFERENCES sessions(id),kind TEXT NOT NULL,status TEXT NOT NULL,request TEXT NOT NULL,result TEXT,error TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL",
        'artifacts': "id TEXT PRIMARY KEY,job_id TEXT NOT NULL UNIQUE REFERENCES jobs(id) ON DELETE CASCADE,session_id TEXT NOT NULL REFERENCES sessions(id),kind TEXT NOT NULL,body TEXT NOT NULL,evidence TEXT NOT NULL,metadata TEXT NOT NULL,edited INTEGER NOT NULL DEFAULT 0,confirmed INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL",
    }
    for table, definition in definitions.items():
        columns = ','.join(row['name'] for row in db.execute(f'PRAGMA table_info({table})') if row['name'] != 'course_id')
        db.execute(f'CREATE TABLE {table}_legacy({definition})')
        db.execute(f'INSERT INTO {table}_legacy({columns}) SELECT {columns} FROM {table}')
        db.execute(f'DROP TABLE {table}')
        db.execute(f'ALTER TABLE {table}_legacy RENAME TO {table}')
    for table in ('page_document_revisions', 'page_documents', 'asset_documents', 'course_assets'):
        db.execute(f'DROP TABLE {table}')
    db.execute('ALTER TABLE assets DROP COLUMN extraction_sha256')
    for introduced, table, names in (
        (16, 'recordings', ('transcription_mode', 'transcription_released', 'capture_id')),
        (15, 'transcripts', ('superseded_by',)),
        (14, 'notes', ('anchor_ms',)),
        (7, 'transcript_ranges', ('model',)),
    ):
        if version < introduced:
            for name in names:
                db.execute(f'ALTER TABLE {table} DROP COLUMN {name}')
    db.execute(f'PRAGMA user_version={version}')
    db.commit()
    db.execute('PRAGMA foreign_keys=ON')
    assert not db.execute('PRAGMA foreign_key_check').fetchall()
