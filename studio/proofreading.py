"""Non-destructive, versioned text inspection. Rules do not claim semantic proof."""
from __future__ import annotations
import copy
import re
from .model import checksum,stamp,paragraphs,plain_text

RULESET='text-review-1'
LIMITATION='자동 규칙 검사는 모든 맞춤법·수학적 의미 오류를 찾는 검수가 아닙니다. 의심 항목을 원문과 대조하며 원문을 자동으로 고치지 않습니다.'

def text_nodes(body):
    index=0
    for group in (body['blocks'],*body.get('choices',[])):
        for b in paragraphs(group):
            if b['kind']=='text':
                yield str(index),b
                index+=1

def inspect(body):
    findings=[]
    def finding(key,text,start,end,rule,reason,suggestion=None,severity='warning'):
        original=text[start:end]
        item={'text_key':key,'start':start,'end':end,'original':original,'context':text[max(0,start-25):min(len(text),end+25)],'rule':rule,'reason':reason,'suggestion':suggestion,'severity':severity,'origin':'local_rule'}
        item['id']=checksum(item)[:24];findings.append(item)
    for key,node in text_nodes(body):
        text=node['value']
        for match in re.finditer(r'[\ufffd\x00-\x08\x0b\x0c\x0e-\x1f]',text):
            finding(key,text,*match.span(),'broken_character','깨진 문자나 제어 문자가 있습니다. 원본과 대조해 복원해야 합니다.',None,'blocking')
        for match in re.finditer(r'([가-힣]{2,})\s+\1(?=\s|[.,?!]|$)',text):
            finding(key,text,*match.span(),'repeated_word','같은 낱말이 연속되어 있습니다. 의도한 표현인지 확인해 주세요.',match[1])
        for match in re.finditer(r'([가-힣])((?:은은|는는|을을|를를|이가가|에에))',text):
            finding(key,text,*match.span(),'repeated_particle','조사나 글자가 중복된 것으로 보입니다.',match[1]+match[2][:len(match[2])//2])
        for match in re.finditer(r'[?？]{2,}|[.]{2}(?![.])|[,]{2,}',text):
            # An ellipsis of three dots is intentional punctuation.
            if text[max(0,match.start()-1):match.end()+1].count('.')>=3:continue
            finding(key,text,*match.span(),'repeated_punctuation','문장 부호가 중복되어 있습니다.',match[0][0])
        for match in re.finditer(r'(?<=[가-힣]) {3,}(?=[가-힣])',text):
            finding(key,text,*match.span(),'excess_spacing','한글 문장 사이에 공백이 과도하게 들어 있습니다.',' ')
    fatal=sum(f['severity']=='blocking' for f in findings)
    return {'ruleset':RULESET,'state':'blocking' if fatal else 'findings' if findings else 'checked','blocking':fatal,'count':len(findings),'findings':findings,'limitation':LIMITATION}

def latest(store,qid,revision):
    rows=store.rows('SELECT value FROM text_reviews WHERE question_id=? AND revision=? ORDER BY created DESC,rowid DESC LIMIT 1',(qid,revision))
    if not rows:return None
    import json
    return json.loads(rows[0]['value'])

def save(store,q,report):
    from .model import identity,encode
    value={**report,'revision':q['revision'],'fingerprint':q['fingerprint'],'created':stamp()}
    with store.transaction() as db:
        row=db.execute('SELECT revision,trashed FROM questions WHERE id=?',(q['id'],)).fetchone()
        if not row or row[0]!=q['revision'] or row[1]:raise ValueError('검수 중 문항이 변경되었습니다. 최신 문항을 다시 검사해 주세요.')
        db.execute('INSERT INTO text_reviews VALUES(?,?,?,?,?)',(identity(),q['id'],q['revision'],encode(value),stamp()))
    return value

def run(store,qid,settings=None,cancel=lambda:False):
    q=store.question(qid)
    if not q or q['trashed']:raise ValueError('검수할 문항을 찾을 수 없습니다.')
    report=inspect(q['body']);report['ai_state']='not_requested'
    if settings and settings.get('provider')!='local':
        from . import ai
        report['ai_state']='running'
        try:
            proposed=ai.proofread(q,settings,cancel)
            report['findings'].extend(proposed);report['ai_state']='completed';report['ai_model']=settings.get('model') or 'default';report['ai_provider']=settings['provider']
        except InterruptedError:raise
        except Exception as exc:report['ai_state']='failed';report['ai_error']=str(exc)[:500]
    report['count']=len(report['findings']);report['blocking']=sum(f['severity']=='blocking' for f in report['findings'])
    report['state']='blocking' if report['blocking'] else 'findings' if report['count'] else 'checked'
    return save(store,q,report)

def apply(store,qid,revision,finding_id,replacement=None):
    q=store.question(qid)
    if not q or q['trashed'] or q['revision']!=revision:raise ValueError('문항이 변경되었습니다. 최신 검수 결과에서 수정해 주세요.')
    report=latest(store,qid,revision) or inspect(q['body'])
    f=next((f for f in report['findings'] if f['id']==finding_id),None)
    if not f:raise ValueError('검수 항목을 찾을 수 없습니다. 검수를 다시 실행해 주세요.')
    replacement=f.get('suggestion') if replacement is None else replacement
    if not isinstance(replacement,str) or len(replacement)>2000:raise ValueError('수정할 문구를 입력해 주세요.')
    body=copy.deepcopy(q['body']);nodes=dict(text_nodes(body));node=nodes.get(f['text_key'])
    if node is None or node['value'][f['start']:f['end']]!=f['original']:raise ValueError('검수 당시의 문구와 달라 수정하지 않았습니다. 다시 검사해 주세요.')
    node['value']=node['value'][:f['start']]+replacement+node['value'][f['end']:]
    source={**q['source'],'text_correction':{'from_revision':revision,'finding':f,'replacement':replacement,'created':stamp()}}
    rev=store.revise(qid,{'body':body,'source':source})
    return {'revision':rev,'review':run(store,qid)}

def dismiss(store,qid,revision,finding_id):
    q=store.question(qid)
    if not q or q['revision']!=revision:raise ValueError('문항이 변경되었습니다. 최신 결과를 확인해 주세요.')
    report=latest(store,qid,revision) or inspect(q['body'])
    finding=next((f for f in report['findings'] if f['id']==finding_id),None)
    if not finding:raise ValueError('검수 항목을 찾을 수 없습니다.')
    if finding['severity']=='blocking':raise ValueError('깨진 문자는 무시하여 사용 가능 처리할 수 없습니다. 원문을 확인해 수정해 주세요.')
    report=copy.deepcopy(report)
    for f in report['findings']:
        if f['id']==finding_id:f['dismissed']=True
    report['count']=sum(not f.get('dismissed') for f in report['findings'])
    report['state']='findings' if report['count'] else 'checked'
    return save(store,q,report)
