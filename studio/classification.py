"""Per-question curriculum and difficulty estimates; never score an input file.

The local rubric is a transparent estimate of the task, not an observed success
rate. File names, question positions, points and answer format are not inputs.
"""
from __future__ import annotations
import copy
import re
from .model import body_fingerprint, difficulty_band, encode, identity, stamp, plain_text, paragraphs

METHOD = 'question-content-2'
UNITS = ['다항식','방정식과 부등식','함수','경우의 수','행렬','기하','미적분','확률과 통계','집합과 명제','미분류']
LIMITATION = '문항 내용에 따른 규칙 기반 추정입니다. 실제 학생 정답률로 보정한 난이도가 아니며 문항별로 수정할 수 있습니다.'


def assess(body, course='미상', boundary_review=False):
    text = plain_text(body['blocks'])
    math = ' '.join(b.get('latex','') for b in paragraphs(body['blocks']) if b['kind']=='math')
    unit = subunit = kind = '미분류'
    score = None
    reasons = []

    def choose(u, s, k, value, reason):
        nonlocal unit, subunit, kind, score, reasons
        unit, subunit, kind, score, reasons = u, s, k, value, [reason]

    # Most specific tasks precede incidental vocabulary (e.g. complex roots).
    if '나머지' in text and any(w in text for w in ('다항식','나누','나눈','이차식')):
        choose('다항식','나머지정리','나머지정리의 적용',4,'나눗셈의 나머지 조건을 식의 값으로 바꾸는 문항')
        if '자연수' in text and any(w in text for w in ('모든','임의')):
            score=7;kind='일반 자연수와 나머지 조건';reasons.append('특정 수 대입을 넘어 일반 자연수에서 성립하는 관계를 해석')
            if '중복인수' in text or re.search(r'\)\s*\^\{?2',math):
                score=8;reasons.append('제곱 인수에 대한 나머지 조건까지 결합')
        elif any(w in text for w in ('다시','나머지를','나머지로')) and text.count('나머지')>=3:
            score=7;kind='나머지의 중첩 조건';reasons.append('둘 이상의 나눗셈 나머지 조건을 연결')
        elif text.count('나머지')>=2:
            score=5;reasons.append('여러 나머지 조건을 함께 사용')
    elif '다항식' in text and '나누어떨어' in text:
        choose('다항식','인수분해','인수정리와 나누어떨어짐',5,'나누어떨어지는 관계를 다항식의 인수 조건으로 변환')
        if text.count('나누어떨어')>=2:
            score=8;kind='여러 다항식의 인수 조건';reasons.append('여러 다항식 사이의 인수 관계와 공통 조건을 결합')
    elif '인수분해' in text:
        choose('다항식','인수분해','인수분해와 인수정리',3,'인수의 구조를 찾고 곱으로 분해')
    elif '다항식' in text and any(w in text for w in ('계산','연산','역으로','관계식')):
        inverse='역으로' in text or '관계식' in text and '구하' in text
        choose('다항식','다항식의 연산','다항식의 역연산' if inverse else '다항식의 연산',5 if inverse else 3,'주어진 결과에서 미지 다항식을 복원' if inverse else '식을 대입하고 동류항을 정리하는 연산')
    elif '두 실수' in text and re.search(r'\^\{?[23]',math) and '+' in math:
        choose('다항식','다항식의 연산','곱셈공식의 변형',5,'두 실수의 거듭제곱 합을 곱셈공식과 대칭식으로 변환')
    elif any(w in text for w in ('원기둥','삼각형','사각형','원뿔','구의 부피','도형','원의 방정식','직선의 방정식')):
        choose('기하','도형의 성질과 측정','입체도형의 부피' if '원기둥' in text or '부피' in text else '도형 조건의 활용',5,'도형의 관계를 식으로 바꾸어 계산')
    elif '이차방정식' not in text and any(w in text for w in ('최댓값','최솟값','판매액','매출액','판매 금액')):
        quadratic=any(w in text for w in ('이차','판매','매출')) or bool(re.search(r'\^\{?2',math))
        choose('방정식과 부등식' if quadratic else '함수','이차함수' if quadratic else '함수의 최대·최소','이차함수의 최대·최소' if quadratic else '함수의 최대·최소',5,'정의역에서 함수의 극값과 끝값을 비교')
        if '자연수' in text or '정수' in text:
            score=7;kind='정수 구간과 최대·최소';reasons.append('연속 함수의 값과 정수·자연수 조건을 함께 비교')
        if any(w in text for w in ('판매','매출')):
            score=6;kind='이차함수의 실생활 활용';reasons.append('문장에 주어진 수량·가격 관계를 함수로 모델링')
    elif '연립방정식' in text or '연립부등식' in text:
        inequality='부등식' in text
        choose('방정식과 부등식','부등식' if inequality else '여러 가지 방정식','연립부등식' if inequality else '연립방정식',5,'여러 식을 동시에 만족하는 해를 찾음')
        if '공통인 해' in text:
            score=7;kind='두 연립방정식의 공통 해';reasons.append('두 연립식의 공통 해로 미정계수까지 결정')
    elif '이차함수' in text:
        choose('방정식과 부등식','이차함수','이차함수의 성질',4,'이차함수의 식과 그래프 조건을 해석')
        if '직선' in text and any(w in text for w in ('만나','만날','교점','한 점')):
            score=6;kind='이차함수와 직선의 위치 관계';reasons.append('교점의 개수를 이차방정식의 판별식으로 해석')
        if '중근' in text or '만나지' in text:
            score=7;kind='함수와 근의 조건 결합';reasons.append('함수 조건과 근·교점의 조건을 함께 적용')
    elif '이차방정식' in text:
        choose('방정식과 부등식','이차방정식','이차방정식의 해',3,'이차식의 해를 구하는 기본 과제')
        if any(w in text for w in ('중근','실근의 개수','실근을 갖','실근을 가지')):
            score=5;kind='판별식과 근의 조건';reasons.append('판별식으로 근의 조건을 계수 조건으로 변환')
        if '두 근' in text or '근과 계수' in text:
            score=5;kind='근과 계수의 관계';reasons.append('두 근의 관계를 계수로 표현')
            if math.count('frac')>=2 or any(w in text for w in ('역수','거듭제곱')):
                score=7;kind='근의 관계와 식의 변환';reasons.append('근의 역수·거듭제곱 관계를 추가 변환')
        if '이차함수' in text or '일차함수' in text:
            score=7;kind='함수와 이차방정식의 결합';reasons.append('함수식과 근의 조건을 함께 해석')
    elif '삼차방정식' in text or '사차방정식' in text:
        choose('방정식과 부등식','여러 가지 방정식','고차방정식과 근의 관계',6,'고차식의 인수·근의 관계를 이용')
        if any(w in text for w in ('허근','켤레','두 실근','실근이 두')) or 'frac' in math:
            score=8;reasons.append('근의 성질·개수 또는 역수의 관계를 결합')
    elif any(w in text for w in ('복소수','허수','켤레')) or re.search(r'\bi\s*=',math) and 'sqrt' in math:
        choose('방정식과 부등식','복소수','복소수의 연산',3,'허수 단위와 복소수의 기본 연산')
        if any(w in text for w in ('켤레','실수')):
            score=5;kind='복소수의 성질';reasons.append('실수 조건 또는 켤레 관계로 계수를 결정')
        if 'sqrt' in math and ('음수' in text or re.search(r'\\sqrt\s*\{\s*-',math)):
            score=max(score,5);reasons.append('음수의 제곱근을 허수 단위로 변환')
    elif '부등식' in text:
        choose('방정식과 부등식','부등식','부등식의 해',4,'부등식의 해와 경계를 판별')
    elif any(w in text for w in ('순열','조합','경우의 수')):
        choose('경우의 수','순열과 조합' if '순열' in text or '조합' in text else '경우의 수','순열과 조합' if '순열' in text or '조합' in text else '합의 법칙과 곱의 법칙',4,'선택·배열의 경우를 세는 과제')
    elif '행렬' in text:
        choose('행렬','행렬의 연산','행렬의 연산',3,'행렬의 성분과 연산을 사용')
    elif any(w in text for w in ('확률','분산','표준편차','기댓값','정규분포')):
        choose('확률과 통계','확률' if '확률' in text else '통계','확률 계산' if '확률' in text else '통계량',4,'확률 또는 통계량의 정의를 적용')
    elif any(w in text for w in ('미분','도함수','적분','극한')):
        sub='적분' if '적분' in text else '극한' if '극한' in text else '미분'
        choose('미적분',sub,sub+'의 활용' if '활용' in text else sub+' 계산',5 if '활용' in text else 3,'문항에 제시된 '+sub+' 과제를 해석')
    elif any(w in text for w in ('집합','명제','대우','필요조건','충분조건')):
        choose('집합과 명제','명제' if '명제' in text or '조건' in text else '집합','명제의 판단' if '명제' in text or '조건' in text else '집합의 연산',4,'집합·명제의 관계를 판단')
    elif '함수' in text:
        choose('함수','함수의 성질','함수의 성질',4,'함수의 정의와 조건을 적용')
    elif '방정식' in text:
        choose('방정식과 부등식','방정식','방정식의 해',3,'방정식을 만족하는 해를 구함')

    if score is not None:
        if any(w in text for w in ('옳은 것만','모두 고르','ㄱ.','ㄴ.')):
            score=min(9,score+1);reasons.append('여러 명제의 참·거짓을 각각 판단')
        if any(w in text for w in ('서로 다른','양의 정수','음의 정수')) and score<7:
            score+=1;reasons.append('해의 구분 또는 정수 부호 조건을 추가 적용')
    state='estimated' if score is not None else 'unknown'
    if boundary_review:
        unit=subunit=kind='미분류';score=None;state='pending_boundary'
        reasons=['여러 문항이 섞일 수 있어 문항 경계를 확정한 뒤 분류합니다.']
    if not reasons:reasons=['이 문항을 판정할 충분한 분류 규칙이 없습니다. 문항별로 지정할 수 있습니다.']
    estimate={'score':score,'band':difficulty_band(score) if score is not None else None,'state':state,'scope':'question','origin':'local_rule','method':METHOD,'basis':reasons,'limitation':LIMITATION,'body_fingerprint':body_fingerprint(body)}
    classification={'course':course or '미상','unit':unit,'subunit':subunit,'type':kind,'certainty':'suggested','basis':'해당 문항의 본문·수식·조건에 따른 자동 제안','method':METHOD,'scope':'question','difficulty_assessment':estimate}
    return classification, score if score is not None else 5


