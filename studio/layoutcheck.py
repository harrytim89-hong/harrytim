"""Desktop acceptance at logical sizes used by Windows display scaling."""
from __future__ import annotations
import json


def verify_renderer_recovery(window):
    """Terminate only this test window's renderer, then use its native retry."""
    import os
    import signal
    import time
    from PySide6.QtCore import QEventLoop,QTimer
    pid=window.page.renderProcessPid()
    if not pid or pid==os.getpid():raise AssertionError('검사할 화면 프로세스가 없습니다.')
    loop=QEventLoop();state={'recovery':False,'ready':False};started=time.monotonic()
    os.kill(pid,signal.SIGTERM)
    def poll():
        if not state['recovery'] and window.stack.currentWidget()==window.recovery:
            state['recovery']=True;window.retry_button.click()
        elif state['recovery'] and window.ui_ready and window.page.renderProcessPid()!=pid:
            state['ready']=True;loop.quit()
        if time.monotonic()-started>25:loop.quit()
    timer=QTimer();timer.timeout.connect(poll);timer.start(100);QTimer.singleShot(27000,loop.quit)
    try:loop.exec()
    finally:timer.stop()
    if not state['ready']:raise AssertionError(('화면 프로세스 종료 후 복구 실패',state))
    return True


def verify(window):
    from PySide6.QtCore import QEventLoop,QTimer
    results=[]
    cases=[(1366,768,1,'bank'),(1280,720,1.5,'bank'),(1024,768,1.25,'modal'),(800,600,1,'drawer'),(640,480,1,'bank')]
    for width,height,zoom,mode in cases:
        window.resize(width,height);window.view.setZoomFactor(zoom)
        loop=QEventLoop();state={}
        script="""(()=>{
 filters={search:'',unit:'',state:'',difficulty:''};selected.clear();selected.add(data.questions.find(q=>!q.source.boundary_review).id);navigate('questions');
 const mode=MODE;const q=data.questions.find(q=>!q.source.boundary_review);
 if(mode==='modal')editClassification(q);else if(mode==='drawer')showDetail(q.id);
 const out=[];
 for(const e of document.querySelectorAll('.q-card,.unit-scope,.page-heading>.row,.selection-bar,.modal,#drawer:not(.hidden)')){
  const r=e.getBoundingClientRect();if(r.width&& (r.left< -1||r.right>innerWidth+1))out.push({element:e.className,left:r.left,right:r.right});
 }
 return {width:innerWidth,scroll:document.documentElement.scrollWidth,overflow:out,cards:document.querySelectorAll('.q-card').length};
})()""".replace('MODE',json.dumps(mode))
        def done(value):
            try:state['result']=json.loads(value) if isinstance(value,str) else value
            except ValueError:state['result']={'script_error':value}
            loop.quit()
        QTimer.singleShot(400,lambda:window.page.runJavaScript('JSON.stringify('+script+')',done));QTimer.singleShot(10000,loop.quit);loop.exec()
        result=state.get('result')
        if not result or 'script_error' in result or result['overflow'] or result['scroll']>result['width']+1 or result['cards']<1:
            raise AssertionError(('화면 배율·창 크기 검사 실패',width,height,zoom,mode,result))
        results.append(result)
    window.page.runJavaScript('closeDrawer();closeModal()');window.view.setZoomFactor(1)
    return results
