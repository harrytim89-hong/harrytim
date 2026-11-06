"""Grading and factual reports from frozen exam items, never current answers."""
from __future__ import annotations
import math
from collections import defaultdict
from .algebra import scalar_answer,same,Unsupported
from .model import difficulty_band,question_difficulty

def auto_grade(submitted,question):
    if not submitted.strip():return 'blank',0
    answer=question.get('answer') or {}
    correct=answer.get('final_answer')
    if correct is None:return 'pending',None
    if question['body']['answer_format']=='mc':
        normalized=submitted.strip().translate(str.maketrans('①②③④⑤','12345'))
        if normalized not in ('1','2','3','4','5'):return 'pending',None
        return ('correct',1) if normalized==correct else ('wrong',0)
    try:
        a,b=scalar_answer(submitted),scalar_answer(correct)
        if a.free_symbols or b.free_symbols:
            return ('correct',1) if same(a,b) else ('pending',None)
        return ('correct',1) if same(a,b) else ('wrong',0)
    except (Unsupported,ValueError,TypeError):return 'pending',None

def grade(store,attempt_id,answers,manual=None,absent=False):
    attempt=next((a for a in store.attempts() if a['id']==attempt_id),None)
    if not attempt:raise ValueError('응시 기록을 찾을 수 없습니다.')
    exam=store.exam(attempt['exam_id']);manual=manual or {};rows=[]
    for item in exam['items']:
        submitted=str(answers.get(item['id'],''));status,ratio=auto_grade(submitted,item['snapshot'])
        score=round(item['points']*ratio,8) if ratio is not None else None
        if item['id'] in manual and manual[item['id']] is not None and manual[item['id']]!='':
            score=float(manual[item['id']])
            if not math.isfinite(score) or not 0<=score<=item['points']:raise ValueError(f"{item['position']}번 점수는 0~{item['points']}점으로 입력해 주세요.")
            status='correct' if score==item['points'] else 'partial' if score>0 else 'blank' if not submitted.strip() else 'wrong'
        rows.append((attempt_id,item['id'],submitted,score,status))
    with store.transaction() as db:
        db.execute('DELETE FROM results WHERE attempt_id=?',(attempt_id,))
        if not absent:db.executemany('INSERT INTO results VALUES(?,?,?,?,?)',rows)
        db.execute('UPDATE attempts SET state=? WHERE id=?',('absent' if absent else 'pending' if any(r[4]=='pending' for r in rows) else 'graded',attempt_id))
    return report(store,attempt_id)

def report(store,attempt_id):
    attempt=next((a for a in store.attempts() if a['id']==attempt_id),None)
    if not attempt:raise ValueError('응시 기록이 없습니다.')
    exam=store.exam(attempt['exam_id']);results={r['item_id']:r for r in store.rows('SELECT * FROM results WHERE attempt_id=?',(attempt_id,))}
    items=[];groups={key:defaultdict(lambda:{'count':0,'correct':0,'score':0,'maximum':0}) for key in ('unit','type','difficulty')}
    for item in exam['items']:
        result=results.get(item['id'],{'submitted':'','score':None,'status':'ungraded'})
        q=item['snapshot'];items.append({**item,**result})
        if attempt['state']=='absent':continue
        d=question_difficulty(q)
        for key,label in (('unit',q['classification']['unit']),('type',q['classification']['type']),('difficulty',difficulty_band(d) if d is not None else '미분류')):
            g=groups[key][label];g['count']+=1;g['correct']+=result['status']=='correct';g['score']+=result['score'] or 0;g['maximum']+=item['points']
    maximum=sum(i['points'] for i in exam['items']);score=sum(i['score'] or 0 for i in items)
    correct=sum(i['status']=='correct' for i in items)
    pending=sum(i['status'] in ('pending','ungraded') for i in items)
    return {'attempt':attempt,'exam':exam,'items':items,'score':None if attempt['state']=='absent' else score,'maximum':maximum,'correct':correct,'count':len(items),'pending':pending,'correct_rate':None if attempt['state']=='absent' else correct/len(items)*100,'score_rate':None if attempt['state']=='absent' else score/maximum*100,'groups':{k:dict(v) for k,v in groups.items()},'sample_size':1,'exam_difficulty':round(sum(i['snapshot']['difficulty'] for i in items)/len(items),1)}

def remediation(store,attempt_id,kind='original'):
    r=report(store,attempt_id)
    ids=[]
    for item in r['items']:
        if item['status'] not in ('wrong','partial','blank'):continue
        qid=item['question_id']
        if kind!='original':
            candidates=store.rows('SELECT child_id FROM lineage WHERE parent_id=? AND kind=?',(qid,kind))
            qs=[store.question(v['child_id']) for v in candidates]
            q=next((q for q in qs if q and q['available'] and not q['trashed']),None)
            if not q:raise ValueError(f"{item['position']}번의 검사 통과 {kind} 변형이 없습니다. 변형을 생성·검증한 후 다시 시도해 주세요.")
            qid=q['id']
        if qid not in ids:ids.append(qid)
    if not ids:raise ValueError('채점된 오답·부분정답·무응답 문항이 없습니다.')
    eid=store.create_exam({'question_ids':ids,'title':r['attempt']['name']+' · 오답 보완 과제','confirm':True,'date':r['exam']['exam_date'],'settings':r['exam']['settings']})
    store.assign(eid,[r['attempt']['student_id']])
    return eid