def save(store,q,classification,difficulty):
    """Metadata-only revision: keep answers/reviews; exam snapshots stay frozen."""
    if not 1<=difficulty<=10:raise ValueError('문항 난이도는 1~10입니다.')
    if classification==q['classification'] and difficulty==q['difficulty']:return q['revision']
    new={**q,'classification':copy.deepcopy(classification),'difficulty':difficulty}
    rev=q['revision']+1
    with store.transaction() as db:
        row=db.execute('SELECT revision,trashed FROM questions WHERE id=?',(q['id'],)).fetchone()
        if not row or row[0]!=q['revision'] or row[1]:raise ValueError('분류 중 문항이 변경되었습니다. 최신 문항에서 다시 실행해 주세요.')
        store._version(db,q['id'],rev,new)
        if q.get('text_review'):
            report={**q['text_review'],'revision':rev,'created':stamp()}
            db.execute('INSERT INTO text_reviews VALUES(?,?,?,?,?)',(identity(),q['id'],rev,encode(report),stamp()))
        db.execute('UPDATE questions SET revision=? WHERE id=?',(rev,q['id']))
    return rev


def reclassify(store,qid):
    q=store.question(qid)
    if not q or q['trashed']:raise ValueError('분류할 문항을 찾을 수 없습니다.')
    if q['classification'].get('certainty')=='user_confirmed':return q['revision']
    c,d=assess(q['body'],q['classification'].get('course'),q['source'].get('boundary_review',False))
    return save(store,q,c,d)


