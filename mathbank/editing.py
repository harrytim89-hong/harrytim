"""Manual structural boundary corrections preserve sources and old exam snapshots."""
import copy
import json
from .store import uid, now
from .hwpx import plain, walk_blocks, classify
from .validation import initial_stages, mark


def save_boundaries(store, parents, groups):
    if not parents or not groups: raise ValueError('문항 경계가 없습니다.')
    if len({q['document_id'] for q in parents}) != 1: raise ValueError('같은 자료의 문항만 합칠 수 있습니다.')
    if any(q['content'].get('format') != 'structured-v2' or store.is_trashed(q) for q in parents):
        raise ValueError('활성 HWPX 문항만 경계를 수정할 수 있습니다.')
    first = parents[0]
    ids = []
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        for q in parents:
            current=db.execute('SELECT version FROM questions WHERE id=?',(q['id'],)).fetchone()
            if current[0]!=q['version']:raise ValueError('동시 편집이 발생했습니다.')
        for i, (blocks, choices) in enumerate(groups):
            if not blocks: raise ValueError('빈 문항으로 나눌 수 없습니다.')
            c=copy.deepcopy(first['content'])
            c.update(blocks=copy.deepcopy(blocks),text=plain(blocks).strip(),choices=choices,
                choice_blocks=[],answer='',solution=[],answer_status='missing',solution_status='missing',verification_status='unverified',
                boundary_origin={'kind':'user_structural_edit','parents':[{'id':q['id'],'version':q['version']} for q in parents]})
            for key in ('verification','proposed_answer','proposed_solution','blind_resolve'):c.pop(key,None)
            c['origins']['answer']={'kind':'missing'};c['origins']['solution']={'kind':'missing'}
            issues=[b.get('issue','미지원 개체') for b in walk_blocks(blocks) if b['type']=='unsupported' or b['type']=='equation' and not b.get('supported')]
            c['input_status']='held' if issues else 'complete'
            c.update(classify(c['text'],c.get('course','')))
            stages=initial_stages()
            for key in ('segmentation','transcription','diagram','comparison','classification'):
                mark(stages,key,'exception' if issues else 'passed',1,'사용자가 문단 경계 수정 · 원본 보존')
            identifier=uid();ids.append(identifier)
            db.execute("INSERT INTO questions VALUES(?,?,1,?,?,?,?,0,?,?)",(identifier,first['document_id'],json.dumps([b.get('location',{}) for b in blocks],sort_keys=True),
                first['number']+('-'+str(i+1) if len(groups)>1 else ''),json.dumps(c,ensure_ascii=False),json.dumps(stages),'; '.join(issues),now()))
            db.execute('INSERT INTO lineage VALUES(?,?,?,?,?,?,?,?)',(identifier,first['id'],first['version'],'split' if len(groups)>1 else 'merge',
                json.dumps(c['boundary_origin']),json.dumps({}),now(),None))
        for q in parents:
            db.execute("INSERT OR IGNORE INTO trash VALUES('question',?,?)",(q['id'],now()))
            db.execute("UPDATE jobs SET status='cancelled',error='문항 경계 수정' WHERE target=? AND status IN ('queued','running','paused')",(q['id'],))
    return ids


def split_question(store, identifier, before_block):
    q=store.question(identifier);blocks=q['content'].get('blocks',[])
    if type(before_block) is not int or not 1<=before_block<len(blocks):raise ValueError('나누는 문단 위치 오류')
    return save_boundaries(store,[q],[(blocks[:before_block],[]),(blocks[before_block:],q['content'].get('choices',[]))])


def merge_questions(store, identifiers):
    if len(identifiers)<2 or len(set(identifiers))!=len(identifiers):raise ValueError('합칠 문항을 2개 이상 선택하세요.')
    parents=[store.question(i) for i in identifiers]
    return save_boundaries(store,parents,[([b for q in parents for b in q['content'].get('blocks',[])],
        [choice for q in parents for choice in q['content'].get('choices',[])])])
