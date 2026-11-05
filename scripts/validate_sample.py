"""Private acceptance for a user-supplied file; outputs are gitignored."""
import argparse
import json
from pathlib import Path
from studio.storage import Store
from studio.importers import import_document
from studio.model import paragraphs,identity
from studio.reasoning import check_question
from studio.variants import generate
from studio.exports import export_packet,PDF
from studio.assessment import grade,report,remediation
from pypdf import PdfReader

parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);parser.add_argument('--expected-count',type=int);args=parser.parse_args()
root=Path('work/private-acceptance')/identity();root.mkdir(parents=True);store=Store(root/'workspace')
result=import_document(store,args.source)
if args.expected_count:assert result['total']==args.expected_count
assert import_document(store,args.source)['duplicate']
for q in store.questions():store.save_answer(q['id'],q['revision'],q['fingerprint'],check_question(q))
original=store.questions();passed=[q for q in original if q['available']];held=[q for q in original if not q['available']]
parent=next(q for q in passed if q['answer']['proof']['policy']=='polynomial-linear-combination')
children=[generate(store,parent['id'],kind,{'provider':'local'},kind) for kind in ('numeric','thinking')]
assert all(store.question(qid)['available'] for qid in children)
draft=store.create_exam({'question_ids':[q['id'] for q in original],'title':'실제 자료 입력·출력 검토','confirm':False})
outputs=[]
for kind in ('questions','answers','solutions','workbook'):
    for fmt in ('pdf','hwpx'):
        path=export_packet(store,draft,kind,fmt=fmt);outputs.append(path)
        if fmt=='pdf':assert PdfReader(path).pages
eid=store.create_exam({'question_ids':[q['id'] for q in passed]+children,'title':'개별 시험 검증','confirm':True,'points':[5]*(len(passed)+2)})
sid=store.add_student({'name':'검증용 가상 학생','school':'테스트 학교','grade':'1학년','class_name':'테스트 반'})
attempt=store.assign(eid,[sid])[0];exam=store.exam(eid)
answers={i['id']:i['snapshot']['answer']['final_answer'] for i in exam['items']}
answers[exam['items'][0]['id']]='1';answers[exam['items'][1]['id']]=''
r=grade(store,attempt,answers,{exam['items'][0]['id']:2.5})
assert r['score']==r['maximum']-7.5 and r['items'][0]['status']=='partial' and r['items'][1]['status']=='blank'
outputs.append(str(PDF(store,store.root/'outputs/individual-report').report(r)))
remedial=remediation(store,attempt);assert len(store.exam(remedial)['items'])==2
retry=store.assign(eid,[sid])[0];assert report(store,retry)['attempt']['round']==2
grade(store,retry,{},absent=True);assert report(store,retry)['score'] is None
third=store.assign(eid,[sid])[0];answers[exam['items'][1]['id']]=exam['items'][1]['snapshot']['answer']['final_answer'];grade(store,third,answers)
numeric_homework=remediation(store,third,'numeric');assert len(store.exam(numeric_homework)['items'])==1
before=store.exam(eid)['items'][0]['snapshot'];store.revise(parent['id'],{'difficulty':8})
assert store.exam(eid)['items'][0]['snapshot']==before and report(store,attempt)['score']==r['score']
assert not store.question(parent['id'])['available']
store.backup(root/'backup.zip');dest=Store.restore(root/'backup.zip',root/'restored');restored=Store(dest)
assert report(restored,attempt)['score']==r['score']
summary={'import':{k:v for k,v in result.items() if k not in ('question_ids','document_id')},'original_question_count':len(original),'provided_answers':sum(bool(q['original_answer']) for q in original),'generated_answers':sum(bool((q.get('answer') or {}).get('final_answer')) for q in original),'generated_solutions':sum(bool((q.get('answer') or {}).get('steps')) for q in original),'passed':len(passed),'held':len(held),'held_reasons':[(q['answer']['reason']) for q in held],'images':sum(b['kind']=='image' for q in original for b in paragraphs(q['body']['blocks'])),'boxes':sum(b['kind']=='box' for q in original for b in paragraphs(q['body']['blocks'])),'variants':2,'output_count':len(outputs),'score':r['score'],'maximum':r['maximum'],'old_exam_unchanged':True,'backup_restored':True,'output_paths':outputs}
(root/'result.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');restored.db.close();store.db.close()
print(json.dumps({k:v for k,v in summary.items() if k!='output_paths'},ensure_ascii=False,indent=2));print('Private outputs:',root)
