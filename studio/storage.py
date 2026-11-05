"""A new, local-only SQLite workspace. Immutable revisions back every exam."""
from __future__ import annotations
import json
import shutil
import sqlite3
import threading
import zipfile
from contextlib import contextmanager
from pathlib import Path
from .model import identity, stamp, encode, checksum, body_fingerprint, available, plain_text

SCHEMA = '''
CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, hash TEXT UNIQUE NOT NULL, name TEXT NOT NULL, path TEXT NOT NULL, rendition TEXT, metadata TEXT NOT NULL, report TEXT NOT NULL, created TEXT NOT NULL, trashed INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS questions(id TEXT PRIMARY KEY, document_id TEXT REFERENCES documents(id), revision INTEGER NOT NULL, favorite INTEGER NOT NULL DEFAULT 0, trashed INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS versions(question_id TEXT NOT NULL REFERENCES questions(id), revision INTEGER NOT NULL, fingerprint TEXT NOT NULL, body TEXT NOT NULL, source TEXT NOT NULL, classification TEXT NOT NULL, difficulty INTEGER NOT NULL CHECK(difficulty BETWEEN 1 AND 10), input_state TEXT NOT NULL, issues TEXT NOT NULL, original_answer TEXT, original_steps TEXT NOT NULL, created TEXT NOT NULL, PRIMARY KEY(question_id, revision));
CREATE TABLE IF NOT EXISTS answers(question_id TEXT NOT NULL, revision INTEGER NOT NULL, value TEXT NOT NULL, PRIMARY KEY(question_id,revision), FOREIGN KEY(question_id,revision) REFERENCES versions(question_id,revision));
CREATE TABLE IF NOT EXISTS validations(id TEXT PRIMARY KEY, question_id TEXT NOT NULL, revision INTEGER NOT NULL, value TEXT NOT NULL, created TEXT NOT NULL, FOREIGN KEY(question_id,revision) REFERENCES versions(question_id,revision));
CREATE TABLE IF NOT EXISTS lineage(child_id TEXT PRIMARY KEY REFERENCES questions(id), parent_id TEXT NOT NULL REFERENCES questions(id), parent_revision INTEGER NOT NULL, kind TEXT NOT NULL, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS classes(id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS students(id TEXT PRIMARY KEY, name TEXT NOT NULL, school TEXT NOT NULL, grade TEXT NOT NULL, class_id TEXT REFERENCES classes(id), archived INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS exams(id TEXT PRIMARY KEY, family_id TEXT NOT NULL, revision INTEGER NOT NULL, status TEXT NOT NULL, title TEXT NOT NULL, exam_date TEXT NOT NULL, settings TEXT NOT NULL, created TEXT NOT NULL, UNIQUE(family_id,revision));
CREATE TABLE IF NOT EXISTS exam_items(id TEXT PRIMARY KEY, exam_id TEXT NOT NULL REFERENCES exams(id), position INTEGER NOT NULL, question_id TEXT NOT NULL REFERENCES questions(id), revision INTEGER NOT NULL, points REAL NOT NULL CHECK(points>0), snapshot TEXT NOT NULL, UNIQUE(exam_id,position));
CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY, exam_id TEXT NOT NULL REFERENCES exams(id), student_id TEXT NOT NULL REFERENCES students(id), round INTEGER NOT NULL CHECK(round>0), state TEXT NOT NULL, created TEXT NOT NULL, UNIQUE(exam_id,student_id,round));
CREATE TABLE IF NOT EXISTS results(attempt_id TEXT NOT NULL REFERENCES attempts(id), item_id TEXT NOT NULL REFERENCES exam_items(id), submitted TEXT NOT NULL, score REAL, status TEXT NOT NULL, PRIMARY KEY(attempt_id,item_id));
CREATE TABLE IF NOT EXISTS exports(id TEXT PRIMARY KEY, exam_id TEXT REFERENCES exams(id), student_id TEXT REFERENCES students(id), kind TEXT NOT NULL, path TEXT NOT NULL, hash TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, kind TEXT NOT NULL, targets TEXT NOT NULL, settings TEXT NOT NULL, state TEXT NOT NULL, completed INTEGER NOT NULL, total INTEGER NOT NULL, failed INTEGER NOT NULL, detail TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS job_items(job_id TEXT NOT NULL REFERENCES jobs(id), position INTEGER NOT NULL, target TEXT NOT NULL, state TEXT NOT NULL, error TEXT NOT NULL, PRIMARY KEY(job_id,position));
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS text_reviews(id TEXT PRIMARY KEY,question_id TEXT NOT NULL,revision INTEGER NOT NULL,value TEXT NOT NULL,created TEXT NOT NULL,FOREIGN KEY(question_id,revision) REFERENCES versions(question_id,revision));
CREATE TABLE IF NOT EXISTS job_documents(job_id TEXT NOT NULL REFERENCES jobs(id),document_id TEXT NOT NULL REFERENCES documents(id),PRIMARY KEY(job_id,document_id));
CREATE INDEX IF NOT EXISTS ix_question_document ON questions(document_id);
PRAGMA user_version=2;
'''

