"""Versioned local storage. Each operation owns a short SQLite transaction."""
from .pdf_lock import PDF_LOCK
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from contextlib import contextmanager, closing
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def uid():
    return uuid.uuid4().hex


def data_home():
    return Path(os.environ.get("MATHBANK_DATA") or
                Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share")) / "MathBankDesktop")


class Store:
    def __init__(self, root=None):
        self.root = Path(root) if root else data_home()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "sources").mkdir(exist_ok=True)
        self.path = self.root / "mathbank.sqlite3"
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError("지원하지 않는 DB 버전입니다. 현재 데이터를 보존했습니다.")
            db.executescript('''
                CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    hash TEXT UNIQUE NOT NULL, path TEXT NOT NULL, pages INTEGER NOT NULL,
                    course TEXT NOT NULL DEFAULT '', created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS questions(id TEXT PRIMARY KEY, document_id TEXT NOT NULL
                    REFERENCES documents(id), version INTEGER NOT NULL DEFAULT 1,
                    regions TEXT NOT NULL, number TEXT NOT NULL DEFAULT '', content TEXT NOT NULL,
                    stages TEXT NOT NULL, user_modified INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '', updated TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS questions_document ON questions(document_id);
                CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY, question_id TEXT,
                    version INTEGER, content TEXT, stages TEXT, created TEXT);
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, kind TEXT, target TEXT,
                    version INTEGER, status TEXT, attempt INTEGER DEFAULT 0, method TEXT DEFAULT '',
                    error TEXT DEFAULT '', updated TEXT);
                CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status);
                CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY, kind TEXT, body TEXT, updated TEXT);
                CREATE INDEX IF NOT EXISTS records_kind ON records(kind);
                CREATE TABLE IF NOT EXISTS trash(kind TEXT, target TEXT, created TEXT,
                    PRIMARY KEY(kind,target));
                PRAGMA user_version=1;
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def documents(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM documents WHERE id NOT IN (SELECT target FROM trash WHERE kind='document') ORDER BY created DESC")]

    def document(self, identifier):
        with self.connect() as db:
            row = db.execute("SELECT * FROM documents WHERE id=?", (identifier,)).fetchone()
            if row is None:
                raise ValueError("자료를 찾을 수 없습니다.")
            return dict(row)

    def add_document(self, path, course=""):
        import pymupdf
        path = Path(path)
        payload = path.read_bytes()
        sha = digest(payload)
        with self.connect() as db:
            old = db.execute("SELECT id FROM documents WHERE hash=?", (sha,)).fetchone()
        if old:
            self.restore_trash("document", old[0])
            return old[0], False
        with PDF_LOCK, pymupdf.open(stream=payload, filetype="pdf") as pdf:
            if pdf.needs_pass:
                raise ValueError("암호화 PDF입니다. 암호를 해제한 사본을 등록하세요.")
            if not pdf.page_count:
                raise ValueError("페이지가 없는 PDF입니다.")
            pages = pdf.page_count
        relative = f"sources/{sha}.pdf"
        destination = self.root / relative
        destination.write_bytes(payload)
        identifier = uid()
        with self.connect() as db:
            db.execute("INSERT INTO documents VALUES(?,?,?,?,?,?,?)",
                       (identifier, path.name, sha, relative, pages, course, now()))
        return identifier, True

    def add_question(self, document_id, regions, number=""):
        from .validation import initial_stages
        identifier = uid()
        with self.connect() as db:
            # Re-running segmentation does not duplicate an identical source region.
            region_json = json.dumps(regions, sort_keys=True)
            old = db.execute("SELECT id FROM questions WHERE document_id=? AND regions=?",
                             (document_id, region_json)).fetchone()
            if old:
                return old[0]
            db.execute("INSERT INTO questions VALUES(?,?,1,?,?,?,?,0,'',?)",
                       (identifier, document_id, region_json, number, '{}',
                        json.dumps(initial_stages()), now()))
        return identifier

    @staticmethod
    def decode(row):
        result = dict(row)
        for key in ("regions", "content", "stages"):
            result[key] = json.loads(result[key])
        return result

    def question(self, identifier):
        with self.connect() as db:
            row = db.execute("SELECT * FROM questions WHERE id=?", (identifier,)).fetchone()
            if row is None:
                raise ValueError("문항을 찾을 수 없습니다.")
            return self.decode(row)

    def questions(self, page=0, search="", document_id=None, exceptions=False):
        where, args = ["id NOT IN (SELECT target FROM trash WHERE kind='question')",
                       "document_id NOT IN (SELECT target FROM trash WHERE kind='document')"], []
        if search:
            where.append("(content LIKE ? OR number LIKE ?)")
            args += [f"%{search}%", f"%{search}%"]
        if document_id:
            where.append("document_id=?")
            args.append(document_id)
        if exceptions:
            where.append("error<>''")
        clause = " AND ".join(where)
        with self.connect() as db:
            total = db.execute(f"SELECT count(*) FROM questions WHERE {clause}", args).fetchone()[0]
            rows = db.execute(f"SELECT * FROM questions WHERE {clause} ORDER BY rowid LIMIT 50 OFFSET ?",
                              args + [max(0, page) * 50]).fetchall()
        return [self.decode(r) for r in rows], total

    def update_question(self, identifier, version, content, stages, error="", manual=False):
        with self.connect() as db:
            old = db.execute("SELECT * FROM questions WHERE id=?", (identifier,)).fetchone()
            if old is None or old["version"] != version or (old["user_modified"] and not manual):
                return False
            db.execute("INSERT INTO history(question_id,version,content,stages,created) VALUES(?,?,?,?,?)",
                       (identifier, version, old["content"], old["stages"], now()))
            db.execute("UPDATE questions SET content=?,stages=?,error=?,version=?,user_modified=?,updated=? WHERE id=?",
                       (json.dumps(content, ensure_ascii=False), json.dumps(stages), error,
                        version + int(manual), int(manual or old["user_modified"]), now(), identifier))
        return True

    def update_regions(self, identifier, version, regions):
        from .validation import initial_stages
        with self.connect() as db:
            result = db.execute("UPDATE questions SET regions=?,version=version+1,stages=?,error=?,updated=? "
                                "WHERE id=? AND version=?", (json.dumps(regions, sort_keys=True),
                                json.dumps(initial_stages()), "영역 변경: 자동 재검사 필요", now(), identifier, version))
            return result.rowcount == 1

    def enqueue(self, kind, target, version=0):
        with self.connect() as db:
            old = db.execute("SELECT id FROM jobs WHERE kind=? AND target=? AND version=? "
                             "AND status IN ('queued','running')", (kind, target, version)).fetchone()
            if old:
                return old[0]
            identifier = uid()
            db.execute("INSERT INTO jobs(id,kind,target,version,status,updated) VALUES(?,?,?,?,?,?)",
                       (identifier, kind, target, version, "queued", now()))
            return identifier

    def next_job(self):
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY CASE kind WHEN 'question' THEN 0 ELSE 1 END, rowid LIMIT 1").fetchone()
            return dict(row) if row else None

    def claim_job(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY "
                             "CASE kind WHEN 'question' THEN 0 ELSE 1 END,rowid LIMIT 1").fetchone()
            if row:
                db.execute("UPDATE jobs SET status='running',updated=? WHERE id=?", (now(), row['id']))
                return dict(row)
        return None

    def move_to_trash(self, kind, identifiers):
        if kind not in ('document', 'question', 'exam', 'student', 'assignment'):
            raise ValueError("지원하지 않는 삭제 대상")
        with self.connect() as db:
            for identifier in identifiers:
                db.execute("INSERT OR IGNORE INTO trash VALUES(?,?,?)", (kind, identifier, now()))
                if kind == 'document':
                    db.execute("UPDATE jobs SET status='cancelled',error='자료 삭제' WHERE status IN ('queued','paused','running') "
                               "AND ((kind='page' AND target LIKE ?) OR (kind='question' AND target IN "
                               "(SELECT id FROM questions WHERE document_id=?)))", (identifier + ':%', identifier))
                elif kind == 'question':
                    db.execute("UPDATE jobs SET status='cancelled',error='문항 삭제' WHERE kind='question' AND target=? "
                               "AND status IN ('queued','paused','running')", (identifier,))

    def trashed(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM trash ORDER BY created DESC")]

    def restore_trash(self, kind, identifier):
        with self.connect() as db:
            db.execute("DELETE FROM trash WHERE kind=? AND target=?", (kind, identifier))

    def is_trashed(self, question):
        with self.connect() as db:
            return db.execute("SELECT 1 FROM trash WHERE (kind='question' AND target=?) "
                              "OR (kind='document' AND target=?)", (question['id'],question['document_id'])).fetchone() is not None

    def document_trashed(self, identifier):
        with self.connect() as db:
            return db.execute("SELECT 1 FROM trash WHERE kind='document' AND target=?", (identifier,)).fetchone() is not None

    def completed_page(self, target):
        with self.connect() as db:
            return db.execute("SELECT 1 FROM jobs WHERE kind='page' AND target=? AND status IN ('done','skipped')", (target,)).fetchone() is not None

    def cancel_jobs(self, identifiers=None):
        with self.connect() as db:
            if identifiers is None:
                db.execute("UPDATE jobs SET status='cancelled',error='사용자 취소' WHERE status IN ('queued','paused')")
            else:
                db.executemany("UPDATE jobs SET status='cancelled',error='사용자 취소' WHERE id=? "
                               "AND status IN ('queued','paused')", [(i,) for i in identifiers])

    def jobs(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM jobs ORDER BY rowid DESC LIMIT 300")]

    def job_status(self, identifier, status, error="", attempt=0, method=""):
        with self.connect() as db:
            db.execute("UPDATE jobs SET status=?,error=?,attempt=?,method=?,updated=? WHERE id=?",
                       (status, error, attempt, method, now(), identifier))

    def put_record(self, kind, body, identifier=None):
        identifier = identifier or uid()
        with self.connect() as db:
            db.execute("INSERT INTO records VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                       "body=excluded.body,updated=excluded.updated", (identifier, kind,
                       json.dumps(body, ensure_ascii=False), now()))
        return identifier

    def records(self, kind):
        with self.connect() as db:
            return [dict(id=r["id"], **json.loads(r["body"])) for r in
                    db.execute("SELECT * FROM records WHERE kind=? AND id NOT IN (SELECT target FROM trash WHERE kind=?) ORDER BY rowid DESC", (kind, kind))]

    def record(self, identifier):
        with self.connect() as db:
            row = db.execute("SELECT * FROM records WHERE id=?", (identifier,)).fetchone()
            if row is None:
                raise ValueError("저장 기록을 찾을 수 없습니다.")
            return dict(id=row["id"], **json.loads(row["body"]))

    def backup(self, destination):
        destination = Path(destination)
        with tempfile.TemporaryDirectory() as temp:
            snapshot = Path(temp) / "mathbank.sqlite3"
            with self.connect() as source:
                target = sqlite3.connect(snapshot)
                try:
                    source.backup(target)
                finally:
                    target.close()
            files = {"mathbank.sqlite3": snapshot}
            with closing(sqlite3.connect(snapshot)) as db:
                for (relative,) in db.execute("SELECT path FROM documents"):
                    files[relative] = self.root / relative
            manifest = {name: digest(path.read_bytes()) for name, path in files.items()}
            temp_zip = Path(temp) / "backup.zip"
            with zipfile.ZipFile(temp_zip, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps({"version": 1, "files": manifest}))
                for name, path in files.items():
                    archive.write(path, name)
            shutil.copyfile(temp_zip, destination)

    @staticmethod
    def restore(archive_path, destination):
        """Restore to a NEW directory only; never overwrite a live database."""
        destination = Path(destination)
        if destination.exists():
            raise ValueError("복원 대상은 새 폴더여야 합니다. 현재 운영 데이터는 변경하지 않습니다.")
        with tempfile.TemporaryDirectory(dir=destination.parent) as temp:
            staging = Path(temp)
            with zipfile.ZipFile(archive_path) as archive:
                infos = archive.infolist()
                if sum(i.file_size for i in infos) > 2_000_000_000:
                    raise ValueError("백업 크기 제한을 초과했습니다.")
                names = [i.filename for i in infos]
                if len(names) != len(set(names)):
                    raise ValueError("중복 백업 항목입니다.")
                manifest = json.loads(archive.read("manifest.json"))
                if manifest.get("version") != 1 or set(names) != set(manifest["files"]) | {"manifest.json"}:
                    raise ValueError("백업 버전 또는 파일 목록 오류입니다.")
                for name, sha in manifest["files"].items():
                    if name != "mathbank.sqlite3" and not __import__('re').fullmatch(r"sources/[0-9a-f]{64}\.pdf", name):
                        raise ValueError("허용되지 않은 백업 경로입니다.")
                    payload = archive.read(name)
                    if digest(payload) != sha:
                        raise ValueError("백업 파일 해시가 일치하지 않습니다.")
                    path = staging / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(payload)
            with closing(sqlite3.connect(staging / "mathbank.sqlite3")) as db:
                if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or db.execute("PRAGMA user_version").fetchone()[0] != 1:
                    raise ValueError("DB 무결성/버전 오류입니다.")
                if db.execute("PRAGMA foreign_key_check").fetchall():
                    raise ValueError("DB 참조 무결성 오류입니다.")
                for path, sha in db.execute("SELECT path,hash FROM documents"):
                    if path not in manifest["files"] or manifest["files"][path] != sha:
                        raise ValueError("연결된 원본이 없거나 변조되었습니다.")
            shutil.copytree(staging, destination)
        return Store(destination)