def edit(store,qid,revision,values):
    q=store.question(qid)
    if not q or q['revision']!=revision:raise ValueError('문항이 변경되었습니다. 다시 열어 주세요.')
    if q['source'].get('boundary_review'):raise ValueError('문항 경계를 확정한 뒤 개별 문항을 분류해 주세요.')
    c=copy.deepcopy(q['classification'])
    for key in ('course','unit','subunit','type'):
        value=str(values.get(key,c.get(key,''))).strip()
        if not value or len(value)>100:raise ValueError('과목·단원·세부단원·유형은 각각 1~100자로 입력해 주세요.')
        c[key]=value
    score=values.get('difficulty')
    if type(score) is not int or not 1<=score<=10:raise ValueError('문항 난이도는 1~10의 정수입니다.')
    reason=str(values.get('reason','교사가 해당 문항의 난이도와 분류를 지정했습니다.')).strip()
    if not reason or len(reason)>1000:raise ValueError('분류 근거는 1~1000자로 입력해 주세요.')
    c.update(certainty='user_confirmed',scope='question',method=METHOD,basis=reason)
    c['difficulty_assessment']={'score':score,'band':difficulty_band(score),'state':'user_confirmed','scope':'question','origin':'user','method':METHOD,'basis':[reason],'body_fingerprint':q['fingerprint']}
    return save(store,q,c,score)


def upgrade_legacy(store):
    # Only replace the known fixed-5/fixed-7 importer rubric. Preserve teacher
    # values, AI-generated values and every old version/exam/grade.
    legacy=[q for q in store.questions() if q['classification'].get('basis')=='본문 어휘에 의한 자동 제안' and q['classification'].get('certainty')!='user_confirmed']
    if legacy:
        import sqlite3
        backups=store.root/'backups';backups.mkdir(exist_ok=True)
        target=sqlite3.connect(backups/('before-question-classification-'+identity()+'.sqlite'))
        try:store.db.backup(target)
        finally:target.close()
    for q in legacy:
        c,d=assess(q['body'],q['classification'].get('course'),q['source'].get('boundary_review',False))
        save(store,q,c,d)
    return len(legacy)