class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        for folder in ('originals','assets','outputs','renditions'):
            (self.root/folder).mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.root/'studio.sqlite', check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        if version > 2:
            raise ValueError('더 최신 버전에서 만든 자료실입니다. 프로그램을 업데이트해 주세요.')
        if version==1:
            backups=self.root/'backups';backups.mkdir(exist_ok=True)
            target=sqlite3.connect(backups/('before-schema-2-'+identity()+'.sqlite'))
            try:self.db.backup(target)
            finally:target.close()
        self.db.executescript(SCHEMA)
        self.db.execute("UPDATE jobs SET state='interrupted',detail='앱 종료로 중단됨 · 재개할 수 있습니다' WHERE state IN ('running','queued')")
        if self.setting('taxonomy') is None:
            self.set_setting('taxonomy', {'courses':['공통수학1','공통수학2','대수','미적분','확률과 통계','중학수학'], 'units':['다항식','방정식과 부등식','복소수','함수','경우의 수','기하','미분류']})

    @contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                yield self.db
                self.db.execute('COMMIT')
            except BaseException:
                self.db.execute('ROLLBACK')
                raise

    def rows(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.db.execute(sql,args).fetchall()]

    def setting(self, key, default=None):
        r=self.rows('SELECT value FROM settings WHERE key=?',(key,))
        return json.loads(r[0]['value']) if r else default

    def set_setting(self,key,value):
        with self.transaction() as db:
            db.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,encode(value)))

    def blob(self, data, folder, suffix):
        digest=checksum(data)
        relative=f'{folder}/{digest}{suffix.lower()}'
        path=self.root/relative
        if not path.exists():
            path.write_bytes(data)
        return relative

    def path(self, relative):
        path=(self.root/relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError('자료실 외부 경로는 사용할 수 없습니다.')
        return path

    def insert_question(self, db, q, document_id=None, lineage=None):
        qid=identity()
        db.execute('INSERT INTO questions(id,document_id,revision,created) VALUES(?,?,1,?)',(qid,document_id,stamp()))
        self._version(db,qid,1,q)
        if lineage:
            db.execute('INSERT INTO lineage VALUES(?,?,?,?,?)',(qid,lineage['parent_id'],lineage['parent_revision'],lineage['kind'],encode(lineage)))
        return qid

    def _version(self,db,qid,rev,q):
        db.execute('INSERT INTO versions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(
            qid,rev,body_fingerprint(q['body']),encode(q['body']),encode(q.get('source',{})),
            encode(q.get('classification',{'course':'미상','unit':'미분류','type':'미분류','certainty':'suggested'})),
            int(q.get('difficulty',5)),q.get('input_state','complete'),encode(q.get('issues',[])),
            q.get('original_answer'),encode(q.get('original_steps',[])),stamp()))
        if q.get('answer'):
            db.execute('INSERT INTO answers VALUES(?,?,?)',(qid,rev,encode(q['answer'])))

    def revise(self,qid,changes):
        old=self.question(qid)
        if not old: raise ValueError('문항을 찾을 수 없습니다.')
        q={**old,**changes}
        q.pop('answer',None)
        rev=old['revision']+1
        with self.transaction() as db:
            self._version(db,qid,rev,q)
            db.execute('UPDATE questions SET revision=? WHERE id=?',(rev,qid))
        return rev

    def questions(self,include_trash=False):
        sql='''SELECT q.*,v.fingerprint,v.body,v.source,v.classification,v.difficulty,v.input_state,v.issues,v.original_answer,v.original_steps,a.value AS answer,l.value AS lineage,d.name AS document_name
            FROM questions q JOIN versions v ON q.id=v.question_id AND q.revision=v.revision
            LEFT JOIN answers a ON q.id=a.question_id AND q.revision=a.revision
            LEFT JOIN lineage l ON l.child_id=q.id LEFT JOIN documents d ON d.id=q.document_id'''
        if not include_trash: sql+=' WHERE q.trashed=0 AND (d.trashed=0 OR d.id IS NULL)'
        return [self._decode(q) for q in self.rows(sql+' ORDER BY q.created,q.rowid')]

    def _decode(self,q):
        for key in ('body','source','classification','issues','original_steps','answer','lineage'):
            if q.get(key) is not None: q[key]=json.loads(q[key])
        from .proofreading import inspect,latest
        q['text_review']=latest(self,q['id'],q['revision']) or inspect(q['body'])
        q['available']=available(q)
        q['search_text']=plain_text(q['body']['blocks'])+' '+plain_text([{'kind':'paragraph','blocks':c} for c in q['body'].get('choices',[])])
        return q

    def question(self,qid):
        return next((q for q in self.questions(True) if q['id']==qid),None)

    def save_answer(self,qid,revision,fingerprint,answer):
        with self.transaction() as db:
            row=db.execute('SELECT revision FROM questions WHERE id=?',(qid,)).fetchone()
            if not row or row[0]!=revision:
                raise ValueError('풀이 중 문항이 수정되어 결과를 적용하지 않았습니다. 최신 버전을 다시 검증해 주세요.')
            row=db.execute('SELECT fingerprint FROM versions WHERE question_id=? AND revision=?',(qid,revision)).fetchone()
            if row[0]!=fingerprint: raise ValueError('문항 버전이 일치하지 않습니다.')
            answer.setdefault('proof',{})['body_fingerprint']=fingerprint
            db.execute('INSERT INTO answers VALUES(?,?,?) ON CONFLICT(question_id,revision) DO UPDATE SET value=excluded.value',(qid,revision,encode(answer)))
            db.execute('INSERT INTO validations VALUES(?,?,?,?,?)',(identity(),qid,revision,encode(answer),stamp()))

    def trash(self,kind,item_id,value=True):
        table={'question':'questions','document':'documents'}[kind]
        with self.transaction() as db:
            db.execute(f'UPDATE {table} SET trashed=? WHERE id=?',(int(value),item_id))

    def documents(self):
        result=self.rows('SELECT d.*, (SELECT count(*) FROM questions q WHERE q.document_id=d.id AND q.trashed=0) AS count FROM documents d ORDER BY created DESC')
        for d in result:
            d['metadata']=json.loads(d['metadata']); d['report']=json.loads(d['report'])
        return result

    def add_student(self,data):
        name=str(data.get('name','')).strip()
        if not name: raise ValueError('학생 이름을 입력해 주세요.')
        cid=None
        with self.transaction() as db:
            class_name=str(data.get('class_name','')).strip()
            if class_name:
                row=db.execute('SELECT id FROM classes WHERE name=?',(class_name,)).fetchone()
                cid=row[0] if row else identity()
                if not row: db.execute('INSERT INTO classes VALUES(?,?)',(cid,class_name))
            sid=data.get('id') or identity()
            db.execute('INSERT INTO students(id,name,school,grade,class_id) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,school=excluded.school,grade=excluded.grade,class_id=excluded.class_id',(sid,name,str(data.get('school','')),str(data.get('grade','')),cid))
        return sid

    def students(self):
        return self.rows('SELECT s.*,c.name AS class_name FROM students s LEFT JOIN classes c ON s.class_id=c.id WHERE s.archived=0 ORDER BY s.name')

    def create_exam(self, data):
        ids=data.get('question_ids',[])
        if not ids or len(set(ids))!=len(ids): raise ValueError('시험 문항을 선택해 주세요. 같은 문항은 중복할 수 없습니다.')
        questions=[self.question(qid) for qid in ids]
        if any(not q or q['trashed'] for q in questions): raise ValueError('삭제된 문항이 포함되어 있습니다.')
        confirm=data.get('confirm',False)
        if confirm and any(not q['available'] for q in questions): raise ValueError('확정 시험에는 자동 검사 통과 문항만 포함할 수 있습니다. 보류 문항은 초안으로 확인해 주세요.')
        eid=identity(); family=data.get('family_id') or eid
        rev=self.rows('SELECT MAX(revision) AS n FROM exams WHERE family_id=?',(family,))[0]['n'] or 0
        base,remainder=divmod(10000,len(ids))
        points=data.get('points') or [(base+(i<remainder))/100 for i in range(len(ids))]
        if len(points)!=len(ids) or any(not isinstance(p,(int,float)) or not 0<p<=10000 for p in points): raise ValueError('문항별 배점을 확인해 주세요.')
        with self.transaction() as db:
            db.execute('INSERT INTO exams VALUES(?,?,?,?,?,?,?,?)',(eid,family,rev+1,'confirmed' if confirm else 'draft',str(data.get('title','새 시험')),str(data.get('date','')),encode(data.get('settings',{})),stamp()))
            for i,(q,p) in enumerate(zip(questions,points),1):
                db.execute('INSERT INTO exam_items VALUES(?,?,?,?,?,?,?)',(identity(),eid,i,q['id'],q['revision'],p,encode(q)))
        return eid

    def exams(self):
        return self.rows('SELECT e.*,(SELECT count(*) FROM exam_items i WHERE i.exam_id=e.id) AS count,(SELECT sum(points) FROM exam_items i WHERE i.exam_id=e.id) AS maximum FROM exams e ORDER BY e.created DESC')

    def exam(self,eid):
        rows=self.rows('SELECT * FROM exams WHERE id=?',(eid,))
        if not rows: raise ValueError('시험을 찾을 수 없습니다.')
        exam=rows[0];exam['settings']=json.loads(exam['settings'])
        exam['items']=self.rows('SELECT * FROM exam_items WHERE exam_id=? ORDER BY position',(eid,))
        for item in exam['items']: item['snapshot']=json.loads(item['snapshot'])
        return exam

    def assign(self,eid,student_ids,absent=False):
        exam=self.exam(eid)
        if exam['status']!='confirmed': raise ValueError('확정 시험을 학생에게 배정할 수 있습니다.')
        result=[]
        with self.transaction() as db:
            for sid in student_ids:
                round_=db.execute('SELECT coalesce(max(round),0)+1 FROM attempts WHERE exam_id=? AND student_id=?',(eid,sid)).fetchone()[0]
                aid=identity();result.append(aid)
                db.execute('INSERT INTO attempts VALUES(?,?,?,?,?,?)',(aid,eid,sid,round_,'absent' if absent else 'assigned',stamp()))
        return result

    def attempts(self):
        return self.rows('SELECT a.*,s.name,s.school,s.grade,c.name AS class_name,e.title,e.exam_date FROM attempts a JOIN students s ON a.student_id=s.id LEFT JOIN classes c ON s.class_id=c.id JOIN exams e ON a.exam_id=e.id ORDER BY a.created DESC')

    def backup(self,target):
        """Hold mutations while snapshotting DB and its content-addressed files."""
        target=Path(target)
        temp=self.root/'snapshot.sqlite'
        with self.lock:
            dest=sqlite3.connect(temp)
            self.db.backup(dest);dest.close()
            files=[p for folder in ('originals','assets','renditions','outputs') for p in (self.root/folder).rglob('*') if p.is_file()]
            manifest={p.relative_to(self.root).as_posix():checksum(p.read_bytes()) for p in files}
            manifest['studio.sqlite']=checksum(temp.read_bytes())
            with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
                z.write(temp,'studio.sqlite')
                for p in files: z.write(p,p.relative_to(self.root).as_posix())
                z.writestr('manifest.json',encode({'version':1,'created':stamp(),'files':manifest}))
            temp.unlink()
        return str(target)

    @staticmethod
    def restore(archive,directory):
        dest=Path(directory).resolve()
        if dest.exists() and any(dest.iterdir()): raise ValueError('복원할 빈 폴더를 선택해 주세요. 현재 자료실은 덮어쓰지 않습니다.')
        dest.mkdir(parents=True,exist_ok=True)
        try:
            with zipfile.ZipFile(archive) as z:
                if sum(i.file_size for i in z.infolist())>2_000_000_000: raise ValueError('백업 파일 크기 제한을 초과했습니다.')
                names=z.namelist()
                if len(set(names))!=len(names): raise ValueError('중복 경로가 있는 백업입니다.')
                manifest=json.loads(z.read('manifest.json'))
                for name,digest in manifest['files'].items():
                    path=(dest/name).resolve()
                    if not path.is_relative_to(dest) or '\\' in name or name.startswith('/'): raise ValueError('잘못된 백업 경로입니다.')
                    data=z.read(name)
                    if checksum(data)!=digest: raise ValueError('백업 파일의 해시가 일치하지 않습니다: '+name)
                    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
            db=sqlite3.connect(dest/'studio.sqlite')
            try:
                if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchall(): raise ValueError('백업 DB 무결성 검사에 실패했습니다.')
            finally: db.close()
        except BaseException:
            shutil.rmtree(dest)
            raise
        return str(dest)
