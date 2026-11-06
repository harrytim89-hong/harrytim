"""Application commands shared by desktop and integration checks."""
from __future__ import annotations
import base64
import copy
import json
from .model import paragraphs
from .formula import equation,mathml
from .jobs import Jobs
from . import assessment,ai
from . import VERSION

class Service:
    def __init__(self,store,notify=lambda:None):self.store=store;self.jobs=Jobs(store,notify)
    def question_for_ui(self,q):
        q=copy.deepcopy(q)
        blocks=[q['body']['blocks'],*q['body'].get('choices',[])]
        if q.get('answer'):
            blocks.extend(s['blocks'] for s in q['answer'].get('steps',[]))
            if q['body']['answer_format']=='short' and q['answer'].get('exact_value'):
                try:q['answer']['final_mathml']=equation(q['answer']['exact_value'],'latex')['mathml']
                except ValueError:pass
        if q['source'].get('original_note'):blocks.append(q['source']['original_note']['blocks'])
        edit_index=0;text_index=0
        for group in blocks:
            for b in paragraphs(group):
                if b['kind'] in ('math','text'):
                    b['edit_key']=str(edit_index);edit_index+=1
                if b['kind']=='text':b['text_key']=str(text_index);text_index+=1
                if b['kind']=='math':b['mathml']=mathml(b['ast'])
                if b['kind']=='image':
                    data=self.store.path(b['path']).read_bytes();suffix=b['path'].rsplit('.',1)[-1]
                    b['data_url']='data:image/'+('jpeg' if suffix=='jpg' else suffix)+';base64,'+base64.b64encode(data).decode()
        return q
    def snapshot(self):
        jobs=self.store.rows('SELECT * FROM jobs ORDER BY created DESC LIMIT 30')
        for j in jobs:j['document_ids']=[r['document_id'] for r in self.store.rows('SELECT document_id FROM job_documents WHERE job_id=?',(j['id'],))]
        return {'questions':[self.question_for_ui(q) for q in self.store.questions()], 'trash':[self.question_for_ui(q) for q in self.store.questions(True) if q['trashed']], 'documents':self.store.documents(),'students':self.store.students(),'exams':self.store.exams(),'attempts':self.store.attempts(),'jobs':jobs,'settings':{'ai':self.store.setting('ai',{'provider':'codex','model':''}),'taxonomy':self.store.setting('taxonomy'),'root':str(self.store.root)},'version':VERSION}
    def command(self,action,args):
        s=self.store
        if action=='snapshot':return self.snapshot()
        if action=='document_review':
            from .review import summary
            return summary(s,args['id'])
        if action=='source_view':
            from .review import source
            result=source(s,s.question(args['id']))
            groups=[result['blocks']]+([result['original_note']['blocks']] if result.get('original_note') else [])
            for b in paragraphs([{'kind':'paragraph','blocks':group} for group in groups]):
                if b['kind']=='math':b['mathml']=mathml(b['ast'])
                elif b['kind']=='image':b['data_url']='data:image/'+b['path'].rsplit('.',1)[-1]+';base64,'+base64.b64encode(s.path(b['path']).read_bytes()).decode()
            return result
        if action=='repair_document':return self.jobs.start('reparse',[args['id']])
        if action=='undo_reparse':
            from .review import undo_reparse
            return undo_reparse(s,args['id'])
        if action=='boundary_suggestions':
            from .boundaries import suggest_blocks
            q=s.question(args['id']);return suggest_blocks(q['body']['blocks'])
        if action=='proofread':return self.jobs.start('proofread',args['ids'],args.get('settings',{'provider':'local'}))
        if action=='classify':return self.jobs.start('classify',args['ids'])
        if action=='edit_classification':
            from .classification import edit
            return edit(s,args['id'],args['revision'],args['values'])
        if action=='correct_text':
            from .proofreading import apply
            return apply(s,args['id'],args['revision'],args['finding_id'],args.get('replacement'))
        if action=='dismiss_text':
            from .proofreading import dismiss
            return dismiss(s,args['id'],args['revision'],args['finding_id'])
        if action=='resolve_source_note':
            q=s.question(args['id'])
            if not q or q['revision']!=args['revision']:raise ValueError('문항이 변경되었습니다. 원문을 다시 확인해 주세요.')
            note={**q['source'].get('original_note',{}),'state':'reference_confirmed'}
            return s.revise(q['id'],{'source':{**q['source'],'answer_ambiguity':False,'original_note':note}})
        if action=='split_boundaries':
            from .splitting import split_saved
            return split_saved(s,args['id'],args['revision'],args['starts'])
        if action=='explain':return self.jobs.start('explain',args['ids'],args.get('settings',{'provider':'local'}))
        if action=='variants':
            targets=[]
            for qid in args['ids']:
                for kind,key in [('numeric','numeric'),('thinking','thinking')]:
                    count=int(args.get(key,1))
                    if not 0<=count<=20:raise ValueError('변형 개수는 0~20개로 지정해 주세요.')
                    targets.extend({'id':qid,'kind':kind} for _ in range(count))
            return self.jobs.start('variant',targets,args.get('settings',{'provider':'local'}))
        if action=='cancel':self.jobs.cancel(args['id']);return True
        if action=='resume':self.jobs.resume(args['id']);return True
        if action=='retry':
            job=s.rows('SELECT * FROM jobs WHERE id=?',(args['id'],))[0]
            failed=s.rows("SELECT target FROM job_items WHERE job_id=? AND state='failed' ORDER BY position",(args['id'],))
            if not failed:raise ValueError('재시도할 실패 항목이 없습니다. 중단한 작업은 재개를 선택해 주세요.')
            return self.jobs.start(job['kind'],[json.loads(i['target']) for i in failed],json.loads(job['settings']))
        if action=='student':return s.add_student(args)
        if action=='exam':return s.create_exam(args)
        if action=='exam_detail':
            exam=s.exam(args['id'])
            for i in exam['items']:i['snapshot']=self.question_for_ui(i['snapshot'])
            return exam
        if action=='assign':return s.assign(args['exam_id'],args['student_ids'],args.get('absent',False))
        if action=='grade':return assessment.grade(s,args['id'],args.get('answers',{}),args.get('manual'),args.get('absent',False))
        if action=='report':return assessment.report(s,args['id'])
        if action=='remediation':return assessment.remediation(s,args['id'],args.get('kind','original'))
        if action=='trash':s.trash(args['kind'],args['id'],args.get('value',True));return True
        if action=='favorite':
            with s.transaction() as db:db.execute('UPDATE questions SET favorite=? WHERE id=?',(int(args['value']),args['id']))
            return True
        if action=='settings':
            if args['key'] not in ('ai','taxonomy'):raise ValueError('지원하지 않는 설정입니다.')
            s.set_setting(args['key'],args['value']);return True
        if action=='connect':return ai.connect(args)
        if action=='revise':
            q=s.question(args['id']);changes={}
            if 'difficulty' in args:
                v=int(args['difficulty'])
                if not 1<=v<=10:raise ValueError('난이도는 1~10입니다.')
                if v!=q['difficulty']:changes['difficulty']=v
            if 'classification' in args and any(q['classification'].get(k)!=v for k,v in args['classification'].items()):changes['classification']={**q['classification'],**args['classification'],'certainty':'user_confirmed'}
            if 'provided_answer' in args and str(args['provided_answer']).strip()!=(q.get('original_answer') or ''):
                answer=str(args['provided_answer']).strip()
                if len(answer)>300:raise ValueError('제공 정답은 300자 이하로 입력해 주세요.')
                changes['original_answer']=answer or None
                changes['source']={**q['source'],'answer_origin':'user_entry','previous_answer_origin':q['source'].get('answer_origin')}
                changes['source']['answer_ambiguity']=False
            if 'body' in args:
                # A form may edit text or equation source; regenerate every math tree.
                body=copy.deepcopy(q['body']);edits=args['body']
                edit_index=0
                for group in (body['blocks'],*body.get('choices',[])):
                    for b in paragraphs(group):
                        if b['kind'] not in ('math','text'):continue
                        key=str(edit_index);edit_index+=1
                        if key in edits:
                            if b['kind']=='text':b['value']=str(edits[key])[:10000]
                            elif b['kind']=='math':
                                new=equation(str(edits[key]),b.get('source_format','eqedit'));b.clear();b.update(new)
                changes['body']=body
            return s.revise(args['id'],changes)
        raise ValueError('지원하지 않는 명령입니다: '+action)
