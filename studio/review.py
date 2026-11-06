"""Document-centred workflow and faithful source views for imported questions."""
from __future__ import annotations
import copy
from .model import paragraphs,encode,plain_text

def summary(store,did):
    document=next((d for d in store.documents() if d['id']==did and not d['trashed']),None)
    if not document:raise ValueError('자료를 찾을 수 없습니다.')
    qs=[q for q in store.questions() if q['document_id']==did]
    unresolved=[q for q in qs if q['source'].get('boundary_review')]
    import re
    suspects=[]
    for q in qs:
        text=''.join(b['value'] for b in paragraphs(q['body']['blocks']) if b['kind']=='text')
        formulas=' '.join(b.get('source','') for b in paragraphs(q['body']['blocks']) if b['kind']=='math')
        choice_as_item=q['source'].get('boundary_evidence') in ('paragraph-numbering','inline-numbering') and bool(re.fullmatch(r'[①-⑤\s]*',text)) and '?' not in formulas
        combined=text.count('①')>=2 and text.count('⑤')>=2
        if choice_as_item or combined:suspects.append(q)
    typed=[q for q in qs if not q['source'].get('boundary_review')]
    findings=[(q,f) for q in qs for f in q['text_review']['findings'] if not f.get('dismissed')]
    ready=[q for q in qs if q['available']]
    pending=[q for q in typed if not q.get('answer')]
    import json
    last_exam=next((e for e in store.exams() if json.loads(e['settings']).get('source_document_id')==did and e['status']=='confirmed'),None)
    if suspects and document['report'].get('parser_version',0)<3:
        next_action='reparse';next_title='이전 버전의 분리 결과를 다시 분석하세요';next_reason=f'{len(suspects)}문항에서 보기 번호 또는 여러 보기 묶음이 문항 경계로 잘못 처리되었을 가능성이 있습니다. 관리 원본에서 다시 분리하고 이전 기록은 보존합니다.'
    elif unresolved:
        next_action='reparse' if document['report'].get('parser_version',0)<4 else 'boundaries'
        next_title='자동 분리를 다시 분석하세요' if next_action=='reparse' else '자동 분리안을 확인하세요'
        next_reason=f'{len(unresolved)}개 묶음의 경계가 아직 확정되지 않았습니다. 시작 문단을 전부 찾는 대신 자동 제안부터 보여 드립니다.'
    elif findings:
        next_action='proofreading';next_title='원문과 의심 문구를 대조하세요';next_reason=f'오타나 문자 깨짐이 의심되는 표현 {len(findings)}건을 찾았습니다. 원문은 보존하며 수정은 새 버전으로 저장합니다.'
    elif pending:
        next_action='explain';next_title='정답·해설을 생성하세요';next_reason=f'{len(pending)}문항을 저장했습니다. 원본 정답이 없어도 별도로 풀고 검사할 수 있습니다.'
    elif ready and last_exam:
        next_action='exam';next_title='만든 시험을 출력하고 학생에게 배정하세요';next_reason='시험지·빠른정답·해설을 저장한 다음 학생을 배정합니다. 답안 입력과 성적표는 성적표 메뉴에서 이어집니다.'
    elif ready:
        next_action='compose';next_title='검사 통과 문항으로 시험지를 만드세요';next_reason=f'{len(ready)}문항이 자동 사용 가능합니다. 보류 문항은 이유를 확인하고 나중에 추가할 수 있습니다.'
    else:
        next_action='verification';next_title='해설 검증의 보류 사유를 확인하세요';next_reason='입력과 풀이 상태를 각각 확인합니다. 지원하지 않는 조건은 통과한 것처럼 처리하지 않습니다.'
    return {'document':document,'question_ids':[q['id'] for q in qs],'counts':{'questions':len(typed),'bundles':len(unresolved),'mc':sum(q['body']['answer_format']=='mc' for q in typed),'short':sum(q['body']['answer_format']=='short' for q in typed),'text_findings':len(findings),'blocking_text':sum(f['severity']=='blocking' for _,f in findings),'solutions':sum(bool((q.get('answer') or {}).get('steps')) for q in typed),'ready':len(ready),'held':sum((q.get('answer') or {}).get('verification') in ('held','failed') for q in typed)},'next_action':next_action,'next_title':next_title,'next_reason':next_reason,'first_boundary':unresolved[0]['id'] if unresolved else None,'first_finding':findings[0][0]['id'] if findings else None,'first_held':next((q['id'] for q in typed if (q.get('answer') or {}).get('verification') in ('held','failed')),None),'ready_ids':[q['id'] for q in ready],'pending_ids':[q['id'] for q in pending],'has_repair_history':bool(document['report'].get('repair_history')),'last_exam_id':last_exam['id'] if last_exam else None}

def source(store,q):
    if not q.get('document_id'):return {'kind':'generated','blocks':copy.deepcopy(q['body']['blocks']),'message':'생성 문항입니다. 원본 연결은 출처 탭에서 확인할 수 있습니다.'}
    from .importers import read_package,Decoder
    from .boundaries import document_units,own_notes,note_at_start
    doc=next(d for d in store.documents() if d['id']==q['document_id'])
    _,files,manifest,sections,_=read_package(store.path(doc['rendition']))
    desired=set(q['source'].get('locations',[]));units=document_units(sections)
    if not desired.intersection(u.location for u in units):units=document_units(sections,review=True)
    selected=[u for u in units if u.location in desired]
    if not selected:
        selected=[u for u in units if u.part==q['source'].get('part') and q['source'].get('paragraph_start',0)<=u.paragraph<=q['source'].get('paragraph_end',-1)]
    notes=[n for u in selected for n in own_notes(u.node) if note_at_start(u.node,n)]
    decoder=Decoder(store,files,manifest,notes)
    blocks=[b for u in selected for b in decoder.parse(u.node)]
    return {'kind':'extracted_source','blocks':blocks,'locations':[u.location for u in selected],'message':'관리 원본의 해당 구역·문단을 다시 읽은 원문 추출 보기입니다. 한글의 페이지 배치를 재현한 화면은 아닙니다.','original_note':q['source'].get('original_note')}

def undo_reparse(store,did):
    doc=next(d for d in store.documents() if d['id']==did)
    history=list(doc['report'].get('repair_history',[]))
    if not history:raise ValueError('되돌릴 자동 재분리 이력이 없습니다.')
    event=history.pop()
    active={q['id'] for q in store.questions() if q['document_id']==did}
    if active!=set(event['after']):raise ValueError('재분리 후 문항 구성이 바뀌어 자동으로 되돌리지 않았습니다. 이전 문항은 휴지통에 보존되어 있습니다.')
    report={**event['old_report'],'repair_history':history}
    with store.transaction() as db:
        for qid in event['after']:db.execute('UPDATE questions SET trashed=1 WHERE id=?',(qid,))
        for qid in event['before']:db.execute('UPDATE questions SET trashed=0 WHERE id=?',(qid,))
        db.execute('UPDATE documents SET report=? WHERE id=?',(encode(report),did))
    return {'restored':len(event['before'])}
