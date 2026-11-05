"""Persisted item queues, cooperative cancellation and idempotent resume."""
from __future__ import annotations
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from .model import identity,stamp,encode
from .importers import import_document
from .reasoning import check_question
from .variants import generate
from . import ai

class Jobs:
    def __init__(self,store,notify=lambda:None):
        self.store=store;self.notify=notify;self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='studio');self.stops={}
    def start(self,kind,targets,settings=None):
        if not targets:raise ValueError('작업할 문항 또는 파일을 선택해 주세요.')
        for row in self.store.rows("SELECT kind,targets FROM jobs WHERE state IN ('queued','running')"):
            if row['kind']==kind and row['targets']==encode(targets):raise ValueError('같은 작업이 이미 진행 중입니다.')
        jid=identity()
        with self.store.transaction() as db:
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?)',(jid,kind,encode(targets),encode(settings or {}),'queued',0,len(targets),0,'대기 중',stamp(),stamp()))
        self.resume(jid);return jid
    def cancel(self,jid):
        if jid in self.stops:self.stops[jid].set()
    def resume(self,jid):
        row=self.store.rows('SELECT * FROM jobs WHERE id=?',(jid,))[0]
        if jid in self.stops:raise ValueError('작업이 이미 실행 중입니다.')
        event=threading.Event();self.stops[jid]=event
        with self.store.transaction() as db:db.execute("UPDATE jobs SET state='queued' WHERE id=?",(jid,))
        self.executor.submit(self._run,jid,event)
    def _update(self,jid,**values):
        values['updated']=stamp()
        with self.store.transaction() as db:
            db.execute('UPDATE jobs SET '+','.join(k+'=?' for k in values)+' WHERE id=?',(*values.values(),jid))
        self.notify()
    def _run(self,jid,event):
        row=self.store.rows('SELECT * FROM jobs WHERE id=?',(jid,))[0];targets=json.loads(row['targets']);settings=json.loads(row['settings']);completed=row['completed'];failed=row['failed'];errors=[]
        try:
            self._update(jid,state='running',detail='작업 시작')
            for index in range(completed,len(targets)):
                if event.is_set():raise InterruptedError('취소됨 · 처리한 항목을 유지하며 재개할 수 있습니다.')
                target=targets[index]
                try:
                    if row['kind']=='import':
                        import_document(self.store,target,lambda count,total,detail:self._update(jid,detail=f'{index+1}/{len(targets)} 파일 · {count}/{total}문항 · {detail}'),event.is_set)
                    elif row['kind']=='explain':
                        q=self.store.question(target)
                        if not q:raise ValueError('문항이 없습니다.')
                        self._update(jid,detail=f'{index+1}/{len(targets)} · 별도 풀이와 필수 검사')
                        proposal=None
                        if settings.get('provider','local')!='local':proposal=ai.explain(q,settings,event.is_set)
                        answer=check_question(q,proposal)
                        self.store.save_answer(q['id'],q['revision'],q['fingerprint'],answer)
                        if answer['verification']!='passed':failed+=1
                    elif row['kind']=='variant':
                        self._update(jid,detail=f"{index+1}/{len(targets)} · {'숫자' if target['kind']=='numeric' else '사고'}변형 생성·검증")
                        generate(self.store,target['id'],target['kind'],settings,jid+':'+str(index),event.is_set)
                    else:raise ValueError('지원하지 않는 작업입니다.')
                except InterruptedError:raise
                except Exception as exc:
                    failed+=1;errors.append({'index':index,'target':target,'reason':str(exc)[:500]})
                completed=index+1
                self._update(jid,completed=completed,failed=failed,detail=(errors[-1]['reason'] if errors else f'{completed}/{len(targets)} 처리 완료'))
            self._update(jid,state='completed',detail=f'{completed}건 처리 · 보류/실패 {failed}건'+(' · '+errors[-1]['reason'] if errors else ''))
        except InterruptedError as exc:self._update(jid,state='cancelled',detail=str(exc))
        except Exception as exc:self._update(jid,state='failed',detail=str(exc)[:500])
        finally:self.stops.pop(jid,None);self.notify()
    def close(self):
        for event in list(self.stops.values()):event.set()
        self.executor.shutdown(wait=False,cancel_futures=True)
