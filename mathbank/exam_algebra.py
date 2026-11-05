"""Explicit source-expression policies for common high-school algebra questions.

No school name, file hash, item number or supplied answer determines a result.
Every policy binds a full prose pattern to parsed mathematical expressions.
"""
import re
import sympy as s


def solve_exam(content):
    from .solver import safe_expr
    source = re.sub(r'\[\s*\$?\d+(?:\.\d+)?\$?\s*점\s*\]', '', content['text']).strip()
    formula = []
    def mark(m):
        formula.append(m.group(1));return '@'+str(len(formula)-1)
    prose = re.sub(r'\s+', '', re.sub(r'\$([^$]+)\$',mark,source))
    x,y,a,b,k,A,B,C = s.symbols('x y a b k A B C',real=True)
    symbols = dict(zip(('x','y','a','b','k','A','B','C'),(x,y,a,b,k,A,B,C)))
    symbols['i']=s.I
    def expr(text, extra=None):
        return safe_expr(text,dict(symbols,**(extra or {})),allow_complex=True)
    def math(i, extra=None): return expr(formula[i],extra)
    def equation(i, extra=None):
        parts=formula[i].split('=')
        if len(parts)!=2:raise ValueError('등식 형식 오류')
        return s.expand(expr(parts[0],extra)-expr(parts[1],extra))
    def latex(v):return '$'+s.latex(v)+'$'
    def require(ok,reason):
        if not ok:raise ValueError(reason)
    policy=None;steps=[];checks=[];result=None;details={}
    if prose=='두다항식@0에대하여@1일때,@2를계산하면?':
        require(re.sub(r'\s+','',formula[0])=='A,B','다항식 이름 관계 확인 필요')
        assignments=formula[1].split(',')
        require(len(assignments)==2,'두 다항식 정의가 필요합니다.')
        definitions={}
        for item in assignments:
            name,value=item.split('=');name=name.strip()
            require(name in ('A','B'),'미지원 다항식 이름')
            definitions[symbols[name]]=expr(value)
        require(set(definitions)=={A,B},'정의 중복/누락')
        p,q=(s.Poly(definitions[t],x,y) for t in (A,B))
        require(p.total_degree()<=4 and q.total_degree()<=4,'다항식 차수 범위 초과')
        target=math(2);require(not (target.free_symbols-{A,B}),'묻는 식에 미정 변수가 있습니다.')
        result=s.expand(target.subs(definitions))
        # Independent coefficient arithmetic on polynomial ring elements.
        ring=s.Poly(target,A,B)
        require(ring.total_degree()<=1,'다항식 선형 결합 검사 범위 초과')
        direct=ring.coeff_monomial(A)*p+ring.coeff_monomial(B)*q+s.Poly(ring.coeff_monomial(1),x,y)
        require(s.expand(direct.as_expr()-result)==0,'다항식 계수 검산 충돌')
        policy='polynomial-linear-combination'
        details={'definitions':definitions,'target':target}
        steps=[f'두 다항식의 정의를 묻는 식 {latex(target)}에 각각 대입합니다.',
            f'{latex(target)}에서 같은 차수·같은 문자를 가진 항끼리 모으면 {latex(result)}입니다.',
            '각 단항식의 계수를 따로 계산한 결과와 전개 결과가 일치합니다.']
        checks=['symbolic expansion','independent coefficient arithmetic']
    elif prose=='두다항식@0에대하여@1이고@2일때,다항식@3를구하시오.':
        require(re.sub(r'\s+','',formula[0])=='A,C' and formula[3].strip()=='B','역방향 다항식 대상 확인 필요')
        definitions={}
        for part in formula[1].split(','):
            name,value=part.split('=');name=name.strip()
            require(name in ('A','C'),'다항식 이름 확인 필요');definitions[symbols[name]]=expr(value)
        require(set(definitions)=={A,C},'정의 누락/중복')
        relation=equation(2)
        require(not relation.free_symbols-{A,B,C},'미정 변수 조건 미지원')
        p=s.Poly(relation.subs(definitions),B)
        require(p.degree()==1 and not p.LC().free_symbols and p.LC()!=0,'역방향 관계의 해가 유일하지 않습니다.')
        result=s.expand(-p.TC()/p.LC())
        require(s.expand(relation.subs(definitions).subs(B,result))==0,'원래 관계식 대입 검산 실패')
        policy='inverse-polynomial-linear-combination'
        details={'definitions':definitions,'relation':relation}
        steps=['주어진 두 다항식을 관계식에 대입하고, 구하려는 다항식 $B$를 한쪽에 남깁니다.',
            f'각 항의 계수를 계산하면 {latex(s.Eq(B,result))}입니다.',
            '이 다항식을 처음 관계식에 다시 대입하면 양변의 모든 단항식 계수가 일치합니다.']
        checks=['nonzero coefficient of unknown polynomial','coefficient solving','original polynomial relation substitution']
    elif prose=='등식@0을만족시키는두실수@1에대하여@2의값은?(단,@3)':
        require(re.sub(r'\s+','',formula[1])=='x,y','실수 변수 조건 확인 필요')
        require(s.simplify(equation(3))==0,'허수단위 정의 확인 필요')
        f=equation(0);real,imag=s.expand_complex(f).as_real_imag()
        matrix,rhs=s.linear_eq_to_matrix([real,imag],[x,y])
        require(matrix.shape==(2,2) and matrix.det()!=0,'연립일차방정식의 해가 유일하지 않습니다.')
        values=matrix.inv()*rhs;solution={x:values[0],y:values[1]}
        require(s.simplify(f.subs(solution))==0,'원래 복소수 등식 대입 실패')
        result=s.simplify(math(2).subs(solution));require(not result.free_symbols,'묻는 값이 결정되지 않습니다.')
        policy='complex-linear-real-unknowns'
        steps=[f'실수부와 허수부를 각각 비교하여 {latex(real)}=0, {latex(imag)}=0을 얻습니다.',
            f'두 일차방정식을 풀면 {latex(s.Eq(x,values[0]))}, {latex(s.Eq(y,values[1]))}입니다.',
            f'원래 등식에 대입해 확인하고, 묻는 값을 계산하면 {latex(result)}입니다.']
        checks=['real/imaginary separation','nonzero determinant','original complex equation substitution']
    elif prose=='이차방정식@0이실근을갖도록하는실수@1의최댓값은?':
        require(formula[1].strip()=='a','매개변수 조건 미지원')
        p=s.Poly(equation(0),x);require(p.degree()==2,'이차방정식이 아닙니다.')
        u,v,w=p.all_coeffs();require(not u.free_symbols and u!=0,'이차항 소멸 가능성')
        require(all(c.is_real is True for c in (u,v,w)),'실근 판별 정책은 실수 계수만 지원합니다.')
        d=s.expand(v*v-4*u*w);dp=s.Poly(d,a)
        require(dp.degree()==1 and dp.LC()<0,'최댓값이 유한하게 결정되지 않습니다.')
        result=-dp.TC()/dp.LC()
        vertex=-v.subs(a,result)/(2*u)
        require(s.simplify(p.as_expr().subs({a:result,x:vertex}))==0,'경계 중근 검산 실패')
        policy='quadratic-real-root-parameter-maximum'
        steps=[f'실근이 존재할 필요충분조건은 판별식 {latex(d)}가 0 이상인 것입니다.',
            f'이를 정리하면 {latex(s.Le(a,result))}이므로 최댓값은 {latex(result)}입니다.',
            f'이때 {latex(s.Eq(x,vertex))}가 실제 중근이고, 더 큰 값에서는 판별식이 음수입니다.']
        checks=['nonzero quadratic coefficient','necessary/sufficient discriminant inequality','boundary double-root substitution']
    elif prose=='다항식@0를@1로나누었을때의나머지는@2이고,@3를@4로나누었을때의나머지는@5이다.@6를@7로나누었을때의나머지는?':
        require(all(re.sub(r'\s+','',formula[i])=='f(x)' for i in (0,3,6)),'동일한 다항식인지 확인 필요')
        d1,d2=math(1),math(4);p1,p2=s.Poly(d1,x),s.Poly(d2,x)
        require(not (d1.free_symbols|d2.free_symbols)-{x},'매개변수 인수의 정의역 검사는 미지원입니다.')
        require(p1.degree()==p2.degree()==1,'일차식으로 나눈 나머지 조건만 지원')
        r1,r2=-p1.TC()/p1.LC(),-p2.TC()/p2.LC();require(r1!=r2,'나누는 일차식의 근이 중복됩니다.')
        rem1,rem2=math(2),math(5);require(not (rem1.free_symbols|rem2.free_symbols),'상수 나머지가 아닙니다.')
        require(s.Poly(math(7),x).monic()==s.Poly(d1*d2,x).monic(),'나누는 식의 인수 관계가 다릅니다.')
        result=s.expand(rem1+(rem2-rem1)*(x-r1)/(r2-r1))
        require(result.subs(x,r1)==rem1 and result.subs(x,r2)==rem2,'나머지 대입 검산 실패')
        policy='remainder-two-distinct-linear-factors'
        steps=[f'나머지정리에 따라 {latex(s.Eq(s.Function("f")(r1),rem1))}, {latex(s.Eq(s.Function("f")(r2),rem2))}입니다.',
            '이차식으로 나눈 나머지는 일차 이하입니다. 두 값을 지나는 일차식을 구합니다.',
            f'두 조건을 연립하면 나머지는 {latex(result)}입니다. 두 근에 다시 대입하면 각각 원래 나머지가 됩니다.']
        checks=['factor relation','distinct roots','degree bound','two-point interpolation','both remainder substitutions']
    elif prose=='두실수@0에대하여@1이고@2일때,@3의값은?':
        require(re.sub(r'\s+','',formula[0])=='x,y','실수 변수 조건 확인 필요')
        f,g=equation(1),equation(2)
        total=s.simplify(x+y-f);cubes=s.simplify(x**3+y**3-g)
        require(not total.free_symbols and not cubes.free_symbols and total.is_real is True and cubes.is_real is True and total!=0,'대칭식 조건 범위 미지원')
        product=(total**3-cubes)/(3*total);d=total**2-4*product
        require(d>=0,'두 실수 조건을 만족하지 않습니다.')
        roots=[(total+s.sqrt(d))/2,(total-s.sqrt(d))/2]
        require(all(r.is_real is True for r in roots),'실수 조건을 만족하지 않습니다.')
        target=math(3);values=[]
        for u,v in (roots,roots[::-1]):
            subs={x:u,y:v};require(s.simplify(f.subs(subs))==s.simplify(g.subs(subs))==0,'원래 조건 대입 실패')
            values.append(s.simplify(target.subs(subs)))
        require(values[0]==values[1],'묻는 식의 값이 유일하지 않습니다.');result=values[0]
        policy='two-real-variables-sum-and-cube-sum'
        steps=[f'항등식 $(x+y)^3=x^3+y^3+3xy(x+y)$에 조건을 대입하면 {latex(s.Eq(x*y,product))}입니다.',
            f'합이 {latex(total)}, 곱이 {latex(product)}인 두 실수의 존재를 판별식으로 확인합니다.',
            f'묻는 식을 계산하면 {latex(result)}입니다. 가능한 두 순서쌍에 모두 대입해 같은 값을 확인했습니다.']
        checks=['symmetric polynomial identity','real feasibility discriminant','all ordered pairs','original conditions substitution','unique target']
    elif prose=='삼차방정식@0의한근이@1일때,나머지두근의합은?(단,@2는실수,@3)':
        require(re.sub(r'\s+','',formula[2])=='a,b' and s.simplify(equation(3))==0,'실수 계수/허수단위 조건 확인 필요')
        p=s.Poly(equation(0),x);require(p.degree()==3 and p.LC()!=0,'삼차방정식 조건 오류')
        r=math(1);require(not r.free_symbols and s.im(r)!=0,'비실수 근 조건 확인 필요')
        f=s.expand_complex(p.as_expr().subs(x,r));re_,im_=f.as_real_imag()
        matrix,rhs=s.linear_eq_to_matrix([re_,im_],[a,b]);require(matrix.det()!=0,'실수 계수가 유일하게 결정되지 않습니다.')
        vals=matrix.inv()*rhs;poly=p.as_expr().subs({a:vals[0],b:vals[1]})
        require(all(c.is_real is True for c in s.Poly(poly,x).all_coeffs()),'실수 계수 조건을 만족하지 않습니다.')
        pair=s.expand((x-r)*(x-s.conjugate(r)));quo,rem=s.div(poly,pair,x)
        require(s.simplify(rem)==0 and s.Poly(quo,x).degree()==1,'켤레근 인수 나눗셈 검사 실패')
        t=-s.Poly(quo,x).TC()/s.Poly(quo,x).LC()
        result=s.simplify(s.conjugate(r)+t)
        require(s.simplify(poly.subs(x,t))==0,'세 번째 근 대입 실패')
        policy='real-cubic-known-nonreal-root'
        steps=[f'실수 계수 다항식이므로 {latex(s.conjugate(r))}도 근입니다.',
            f'주어진 근을 대입해 실수부·허수부를 비교하면 {latex(s.Eq(a,vals[0]))}, {latex(s.Eq(b,vals[1]))}입니다.',
            f'켤레근의 이차인수 {latex(pair)}로 나누면 남은 인수는 {latex(quo)}이므로 세 번째 근은 {latex(t)}입니다.',
            f'따라서 주어진 근을 제외한 두 근의 합은 {latex(result)}입니다. 인수분해와 원식 대입으로 확인했습니다.']
        checks=['real-coefficient conjugate-root theorem','unique coefficient system','exact polynomial division','third-root substitution']
    elif prose=='이차방정식@0의두근을@1와@2라할때,@3의값은?':
        require(formula[1].strip()==r'\alpha' and formula[2].strip()==r'\beta','근 이름 관계 확인 필요')
        require(re.sub(r'[\s{}]','',formula[3])==r'\alpha^3+\beta^3','미지원 근의 대칭식')
        p=s.Poly(equation(0),x);require(p.degree()==2 and not p.as_expr().free_symbols-{x},'숫자 계수 이차방정식 필요')
        u,v,w=p.all_coeffs();total=-v/u;product=w/u;result=s.simplify(total**3-3*product*total)
        d=v*v-4*u*w;r1=(-v+s.sqrt(d))/(2*u);r2=(-v-s.sqrt(d))/(2*u)
        require(s.simplify(r1**3+r2**3-result)==0 and s.simplify(p.as_expr().subs(x,r1))==0 and s.simplify(p.as_expr().subs(x,r2))==0,'근의 공식 재풀이 충돌')
        policy='quadratic-root-cube-sum'
        steps=[f'근과 계수의 관계에 따라 두 근의 합은 {latex(total)}, 곱은 {latex(product)}입니다.',
            '세제곱 합 항등식 $\\alpha^3+\\beta^3=(\\alpha+\\beta)^3-3\\alpha\\beta(\\alpha+\\beta)$를 이용합니다.',
            f'대입하여 정리하면 {latex(result)}입니다. 근의 공식으로 구한 두 근의 세제곱 합과도 일치합니다.']
        checks=['Vieta sum/product','cubic identity','independent quadratic-formula evaluation','both root substitutions']
    elif prose=='직선@0가이차함수@1의그래프와한점에서만나고,직선@2가이차함수@3의그래프와만나지않도록하는실수@4의값은?':
        require(formula[4].strip()=='k' and s.simplify(equation(0)-equation(2))==0,'직선/매개변수 관계 확인 필요')
        polys=[s.Poly(equation(i)-equation(0),x) for i in (1,3)]
        require(all(p.degree()==2 and not p.LC().free_symbols and p.LC()!=0 for p in polys),'이차항 소멸 가능성')
        require(all(c.is_real is True for p in polys for c in p.all_coeffs()),'그래프 교점 정책은 실수 계수만 지원합니다.')
        discs=[s.discriminant(p.as_expr(),x) for p in polys]
        candidates=s.solveset(discs[0],k,domain=s.S.Reals);require(isinstance(candidates,s.FiniteSet),'접하는 조건의 후보가 유한하지 않습니다.')
        accepted=[v for v in candidates if s.simplify(discs[1].subs(k,v))<0]
        require(len(accepted)==1,'두 조건을 만족하는 매개변수가 유일하지 않습니다.');result=accepted[0]
        require(s.discriminant(polys[0].as_expr().subs(k,result),x)==0 and s.discriminant(polys[1].as_expr().subs(k,result),x)<0,'최종 조건 재검사 실패')
        policy='line-quadratic-tangent-and-disjoint'
        steps=[f'첫 이차함수와 직선의 식을 같게 두면 판별식이 {latex(s.factor(discs[0]))}입니다. 한 점에서 만나므로 이 값은 0입니다.',
            f'실수 후보는 {", ".join(latex(v) for v in candidates)}입니다.',
            f'두 번째 이차함수와 만나지 않으려면 판별식 {latex(discs[1])}이 음수여야 합니다.',
            f'모든 후보를 대조하면 두 조건을 만족하는 값은 {latex(result)}뿐입니다.']
        checks=['nonzero quadratic terms','all real tangent candidates','negative second discriminant','uniqueness','final discriminant recalculation']
    elif prose=='어느분식집에서김밥한줄의가격이@0원일때하루에@1줄씩팔린다고한다.이김밥한줄의가격을@2원씩내릴때마다하루판매량은@3줄씩증가한다고한다.이김밥의하루판매액이최대일때의김밥한줄의가격은?':
        nums=[expr(re.sub(r'\s*,\s*','',formula[i])) for i in range(4)];price,demand,drop,growth=nums
        require(all(v.is_Integer and v>0 for v in nums) and price/drop<=10000,'정수 가격/판매량 또는 탐색 범위 조건 미지원')
        t=s.Symbol('t',integer=True,nonnegative=True);revenue=s.expand((price-drop*t)*(demand+growth*t));maximum=int(price//drop)
        vertex=(price*growth-drop*demand)/(2*drop*growth)
        candidates={0,maximum,max(0,min(maximum,int(s.floor(vertex)))),max(0,min(maximum,int(s.ceiling(vertex))))}
        ranked=sorted(((revenue.subs(t,n),n) for n in candidates),reverse=True)
        require(len(ranked)<2 or ranked[0][0]!=ranked[1][0],'최적 가격이 유일하지 않습니다.')
        best=ranked[0];enumerated=[revenue.subs(t,n) for n in range(maximum+1)]
        require(max(enumerated)==best[0] and enumerated.count(best[0])==1,'완전 탐색 검산 충돌')
        result=price-drop*best[1];policy='discrete-linear-demand-revenue-maximum'
        steps=[f'가격을 내리는 횟수를 음이 아닌 정수 $t$라 하면 하루 판매액은 {latex(revenue)}입니다.',
            f'위로 볼록한 이차함수이므로 꼭짓점 {latex(s.Eq(t,vertex))} 주변의 정수와 양 끝값을 비교합니다.',
            f'최대 판매액은 {latex(best[0])}원이고, 이때 가격은 {latex(result)}원입니다.',
            f'가격이 음수가 되지 않는 모든 경우 $0\\leq t\\leq {maximum}$도 완전 탐색하여 같은 유일한 최댓값을 확인했습니다.']
        checks=['positive integer demand parameters','nonnegative price domain','concave quadratic vertex','integer boundaries','exhaustive enumeration','unique maximum']
    elif prose=='복소수@0에대하여@1의값을구하시오.(단,@2,@3는@4의켤레복소수)':
        parts=formula[0].split('=');require(len(parts)==2 and parts[0].strip()=='z','복소수 정의 확인 필요')
        value=expr(parts[1]);require(not value.free_symbols and value!=0,'분모가 0이거나 미정 변수입니다.')
        strip=lambda t:re.sub(r'[\s{}]','',t)
        require(strip(formula[1])==r'\frac1z+\frac1\overlinez' and strip(formula[3])==r'\overlinez' and formula[4].strip()=='z','켤레복소수의 역수 합 표현 확인 필요')
        require(s.simplify(equation(2))==0,'허수단위 정의 확인 필요')
        result=s.simplify(1/value+1/s.conjugate(value));other=2*s.re(value)/(value*s.conjugate(value))
        require(s.simplify(result-other)==0,'켤레복소수 항등식 검산 충돌')
        policy='complex-conjugate-reciprocal-sum'
        steps=[f'켤레복소수는 {latex(s.conjugate(value))}입니다. 두 분모는 모두 0이 아닙니다.',
            f'두 분수를 통분하면 분자는 {latex(2*s.re(value))}, 분모는 {latex(s.simplify(value*s.conjugate(value)))}입니다.',
            f'따라서 값은 {latex(result)}입니다. 각각의 역수를 계산해 더한 결과와도 일치합니다.']
        checks=['nonzero denominators','conjugate definition','direct reciprocal arithmetic','independent common-denominator identity']
    if policy is None:raise ValueError('이 문항 표현에 적용할 필수 수학 검사 정책이 없습니다.')
    result=s.simplify(result)
    choices=content.get('choices',[])
    if choices:
        matches=[]
        for index,choice in enumerate(choices,1):
            c=re.sub(r'원\s*$','',choice).strip().strip('$')
            if policy=='discrete-linear-demand-revenue-maximum':c=re.sub(r'\s*,\s*','',c)
            try:
                if s.simplify(expr(c)-result)==0:matches.append(index)
            except ValueError as exc:raise ValueError('모든 보기를 해석하지 못해 객관식 정답의 유일성을 검증할 수 없습니다.') from exc
        require(len(matches)==1,'계산 답과 동치인 객관식 보기가 정확히 1개가 아닙니다.')
        answer=str(matches[0]);steps.append(f'보기와 대조하면 정답은 {answer}번입니다.')
    else:
        require(not result.free_symbols,'단답의 변수가 결정되지 않았습니다.');answer=s.sstr(result)
    return {'answer':answer,'answer_is_choice':bool(choices),'solution':steps,'computed':result,
        'spec':{'kind':'exam-algebra','policy':policy,**details},
        'evidence':{'policy':policy,'checks':checks+(['unique equivalent choice'] if choices else []),
                    'computed_value':s.sstr(result),'answer':answer,'source_prose_pattern':prose}}


def polynomial_variant(content,kind,seed):
    import random
    original=solve_exam(content);spec=original['spec']
    if spec['policy']!='polynomial-linear-combination':raise ValueError('이 대수 유형의 오프라인 변형 정책이 없습니다.')
    rng=random.Random(seed);x,y,A,B,C=s.symbols('x y A B C',real=True)
    defs=spec['definitions'];target=spec['target']
    u,v=defs[A],defs[B]
    if kind=='numeric':
        offset=rng.choice([-3,-2,-1,1,2,3]);u=s.expand(u+offset*x*x);v=s.expand(v-offset*y*y)
        correct=s.expand(target.subs({A:u,B:v}))
        text=f'두 다항식 $A,B$에 대하여 $A={s.latex(u)}, B={s.latex(v)}$일 때,${s.latex(target)}$를 계산하면?'
        changes='A, B의 수치 계수를 변경하고 동일한 다항식 연산을 다시 계산'
        objective='동류항과 계수 계산 구조를 유지하는 연습'
    else:
        text=f'두 다항식 $A,C$에 대하여 $A={s.latex(u)}, C={s.latex(original["computed"])}$이고 $C={s.latex(target)}$일 때, 다항식 $B$를 구하시오.'
        correct=v;changes='다항식 연산의 결과를 주고 원래 다항식 B를 구하는 역방향 조건으로 변경';objective='다항식 관계식을 역으로 풀어 동류항 구조 이해'
    options=[correct,s.expand(correct+x),s.expand(correct-x),s.expand(correct+y),s.expand(correct-y)]
    rng.shuffle(options)
    return {'text':text,'choices':['$'+s.latex(v)+'$' for v in options],'changes':changes,'objective':objective}


def polynomial_relation(parent,child,kind):
    try:
        p,q=solve_exam(parent),solve_exam(child)
        ps,qs=p['spec'],q['spec'];A,B,C=s.symbols('A B C',real=True)
        if ps['policy']!='polynomial-linear-combination':return False
        if kind=='numeric' and qs['policy']=='polynomial-linear-combination':
            return ps['target']==qs['target'] and ps['definitions']!=qs['definitions']
        if kind=='thinking' and qs['policy']=='inverse-polynomial-linear-combination':
            return (qs['definitions'][A]==ps['definitions'][A] and qs['definitions'][C]==p['computed']
                and s.expand(qs['relation'].subs({A:ps['definitions'][A],B:ps['definitions'][B],C:p['computed']}))==0)
    except (ValueError,KeyError,TypeError,s.PolynomialError):pass
    return False
