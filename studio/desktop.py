"""Independent Windows desktop shell around the new local application."""
from __future__ import annotations
import argparse
import json
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from .runtime import prepare_rendering
SOFTWARE_RENDERING=prepare_rendering()
from PySide6.QtCore import QObject,Signal,Slot,QUrl,Qt,QTimer
from PySide6.QtGui import QDesktopServices,QIcon
from PySide6.QtWidgets import QApplication,QMainWindow,QFileDialog,QMessageBox,QDialog,QVBoxLayout,QWidget,QStackedWidget,QLabel,QPushButton
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineSettings,QWebEngineProfile
from PySide6.QtWebChannel import QWebChannel
from .storage import Store
from .service import Service
from .exports import export_packet,export_question,export_questions_archive,PDF
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
            if action=='ui_ready':
                self.window.mark_ready();self.deliver(request_id,'true','');return
            if action=='import':
                paths,_=QFileDialog.getOpenFileNames(self.window,'문제 자료 가져오기',str(Path.home()),'한글 문서 (*.hwpx *.hwp)')
                result=self.service.jobs.start('import',paths) if paths else None
                self.deliver(request_id,json.dumps(result),'');return
            if action in ('export','question_export','questions_archive','report_export','class_export','backup','restore'):
                if action=='restore':
                    archive,_=QFileDialog.getOpenFileName(self.window,'백업 파일 선택','','MathBank 백업 (*.zip)')
                    if not archive:self.deliver(request_id,'null','');return
                    directory=QFileDialog.getExistingDirectory(self.window,'복원할 빈 폴더 선택')
                    if not directory:self.deliver(request_id,'null','');return
                    args.update(archive=archive,directory=directory)
                else:
                    suffix='zip' if action in ('backup','questions_archive') else args.get('format','pdf')
                    suggested='MathBank-backup.zip' if action=='backup' else ('문항별파일.' if action=='questions_archive' else '개별문항.' if action=='question_export' else '학습성적표.' if action in ('report_export','class_export') else '시험출력.')+suffix
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
            elif action=='question_export':
                path=export_question(self.store,args['id'],args.get('format','pdf'));shutil.copy2(path,args['target']);result=args['target']
            elif action=='questions_archive':
                path=export_questions_archive(self.store,args['ids'],args.get('format','hwpx'));shutil.copy2(path,args['target']);result=args['target']
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
        super().__init__();self.setWindowTitle('MathBank Studio '+VERSION);self.setMinimumSize(640,480)
        screen=QApplication.primaryScreen().availableGeometry()
        self.resize(min(1480,max(640,screen.width()-40)),min(960,max(480,screen.height()-60)))
        self.other_windows=[]
        self.setWindowIcon(QIcon(str(Path(__file__).parent/'ui/assets/studio.ico')))
        self.stack=QStackedWidget(self);self.setCentralWidget(self.stack)
        self.view=QWebEngineView(self);self.stack.addWidget(self.view)
        self.recovery=QWidget(self);layout=QVBoxLayout(self.recovery);layout.setContentsMargins(35,30,35,30)
        title=QLabel('MathBank Studio · 화면 복구');title.setStyleSheet('font-size:22px;font-weight:600;color:#263653');layout.addWidget(title)
        self.recovery_message=QLabel('프로그램 화면을 준비하고 있습니다. 원본·문항·학생·성적은 PC 자료실에 보존되어 있습니다.');self.recovery_message.setWordWrap(True);layout.addWidget(self.recovery_message)
        self.retry_button=QPushButton('화면 다시 열기');self.retry_button.clicked.connect(self.reload_view);layout.addWidget(self.retry_button)
        folder=QPushButton('내 자료실 폴더 열기');folder.clicked.connect(lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(store.root))));layout.addWidget(folder);layout.addStretch()
        self.recovery.setStyleSheet('QWidget{background:#f5f6fa;color:#3e506c;font-size:14px} QPushButton{background:white;border:1px solid #bfc8dc;border-radius:6px;padding:12px;text-align:left}');self.stack.addWidget(self.recovery)
        # Off-the-record profile avoids carrying stale GPU/cache state between releases.
        self.profile=QWebEngineProfile(self)
        self.ui_ready=False;self.startup_timer=QTimer(self);self.startup_timer.setSingleShot(True);self.startup_timer.timeout.connect(lambda:self.show_recovery('화면 연결 시간이 초과되었습니다. 화면 다시 열기를 눌러 주세요.'))
        self.bridge=Bridge(self,store)
        recovery_menu=self.menuBar().addMenu('화면 복구')
        recovery_menu.addAction('화면 다시 열기',self.reload_view)
        recovery_menu.addAction('복구 안내 열기',lambda:self.show_recovery('화면이 하얗거나 검게 보이면 화면 다시 열기를 눌러 주세요. 이 버전은 그래픽 카드 가속 없이 화면을 표시합니다.'))
        self.reload_view()
    def loaded(self,ok):
        if not ok:self.show_recovery('화면 파일을 읽지 못했습니다. ZIP 전체를 새 폴더에 압축 해제했는지 확인하고 화면 다시 열기를 눌러 주세요.')
    def mark_ready(self):
        self.ui_ready=True;self.startup_timer.stop();self.stack.setCurrentWidget(self.view)
    def show_recovery(self,message):
        self.ui_ready=False;self.startup_timer.stop();self.recovery_message.setText(message+'\n\n저장한 문항·원본·정답·학생·성적은 삭제하지 않습니다.');self.stack.setCurrentWidget(self.recovery)
    def reload_view(self):
        self.ui_ready=False;self.recovery_message.setText('화면을 다시 연결하고 있습니다. 잠시 기다려 주세요.');self.stack.setCurrentWidget(self.recovery);self.startup_timer.start(30000)
        old=getattr(self,'page',None)
        page=Page(self.profile,self.view);self.page=page
        page.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls,False)
        page.settings().setAttribute(QWebEngineSettings.JavascriptCanOpenWindows,False)
        page.renderProcessTerminated.connect(lambda status,code,p=page:self.show_recovery('화면 표시 프로세스가 종료되었습니다. 원본과 DB는 보존되어 있습니다. 화면 다시 열기를 눌러 주세요.') if p is self.page else None)
        page.loadFinished.connect(lambda ok,p=page:self.loaded(ok) if p is self.page else None)
        self.channel=QWebChannel(page);self.channel.registerObject('studio',self.bridge);page.setWebChannel(self.channel)
        self.view.setPage(page)
        if old:old.setWebChannel(None);old.deleteLater()
        url=QUrl.fromLocalFile(str(Path(__file__).parent/'ui/index.html'))
        self.view.setUrl(url)
    def closeEvent(self,event):
        self.bridge.service.jobs.close();self.bridge.executor.shutdown(wait=False,cancel_futures=True);event.accept()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workspace');parser.add_argument('--self-test',action='store_true');parser.add_argument('--software-rendering',action='store_true');parser.add_argument('--capture');parser.add_argument('--capture-page',default='questions');args=parser.parse_args()
    if SOFTWARE_RENDERING:QApplication.setAttribute(Qt.AA_UseSoftwareOpenGL)
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
