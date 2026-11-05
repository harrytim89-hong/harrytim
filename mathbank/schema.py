"""Additive v1 -> v2 migration; legacy PDF data is preserved."""


def migrate(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS source_info(
            document_id TEXT PRIMARY KEY REFERENCES documents(id), format TEXT NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}', import_result TEXT NOT NULL DEFAULT '{}',
            rule TEXT NOT NULL DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS assets(
            id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
            ref TEXT NOT NULL, kind TEXT NOT NULL, path TEXT NOT NULL, hash TEXT NOT NULL,
            UNIQUE(document_id,ref));
        CREATE TABLE IF NOT EXISTS lineage(
            question_id TEXT PRIMARY KEY REFERENCES questions(id),
            parent_id TEXT NOT NULL REFERENCES questions(id), parent_version INTEGER NOT NULL,
            kind TEXT NOT NULL, changes TEXT NOT NULL, settings TEXT NOT NULL, created TEXT NOT NULL,
            job_id TEXT UNIQUE);
        CREATE TABLE IF NOT EXISTS verification(
            id TEXT PRIMARY KEY, question_id TEXT NOT NULL REFERENCES questions(id),
            version INTEGER NOT NULL, method TEXT NOT NULL, state TEXT NOT NULL,
            evidence TEXT NOT NULL, created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS classes(id TEXT PRIMARY KEY,name TEXT NOT NULL UNIQUE);
        CREATE TABLE IF NOT EXISTS memberships(class_id TEXT REFERENCES classes(id),
            student_id TEXT REFERENCES records(id), PRIMARY KEY(class_id,student_id));
        CREATE TABLE IF NOT EXISTS attempts(
            id TEXT PRIMARY KEY, student_id TEXT NOT NULL REFERENCES records(id),
            exam_id TEXT NOT NULL REFERENCES records(id), round INTEGER NOT NULL,
            status TEXT NOT NULL, report_id TEXT REFERENCES records(id), created TEXT NOT NULL,
            UNIQUE(student_id,exam_id,round));
        CREATE TABLE IF NOT EXISTS results(
            attempt_id TEXT NOT NULL REFERENCES attempts(id), ordinal INTEGER NOT NULL,
            answer TEXT NOT NULL, score REAL, status TEXT NOT NULL,
            PRIMARY KEY(attempt_id,ordinal));
        CREATE TABLE IF NOT EXISTS distributions(
            id TEXT PRIMARY KEY, attempt_id TEXT REFERENCES attempts(id),
            exam_id TEXT REFERENCES records(id), kind TEXT NOT NULL, path TEXT NOT NULL,
            hash TEXT NOT NULL, created TEXT NOT NULL);
        PRAGMA user_version=2;
    ''')
