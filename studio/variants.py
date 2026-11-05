"""Fresh immutable children with meaningful numeric vs inverse tasks."""
from __future__ import annotations
import secrets
import sympy as S
from .formula import equation
from .model import body_fingerprint,stamp,plain_text,checksum
from .reasoning import check_question,solve_policy
from .algebra import parse,symbol
from . import ai

def paragraph(*items):return {'kind':'paragraph','blocks':[{'kind':'text','value':i} if isinstance(i,str) else equation(S.latex(i),'latex') for i in items]}

def local_variant(parent,kind):
    result=solve_policy(parent['body'])
    if result['policy']!='polynomial-linear-combination':raise ValueError('이 유형의 로컬 변형은 아직 지원하지 않습니다. 설정에서 AI를 연결하여 생성해 주세요.')
    model=result['model'];a=parse(model['a'],'latex');b=parse(model['b'],'latex');A,B=symbol('A'),symbol('B');x,y=symbol('x'),symbol('y')
    seed=secrets.randbelow(7)+1;a=S.expand(a+seed*x*y);b=S.expand(b-(seed+1)*y*y);factor=secrets.randbelow(4)+2
    if kind=='numeric':
        # EqEdit declarations use the same recognized semantics as imported input.
        declaration=equation('A='+S.latex(a)+', B='+S.latex(b),'latex')
        body={'blocks':[paragraph('두 다항식 A, B에 대하여 다음과 같다.'),{'kind':'paragraph','blocks':[declaration]},paragraph('다항식 ',A+factor*B,'를 계산하시오.')],'choices':[],'answer_format':'short'}
        change='두 다항식의 계수와 결합 계수를 변경';purpose='동류항의 계수 계산 구조를 유지하며 연산을 연습'
    else:
        C=symbol('C');c=S.expand(a+factor*b)
        body={'blocks':[paragraph('두 다항식 A, C가 다음과 같다. 다항식 B를 역으로 구하시오.'),paragraph(S.Eq(A,a,evaluate=False)),paragraph(S.Eq(C,c,evaluate=False)),paragraph('관계식 ',S.Eq(A+factor*B,C,evaluate=False),'을 만족하는 다항식 B를 구하시오.')],'choices':[],'answer_format':'short'}
        change='선형 결합의 결과와 한 다항식을 주고 다른 다항식을 복원';purpose='순방향 대입에서 역방향 구조 파악으로 사고를 전환'
    return {'body':body,'classification':{**parent['classification'],'type':'다항식의 역연산' if kind=='thinking' else '다항식의 연산'},'difficulty':min(10,parent['difficulty']+(kind=='thinking')),'input_state':'complete','issues':[]},change,purpose

def generate(store,qid,kind,settings,job_key,cancel=lambda:False):
    parent=store.question(qid)
    if not parent or parent['trashed']:raise ValueError('원본 문항이 없습니다.')
    existing=store.rows('SELECT child_id,value FROM lineage WHERE parent_id=? AND kind=?',(qid,kind))
    import json
    for e in existing:
        if json.loads(e['value']).get('job_key')==job_key:return e['child_id']
    provider=settings.get('provider','local')
    if provider=='local':q,change,purpose=local_variant(parent,kind);proposal=None;model='exact-local-1.0'
    else:
        if any(b['kind']=='image' for b in __import__('studio.model',fromlist=['paragraphs']).paragraphs(parent['body']['blocks'])):raise ValueError('그림이 있는 문항의 자동 AI 변형은 도형 조건 구조화 전까지 보류합니다.')
        raw=ai.request(settings,('숫자변형' if kind=='numeric' else '사고변형')+'을 하나 생성하라.\n'+ai.question_prompt(parent),cancel)
        body,proposal=ai.validate(raw);change=raw['change'];purpose=raw['purpose'];model=settings.get('model') or 'default'
        blind=ai.request(settings,'다음 새 문항의 정답을 보지 말고 별도로 재풀이하라.\n'+ai.question_prompt({'body':body}),cancel)
        _,second=ai.validate(blind);proposal['blind_answer']=second['final_answer'];proposal['blind_steps']=second['steps']
        proposal['independence']='정답을 숨긴 별도 호출이지만 동일 모델일 수 있으므로 독립성은 제한됩니다.'
        if not change.strip() or not purpose.strip():raise ValueError('변경점과 교육적 목적이 필요합니다.')
        if kind=='thinking' and any(w in change for w in ('숫자만','문자만','계수만')):raise ValueError('수치·문자만 바꾼 응답은 사고변형으로 저장하지 않았습니다.')
        q={'body':body,'classification':{'course':raw['course'],'unit':raw['unit'],'type':raw['type'],'certainty':'suggested','basis':'AI 제안'},'difficulty':raw['difficulty'],'input_state':'complete','issues':[]}
    q['source']={'parent_id':qid,'parent_revision':parent['revision'],'number':parent['source'].get('number'),'generated':True}
    q['fingerprint']=body_fingerprint(q['body']);q['original_answer']=None
    q['answer']=check_question(q,proposal)
    q['answer']['origin']='local_generated' if provider=='local' else 'ai_with_calculation'
    if cancel():raise InterruptedError('변형 생성을 취소했습니다.')
    lineage={'parent_id':qid,'parent_revision':parent['revision'],'kind':kind,'change':change,'purpose':purpose,'provider':provider,'model':model,'job_key':job_key,'created':stamp()}
    with store.transaction() as db:return store.insert_question(db,q,None,lineage)
