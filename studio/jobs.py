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
            db.executemany('INSERT INTO job_items VALUES(?,?,?,?,?)',[(jid,i,encode(target),'pending','') for i,target in enumerate(targets)])
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
        row=self.store.rows('SELECT * FROM jobs WHERE id=?',(jid,))[0];targets=json.loads(row['targets']);settings=json.loads(row['settings']);completed=row['completed'];failed=row['failed'];errors=[];saved_held=0;messages=[]
        try:
            self._update(jid,state='running',detail='작업 시작')
            for index in range(completed,len(targets)):
                if event.is_set():raise InterruptedError('취소됨 · 처리한 항목을 유지하며 재개할 수 있습니다.')
                target=targets[index]
                item_error=''
                try:
                    if row['kind']=='import':
                        imported=import_document(self.store,target,lambda count,total,detail:self._update(jid,detail=f'{index+1}/{len(targets)} 파일 · {count}/{total}문항 · {detail}'),event.is_set)
                        with self.store.transaction() as db:db.execute('INSERT OR IGNORE INTO job_documents VALUES(?,?)',(jid,imported['document_id']))
                        saved_held+=imported.get('held',0)
                        if imported.get('boundary_review'):messages.append('원문 저장 완료 · 문항검색에서 문항 나누기로 경계를 확인해 주세요.')
                        elif imported.get('duplicate'):messages.append(imported['message'])
                    elif row['kind']=='reparse':
                        doc=next(d for d in self.store.documents() if d['id']==target)
                        self._update(jid,detail='관리 원본에서 문항 경계를 다시 분석합니다')
                        result=import_document(self.store,self.store.path(doc['path']),lambda count,total,detail:self._update(jid,detail=f'{count}/{total}문항 · {detail}'),event.is_set,replace_document=target)
                        saved_held+=result.get('held',0)
                        with self.store.transaction() as db:db.execute('INSERT OR IGNORE INTO job_documents VALUES(?,?)',(jid,target))
                        messages.append('재분리 결과를 저장했습니다. 이전 문항과 시험 기록은 보존했습니다.')
                    elif row['kind']=='proofread':
                        from .proofreading import run
                        self._update(jid,detail=f'{index+1}/{len(targets)} · 원문·문장 검수')
                        reviewed=run(self.store,target,settings,event.is_set)
                        if reviewed.get('ai_state')=='failed':failed+=1;item_error=reviewed['ai_error']
                    elif row['kind']=='explain':
                        q=self.store.question(target)
                        if not q:raise ValueError('문항이 없습니다.')
                        if q['source'].get('boundary_review'):raise ValueError('문항 나누기에서 시작 문단을 선택한 뒤 정답·해설을 생성해 주세요.')
                        self._update(jid,detail=f'{index+1}/{len(targets)} · 별도 풀이와 필수 검사')
                        proposal=None
                        if settings.get('provider','local')!='local':proposal=ai.explain(q,settings,event.is_set)
                        answer=check_question(q,proposal)
                        self.store.save_answer(q['id'],q['revision'],q['fingerprint'],answer)
                        if answer['verification']!='passed':
                            failed+=1;item_error=answer['reason']
                    elif row['kind']=='variant':
                        self._update(jid,detail=f"{index+1}/{len(targets)} · {'숫자' if target['kind']=='numeric' else '사고'}변형 생성·검증")
                        child=generate(self.store,target['id'],target['kind'],settings,jid+':'+str(index),event.is_set)
                        q=self.store.question(child)
                        if not q['available']:failed+=1;item_error=q['answer']['reason']
                    else:raise ValueError('지원하지 않는 작업입니다.')
                except InterruptedError:raise
                except Exception as exc:
                    failed+=1;item_error='작업 실패: '+str(exc)[:500];errors.append({'index':index,'target':target,'reason':item_error})
                with self.store.transaction() as db:
                    db.execute('INSERT INTO job_items VALUES(?,?,?,?,?) ON CONFLICT(job_id,position) DO UPDATE SET state=excluded.state,error=excluded.error',(jid,index,encode(target),'failed' if item_error else 'completed',item_error))
                completed=index+1
                self._update(jid,completed=completed,failed=failed,detail=(item_error or f'{completed}/{len(targets)} 처리 완료'))
            self._update(jid,state='completed',detail=f'{completed}개 자료 처리 · 저장 보류 {saved_held}문항 · 실패 {failed}건'+(' · '+errors[-1]['reason'] if errors else ' · '+messages[-1] if messages else '') if row['kind'] in ('import','reparse') else f'{completed}건 처리 · 보류/실패 {failed}건'+(' · '+errors[-1]['reason'] if errors else ''))
        except InterruptedError as exc:self._update(jid,state='cancelled',detail=str(exc))
        except Exception as exc:self._update(jid,state='failed',detail=str(exc)[:500])
        finally:self.stops.pop(jid,None);self.notify()
    def close(self):
        for event in list(self.stops.values()):event.set()
        self.executor.shutdown(wait=False,cancel_futures=True)
