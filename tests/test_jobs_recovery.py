import time
import threading
from studio.storage import Store
from studio.service import Service
from studio.fixtures import make_fixture
from studio.jobs import Jobs

def wait_job(jobs,jid):
    deadline=time.monotonic()+10
    while jid in jobs.stops and time.monotonic()<deadline:time.sleep(.02)
    assert jid not in jobs.stops

def test_retry_processes_failed_items_only(tmp_path):
    s=Store(tmp_path/'db');good=make_fixture(tmp_path/'good.hwpx');service=Service(s)
    jid=service.jobs.start('import',[str(good),str(tmp_path/'missing.hwpx')]);wait_job(service.jobs,jid)
    assert s.rows("SELECT count(*) AS n FROM job_items WHERE job_id=? AND state='failed'",(jid,))[0]['n']==1
    retry=service.command('retry',{'id':jid});wait_job(service.jobs,retry)
    assert s.rows('SELECT total FROM jobs WHERE id=?',(retry,))[0]['total']==1
    assert len(s.questions())==2
    service.jobs.close()

def test_cancellation_resumes_without_committing_partial_import(tmp_path,monkeypatch):
    import studio.jobs as module
    original=module.import_document;started=threading.Event();release=threading.Event()
    def controlled(store,path,progress,cancel):
        started.set();release.wait(3)
        if cancel():raise InterruptedError('취소됨')
        return original(store,path,progress,cancel)
    monkeypatch.setattr(module,'import_document',controlled)
    s=Store(tmp_path/'db');source=make_fixture(tmp_path/'q.hwpx');jobs=Jobs(s)
    jid=jobs.start('import',[str(source)]);assert started.wait(3);jobs.cancel(jid);release.set();wait_job(jobs,jid)
    assert not s.questions()
    jobs.resume(jid);wait_job(jobs,jid);assert len(s.questions())==2
    jobs.close()
