"""Resolve only uncertain boundaries; keep originals and past exam snapshots."""
from __future__ import annotations
import copy
import json
from .boundaries import PREFIX,strip_prefix
from .importers import choice_split,detach_original_points,classify
from .model import plain_text,paragraphs,encode,identity

def split_saved(store,qid,revision,starts):
    q=store.question(qid)
    if not q or q['trashed']:raise ValueError('자료가 이미 분리되었거나 휴지통에 있습니다. 목록을 새로고침해 주세요.')
    if q['revision']!=revision:raise ValueError('자료가 수정되었습니다. 최신 내용에서 문항 경계를 다시 선택해 주세요.')
    if not q['source'].get('boundary_review'):raise ValueError('경계 확인이 필요한 자료가 아닙니다.')
    blocks=q['body']['blocks']
    if not isinstance(starts,list) or not starts or any(type(i) is not int for i in starts):raise ValueError('각 문항의 시작 문단을 하나 이상 선택해 주세요.')
    if len(starts)!=len(set(starts)) or any(i<0 or i>=len(blocks) for i in starts):raise ValueError('문항 시작 위치를 확인해 주세요.')
    starts=sorted(starts);doc=next(d for d in store.documents() if d['id']==q['document_id'])
    batch=identity();children=[]
    for index,start in enumerate(starts):
        end=starts[index+1] if index+1<len(starts) else len(blocks)
        selected=copy.deepcopy(blocks[start:end])
        original_locations=[b['source_location'] for b in selected if b.get('source_location')]
        if not any(plain_text([b]).strip() or b['kind'] in ('image','table') for b in selected):raise ValueError('빈 문단만 포함된 문항이 있습니다.')
        text=''.join(b.get('value','') for b in selected[0].get('blocks',[]) if b['kind']=='text') if selected[0]['kind']=='paragraph' else ''
        mark=PREFIX.match(text)
        number=int(next(mark[k] for k in ('ln','bn','pn','rn') if mark[k] is not None)) if mark else None
        strip_prefix(selected,mark[0] if mark else '')
        selected,choices,choice_issues=choice_split(selected);original_points=detach_original_points(selected)
        body={'blocks':selected,'choices':choices,'answer_format':'mc' if choices else 'short'}
        issues=[{'reason':message} for message in choice_issues]
        issues.extend({'reason':b['label']} for b in paragraphs(selected) if b['kind']=='unsupported')
        issues.extend(i for i in q['issues'] if i.get('audit'))
        classification,difficulty=classify(body,doc['metadata'])
        locations=original_locations
        position={'part':locations[0]['part'],'paragraph_start':locations[0]['paragraph'],'paragraph_end':locations[-1]['paragraph'],'locations':[l['path'] for l in locations]} if locations else {}
        children.append({'body':body,'source':{**q['source'],**position,'number':number or index+1,'original_points':original_points,'profile':'user-selected-boundaries','boundary_review':False,'split_from':qid,'split_revision':revision,'split_batch':batch,'block_start':start,'block_end':end,'answer_origin':None},'classification':classification,'difficulty':difficulty,'input_state':'held' if issues else 'complete','issues':issues})
    with store.transaction() as db:
        row=db.execute('SELECT revision,trashed FROM questions WHERE id=?',(qid,)).fetchone()
        if not row or row[0]!=revision or row[1]:raise ValueError('자료가 이미 변경되었습니다. 목록을 새로고침해 주세요.')
        ids=[store.insert_question(db,child,q['document_id']) for child in children]
        db.execute('UPDATE questions SET trashed=1 WHERE id=?',(qid,))
        counts=db.execute('SELECT v.input_state,count(*) FROM questions q JOIN versions v ON q.id=v.question_id AND q.revision=v.revision WHERE q.document_id=? AND q.trashed=0 GROUP BY v.input_state',(q['document_id'],)).fetchall()
        counts=dict(counts);total=sum(counts.values());complete=counts.get('complete',0)
        report=dict(doc['report']);report.update(total=total,complete=complete,held=total-complete,split_reviewed=True)
        report.setdefault('boundary_history',[]).append({'parent_id':qid,'revision':revision,'batch':batch,'starts':starts,'children':ids,'preamble_blocks':copy.deepcopy(blocks[:starts[0]])})
        db.execute('UPDATE documents SET report=? WHERE id=?',(encode(report),q['document_id']))
    return {'question_ids':ids,'total':len(ids),'complete':sum(q['input_state']=='complete' for q in children),'held':sum(q['input_state']!='complete' for q in children)}
