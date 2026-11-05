"""Independent Windows desktop shell around the new local application."""
from __future__ import annotations
import argparse
import json
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PySide6.QtCore import QObject,Signal,Slot,QUrl,Qt,QTimer
from PySide6.QtGui import QDesktopServices,QIcon
from PySide6.QtWidgets import QApplication,QMainWindow,QFileDialog,QMessageBox,QDialog,QVBoxLayout
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineSettings
from PySide6.QtWebChannel import QWebChannel
from .storage import Store
from .service import Service
from .exports import export_packet,PDF
from .assessment import report
from .model import identity
from . import VERSION

class Page(QWebEnginePage):
    def acceptNavigationRequest(self,url,type_,main):
        if url.isLocalFile() and Path(url.toLocalFile()).resolve()==(Path(__file__).parent/'ui/index.html').resolve():return True
        return url.scheme() in ('qrc','data','about')
    def javaScriptConsoleMessage(self,level,message,line,source):
        if os.environ.get('STUDIO_DEBUG'):print('JS',line,message,flush=True)

class Bridge(QObject):
    reply=Signal(str);changed=Signal();artifact=Signal(str);finished=Signal(str,str,str)
    def __init__(self,window,store):
        super().__init__(window);self.window=window;self.store=store;self.service=Service(store,self.changed.emit);self.executor=ThreadPoolExecutor(max_workers=2,thread_name_prefix='studio-ui')
        self.finished.connect(self.deliver)
    @Slot(str,str,str)
    def call(self,request_id,action,payload):
        try:
            args=json.loads(payload)
            if action=='import':
                paths,_=QFileDialog.getOpenFileNames(self.window,'문제 자료 가져오기',str(Path.home()),'한글 문서 (*.hwpx *.hwp)')
                result=self.service.jobs.start('import',paths) if paths else None
                self.deliver(request_id,json.dumps(result),'');return
            if action in ('export','report_export','class_export','backup','restore'):
                if action=='restore':
                    archive,_=QFileDialog.getOpenFileName(self.window,'백업 파일 선택','','MathBank 백업 (*.zip)')
                    if not archive:self.deliver(request_id,'null','');return
                    directory=QFileDialog.getExistingDirectory(self.window,'복원할 빈 폴더 선택')
                    if not directory:self.deliver(request_id,'null','');return
                    args.update(archive=archive,directory=directory)
                else:
                    suffix='zip' if action=='backup' else args.get('format','pdf')
                    suggested='MathBank-backup.zip' if action=='backup' else ('학습성적표.' if action in ('report_export','class_export') else '시험출력.')+suffix
                    target,_=QFileDialog.getSaveFileName(self.window,'저장할 위치',str(Path.home()/'Downloads'/suggested),suffix.upper()+' (*.'+suffix+')')
                    if not target:self.deliver(request_id,'null','');return
                    args['target']=target
            if action=='open_folder':QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.root)));self.deliver(request_id,'true','');return
            if action=='open_workspace':
                directory=args.get('directory') or QFileDialog.getExistingDirectory(self.window,'열 자료실 폴더 선택')
                if not directory:self.deliver(request_id,'null','');return
                if not (Path(directory)/'studio.sqlite').is_file():raise ValueError('MathBank Studio 자료실 DB가 없는 폴더입니다. 복원한 자료실 폴더를 선택해 주세요.')
                other=Window(Store(directory));self.window.other_windows.append(other);other.show();other.raise_();other.activateWindow()
                self.deliver(request_id,'true','');return
            self.executor.submit(self.work,request_id,action,args)
        except Exception as exc:self.deliver(request_id,'null',str(exc))
    def work(self,request_id,action,args):
        try:
            if action=='export':
                path=export_packet(self.store,args['exam_id'],args.get('kind','questions'),args.get('student_id'),args.get('format','pdf'));shutil.copy2(path,args['target']);result=args['target']
            elif action=='report_export':
                directory=self.store.root/'outputs'/identity();path=PDF(self.store,directory).report(report(self.store,args['id']));shutil.copy2(path,args['target']);result=args['target']
            elif action=='class_export':
                from pypdf import PdfWriter
                attempts=[a for a in self.store.attempts() if a['exam_id']==args['exam_id'] and (not args.get('class_name') or a['class_name']==args['class_name'])]
                if not attempts:raise ValueError('합칠 응시 기록이 없습니다.')
                writer=PdfWriter()
                for a in attempts:writer.append(str(PDF(self.store,self.store.root/'outputs'/identity()).report(report(self.store,a['id']))))
                with open(args['target'],'wb') as f:writer.write(f)
                writer.close();result=args['target']
            elif action=='backup':result=self.store.backup(args['target'])
            elif action=='restore':result=Store.restore(args['archive'],args['directory'])
            else:result=self.service.command(action,args)
            self.finished.emit(request_id,json.dumps(result,ensure_ascii=False),'')
            if action not in ('snapshot','document_review','source_view','boundary_suggestions','report','exam_detail','connect'):self.changed.emit()
        except Exception as exc:self.finished.emit(request_id,'null',str(exc)[:1500])
    @Slot(str,str,str)
    def deliver(self,request_id,value,error):self.reply.emit(json.dumps({'id':request_id,'value':json.loads(value),'error':error},ensure_ascii=False))

class Window(QMainWindow):
    def __init__(self,store):
        super().__init__();self.setWindowTitle('MathBank Studio '+VERSION);self.resize(1480,960);self.setMinimumSize(1080,760)
        self.other_windows=[]
        self.setWindowIcon(QIcon(str(Path(__file__).parent/'ui/assets/studio.ico')))
        self.view=QWebEngineView(self);self.page=Page(self.view);self.view.setPage(self.page);self.setCentralWidget(self.view)
        self.page.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls,False)
        self.page.settings().setAttribute(QWebEngineSettings.JavascriptCanOpenWindows,False)
        self.channel=QWebChannel(self.page);self.bridge=Bridge(self,store);self.channel.registerObject('studio',self.bridge);self.page.setWebChannel(self.channel)
        self.view.setUrl(QUrl.fromLocalFile(str(Path(__file__).parent/'ui/index.html')))
    def closeEvent(self,event):
        self.bridge.service.jobs.close();self.bridge.executor.shutdown(wait=False,cancel_futures=True);event.accept()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workspace');parser.add_argument('--self-test',action='store_true');parser.add_argument('--capture');parser.add_argument('--capture-page',default='library');args=parser.parse_args()
    if args.self_test:
        from .selftest import run
        return run()
    app=QApplication(sys.argv);app.setApplicationName('MathBank Studio');app.setApplicationVersion(VERSION);app.setOrganizationName('MathBankStudio')
    base=Path(args.workspace) if args.workspace else Path(os.environ.get('LOCALAPPDATA',Path.home()/'.local/share'))/'MathBankStudio'
    try:window=Window(Store(base))
    except Exception as exc:
        QMessageBox.critical(None,'자료실을 열지 못했습니다',str(exc)+'\n\n자료실 파일은 그대로 보존되어 있습니다. 최신 프로그램으로 다시 실행해 주세요.');return 1
    window.show()
    if args.capture:
        def capture():
            window.page.runJavaScript('navigate('+json.dumps(args.capture_page)+')')
            QTimer.singleShot(1500,lambda:(window.grab().save(args.capture),app.quit()))
        QTimer.singleShot(3500,capture)
    return app.exec()
