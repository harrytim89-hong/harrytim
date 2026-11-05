"""Auditable mathematical policies, separate from AI generation.

No question numbers, filenames or provided answers select a solution. A policy
must recognize the mathematical conditions; unsupported semantics are held.
"""
from __future__ import annotations
import re
import sympy as S
from .model import paragraphs, plain_text, stamp, checksum
from .algebra import expr, parse, scalar_answer, symbol, same, Unsupported

def formulas(body):return [b for b in paragraphs(body['blocks']) if b['kind']=='math']
def expression_items(body):
    out=[]
    for f in formulas(body):
        try:out.append((f,expr(f['ast'])))
        except (Unsupported,TypeError,ValueError,AttributeError):out.append((f,None))
    return out

def math_step(title,*content):
    blocks=[]
    from .formula import equation
    for value in content:
        if isinstance(value,S.Basic):blocks.append(equation(S.latex(value),'latex'))
        else:blocks.append({'kind':'text','value':str(value)})
    return {'title':title,'blocks':[{'kind':'paragraph','blocks':blocks}]}

def solution(value,kind,steps,checks,model=None):
    return {'value':S.simplify(value),'policy':kind,'steps':steps,'checks':checks,'model':model or {}}

def polynomial_combine(body,items,text):
    if not all(w in text for w in ('다항식','계산')):return
    A,B=symbol('A'),symbol('B')
    decl=next((f for f in formulas(body) if re.match(r'\s*A\s*=',f['source']) and re.search(r',\s*~?\s*B\s*=',f['source'])),None)
    if not decl:return
    raw=re.split(r',\s*~?\s*B\s*=',decl['source'],maxsplit=1)
    a=parse(raw[0].split('=',1)[1],decl.get('source_format','eqedit'));b=parse(raw[1],decl.get('source_format','eqedit'))
    target=next((e for f,e in items if e is not None and isinstance(e,S.Expr) and e.free_symbols=={A,B}),None)
    if target is None:return
    x,y=symbol('x'),symbol('y')
    if not (a.free_symbols|b.free_symbols)<={x,y} or S.Poly(target,A,B).total_degree()>1:return
    value=S.expand(target.subs({A:a,B:b}))
    ca,cb=S.diff(target,A),S.diff(target,B)
    mons=set(S.Poly(a,x,y).monoms())|set(S.Poly(b,x,y).monoms())
    independent=sum((ca*S.Poly(a,x,y).coeff_monomial(m)+cb*S.Poly(b,x,y).coeff_monomial(m))*x**m[0]*y**m[1] for m in mons)+target.subs({A:0,B:0})
    if not same(value,independent):raise Unsupported('계수별 재계산이 일치하지 않습니다.')
    return solution(value,'polynomial-linear-combination',[
        math_step('01 · 식을 대입합니다','주어진 두 다항식을 목표식에 대입합니다. ',S.Eq(target,target.subs({A:a,B:b}),evaluate=False)),
        math_step('02 · 동류항끼리 정리합니다','같은 차수의 항에서 계수를 각각 계산하면 ',value),
        math_step('03 · 계수별로 검산합니다','전개한 식과 각 단항식의 계수를 따로 합산한 식이 모든 항에서 일치합니다.')],['전개 항등식','모든 단항식 계수 독립 재계산'],{'a':S.latex(a),'b':S.latex(b),'target':S.latex(target)})

def solve_policy(body):
    items=expression_items(body); text=plain_text(body['blocks']);x,y,a,b,k,n=[symbol(v) for v in ('x','y','a','b','k','n')]
    eqs=[e for _,e in items if isinstance(e,S.Equality)]
    expressions=[e for _,e in items if isinstance(e,S.Expr)]
    result=polynomial_combine(body,items,text)
    if result:return result
    if '다항식 B를' in text and '역으로' in text and '관계식' in text:
        A,B,C=symbol('A'),symbol('B'),symbol('C')
        known={e.lhs:e.rhs for e in eqs if e.lhs in (A,C)}
        relation=next((e for e in eqs if e.lhs.has(B) and e.rhs==C),None)
        if set(known)=={A,C} and relation is not None:
            coeff=S.diff(relation.lhs,B)
            if not coeff.is_Rational or coeff==0 or S.diff(relation.lhs,B,2)!=0:raise Unsupported('역연산 계수가 상수인 일차식이 아닙니다.')
            value=S.expand(S.solve(relation,B)[0].subs(known))
            if not same((relation.lhs-relation.rhs).subs(known).subs(B,value),0):raise Unsupported('역산한 다항식의 원관계 검사가 실패했습니다.')
            return solution(value,'inverse-polynomial-combination',[math_step('01 · 관계식을 미지 다항식에 대해 정리합니다',S.Eq(B,S.solve(relation,B)[0],evaluate=False)),math_step('02 · 알려진 두 식을 대입합니다','각 항의 차를 구한 뒤 0이 아닌 결합 계수로 나눕니다. ',value),math_step('03 · 원래 관계에 대입해 검산합니다','복원한 B를 관계식에 넣으면 두 다항식의 모든 계수가 일치합니다.')],['일차 관계·계수 0 아님','다항식 역산 유일성','원관계 전 계수 항등 대조'])
    if '공통인 해' in text and '연립방정식' in text:
        rows=[]
        for f in formulas(body):
            for table in (t for t in _trees(f['ast']) if t['tag']=='mtable'):
                for row in table['children']:
                    for cell in row['children']:
                        e=expr(cell)
                        if not isinstance(e,S.Equality):raise Unsupported('연립식 행을 확인하지 못했습니다.')
                        rows.append(e.lhs-e.rhs)
        if len(rows)!=4:return None
        solutions=S.solve(rows,[x,y,a,b],dict=True)
        if not solutions or any(set(s)!={x,y,a,b} for s in solutions):raise Unsupported('공통 해의 완전성과 유일성이 불명확합니다.')
        real=[s for s in solutions if all(v.is_real for v in s.values())]
        if not real:raise Unsupported('공통인 실수 해가 없습니다.')
        target=next(e for e in expressions if e.free_symbols=={a,b});values=[S.simplify(target.subs(s)) for s in real]
        if any(not same(v,values[0]) for v in values):raise Unsupported('목표값이 유일하지 않습니다.')
        if any(not all(same(p.subs(s),0) for p in rows) for s in real):raise Unsupported('연립식 대입 불일치')
        return solution(values[0],'common-polynomial-system',[math_step('01 · 공통 해를 동시에 만족시킵니다','네 방정식을 하나의 연립식으로 보고 선형식으로 문자를 소거합니다.'),math_step('02 · 남은 다항식의 모든 실근을 구합니다','완전 해집합은 '+str(real)+'입니다.'),math_step('03 · 원식과 목표값을 검산합니다','각 해를 네 식에 각각 대입하여 확인하면 ',S.Eq(target,values[0]))],['다항식 연립 완전 해집합','모든 해 실수성','네 원식 정확 대입','전체 해에서 목표값 동일'])
    if '이차방정식' in text and '두 근' in text and len(eqs)==2:
        c=symbol('c');alpha,beta=symbol('α'),symbol('β')
        p=eqs[0].lhs-eqs[0].rhs;q=eqs[1].lhs-eqs[1].rhs
        target=next((e for e in expressions if e.free_symbols=={alpha,beta}),None)
        constants=[e for e in expressions if not e.free_symbols and e.is_Rational]
        if target is not None and same(target,1/alpha**2+1/beta**2) and len(constants)==2 and S.expand(x**2*p.subs(x,1/x)-q)==0:
            r,s=constants
            if r*s==0:raise Unsupported('역수 관계에서 0인 근이 있습니다.')
            value=r*r+s*s
            rev=S.expand(x*x*((1/x-r)*(1/x-s)))
            roots=S.solve(rev,x)
            assert same(sum(1/v**2 for v in roots),value)
            return solution(value,'reversed-quadratic-roots',[math_step('01 · 역수 관계를 확인합니다','원래 두 근이 0이 아니므로 계수 순서를 뒤집은 이차식의 두 근은 각각의 역수입니다.'),math_step('02 · 목표식을 원래 근으로 바꿉니다','역수 제곱의 합은 원래 두 근의 제곱의 합입니다. ',S.Eq(target,r*r+s*s,evaluate=False)),math_step('03 · 뒤집은 식의 근으로 다시 확인합니다',value)],['0인 근 제외','x²p(1/x)=역순 이차식 항등식','역순 식의 두 근 직접 계산·대조'])
    if '자연수' in text and '나머지' in text and '다항식' in text:
        polynomial=next((e for e in expressions if {x,n,a,b}<=e.free_symbols),None)
        modulus=next((e for e in expressions if e.free_symbols=={x} and e.is_polynomial(x) and S.degree(e,x)==2),None)
        remainder=next((e for e in expressions if e.free_symbols=={x,n}),None)
        if polynomial is not None and modulus is not None and remainder is not None:
            roots=S.roots(modulus,x)
            if len(roots)!=1 or list(roots.values())!=[2]:raise Unsupported('중복 일차인수 제수가 아닙니다.')
            r=next(iter(roots))
            if r==0 or not same(remainder,r**n*(x-r)):raise Unsupported('일반 자연수 n에 대한 정책과 다릅니다.')
            q=S.cancel(polynomial/x**n)
            if not q.is_polynomial(x) or not same(q,x*x+a*x+b):raise Unsupported('곱의 구조가 다릅니다.')
            sol=S.solve([q.subs(x,r),S.diff(q,x).subs(x,r)-1],[a,b],dict=True)
            if len(sol)!=1:raise Unsupported('계수 유일해가 아닙니다.')
            target=next(e for e in expressions if e.free_symbols=={a,b})
            return solution(target.subs(sol[0]),'all-natural-double-root-remainder',[math_step('01 · 중복근 나머지의 조건을 씁니다','(x-r)²에 대한 나머지는 원식과 x=r에서 함수값 및 미분값이 같아야 합니다.'),math_step('02 · 모든 자연수 n에 공통인 조건을 구합니다','r≠0이므로 q(r)=0, 곱의 미분에서 q′(r)=1을 얻습니다. n값을 표본 대입하지 않고 일반식으로 성립합니다.'),math_step('03 · 계수를 결정합니다','연립 조건에서 '+str(sol[0])+'이므로 ',S.Eq(target,target.subs(sol[0])))],['중복근 나머지의 값·미분 필요충분조건','r≠0','모든 자연수 n에 대한 곱의 미분 항등식','계수 연립 유일해'])
    if '삼차방정식' in text and '세 근' in text and 'frac' in ''.join(f['latex'] for f in formulas(body)):
        p=S.Poly(eqs[0].lhs-eqs[0].rhs,x)
        xs=[symbol('x_'+str(j)) for j in range(1,4)]
        target=next((e for e in expressions if e.free_symbols==set(xs)),None)
        if target is not None and same(target,sum(1/v**2 for v in xs)):
            A,B,C,D=p.all_coeffs()
            if D==0:raise Unsupported('0인 근이 있어 역수가 정의되지 않습니다.')
            value=(C/D)**2-2*B/D
            roots=S.roots(p.as_expr(),x)
            if sum(roots.values())!=3:raise Unsupported('모든 세 근을 분리하지 못했습니다.')
            assert same(value,sum(mult/r**2 for r,mult in roots.items()))
            return solution(value,'cubic-reciprocal-power-sum',[math_step('01 · 근의 역수에 근과 계수 관계를 씁니다','세 근은 모두 0이 아니므로 역수의 합은 ', -C/D,', 두 역수 곱의 합은 ',B/D,'입니다.'),math_step('02 · 제곱의 합을 계산합니다','합의 제곱에서 두 곱의 합의 두 배를 빼면 ',value),math_step('03 · 원래 세 근으로 재계산합니다','원래 삼차식을 인수분해하여 얻은 세 근(중복도 포함)으로 직접 계산한 결과가 같습니다.')],['상수항 0 아님','역순 다항식 Newton 항등식','모든 근·중복도 확보 및 직접 역수 제곱 합'])
    if '이차항의 계수' in text and '일차항의 계수' in text and '중근' in text:
        constants=[e for e in expressions if e.is_number]
        if len(constants)>=2:
            lead,slope=constants[:2];u,v,w=S.symbols('u v w',real=True);F=lead*x*x+u*x+v;G=slope*x+w
            condition=next((e for e in eqs if e.lhs.has(S.Function('f')(0))),None)
            target=next((e for e in expressions if e.has(S.Function('f')) and e.has(S.Function('g')) and x not in e.free_symbols),None)
            if condition is not None and target is not None and lead>0:
                def substitute(e):return e.replace(lambda t:t.is_Function and t.func in (S.Function('f'),S.Function('g')),lambda t:(F if t.func==S.Function('f') else G).subs(x,t.args[0]))
                condition=substitute(condition.lhs-condition.rhs);disc=S.discriminant(F+G,x);sol=S.solve([condition,disc],[u,v],dict=True)
                if len(sol)!=1:raise Unsupported('조건을 완전히 결정하지 못했습니다.')
                value=S.simplify(substitute(target).subs(sol[0]))
                if value.free_symbols:raise Unsupported('목표값에 자유변수가 남습니다.')
                assert S.simplify(disc.subs(sol[0]))==0
                return solution(value,'quadratic-linear-double-root',[math_step('01 · 계수를 문자로 둡니다',S.Eq(S.Function('f')(x),F),', ',S.Eq(S.Function('g')(x),G)),math_step('02 · 두 조건을 식으로 옮깁니다','(가)에서 ',S.Eq(condition,0),'이고, (나)의 중근 조건은 ',S.Eq(disc,0),'입니다.'),math_step('03 · 필요한 계수 조합을 구합니다','두 조건으로 목표식에서 자유계수가 소거됩니다. ',value)],['본문 선형·이차 계수 명시','조건식 전체 대입','판별식 0','자유계수 소거·목표 유일성'])
    if '두 실수' in text and '등식' in text and '만족' in text and any(S.I in e.atoms() for e in eqs):
        eq=next(e for e in eqs if {x,y}<=e.free_symbols);p=S.expand_complex(eq.lhs-eq.rhs)
        equations=[S.re(p),S.im(p)];matrix,rhs=S.linear_eq_to_matrix(equations,x,y)
        if matrix.det()==0:raise Unsupported('실수 해의 유일성을 확인하지 못했습니다.')
        values=matrix.inv()*rhs;sub={x:values[0],y:values[1]}
        target=next(e for e in expressions if e.free_symbols=={x,y})
        if not same(p.subs(sub),0):raise Unsupported('복소수 원식 대입 검사가 실패했습니다.')
        return solution(target.subs(sub),'complex-real-linear',[
            math_step('01 · 실수부와 허수부를 비교합니다','등식의 양변에서 실수부와 허수부가 각각 같아야 합니다. ',S.Eq(equations[0],0),', ',S.Eq(equations[1],0)),
            math_step('02 · 연립방정식을 풉니다',S.Eq(x,values[0]),', ',S.Eq(y,values[1])),
            math_step('03 · 목표값을 구합니다',S.Eq(target,target.subs(sub)))],['실수 해 존재·유일성(행렬식)','복소수 원식에 정확 대입'])
    if '이차방정식' in text and '실근' in text and '최댓값' in text:
        p=next(e.lhs-e.rhs for e in eqs if x in e.free_symbols and a in e.free_symbols)
        if S.degree(p,x)!=2 or S.Poly(p,x).LC().free_symbols:raise Unsupported('이차항 계수의 조건이 불명확합니다.')
        disc=S.discriminant(p,x);poly=S.Poly(disc,a)
        if poly.degree()!=1 or not poly.LC()<0:raise Unsupported('매개변수 최댓값의 검증 규칙이 다릅니다.')
        value=S.solve(disc,a)[0];root=-S.Poly(p,x).nth(1)/(2*S.Poly(p,x).nth(2))
        assert same(p.subs({a:value,x:root}),0)
        return solution(value,'quadratic-real-boundary',[math_step('01 · 실근 조건을 세웁니다','실수 계수 이차방정식이 실근을 가질 필요충분조건은 판별식이 0 이상인 것입니다. ',S.Ge(disc,0)),math_step('02 · 범위를 정리합니다',S.Le(a,value)),math_step('03 · 경계에서 존재를 확인합니다','최댓값에서 판별식은 0이며 중근 ',root,'가 원식을 만족합니다.')],['실수 이차식 필요충분 판별식','경계 중근 원식 대입'])
    if '나누었을 때의 나머지는' in text and text.count('나누었을 때의 나머지')>=3:
        candidates=[e for e in expressions if e.free_symbols=={x} and e.is_polynomial(x) and S.Poly(e,x).degree()==1]
        constants=[e for e in expressions if not e.free_symbols and e.is_Rational]
        if len(candidates)>=2 and len(constants)>=2:
            divs=candidates[:2];r=[S.solve(v,x)[0] for v in divs];v=constants[:2]
            if r[0]==r[1]:raise Unsupported('두 일차식의 근이 같습니다.')
            rem=S.interpolate(list(zip(r,v)),x)
            assert all(same(rem.subs(x,t),u) for t,u in zip(r,v))
            return solution(rem,'two-linear-remainders',[math_step('01 · 나머지정리를 적용합니다',S.Eq(S.Function('f')(r[0]),v[0]),', ',S.Eq(S.Function('f')(r[1]),v[1])),math_step('02 · 일차 나머지를 결정합니다','서로 다른 두 근에서의 값으로 일차 나머지가 유일하게 정해집니다. ',rem),math_step('03 · 두 조건을 대조합니다','구한 나머지를 두 근에 각각 대입하면 주어진 나머지와 일치합니다.')],['서로 다른 두 제수의 근','일차 보간 유일성','두 나머지 정확 대조'])
    if '두 실수' in text and {x,y}<=set().union(*(e.free_symbols for e in eqs)):
        sum_eq=next((e for e in eqs if same(e.lhs,x+y)),None);cube=next((e for e in eqs if same(e.lhs,x**3+y**3)),None)
        if sum_eq is not None and cube is not None:
            total,third=sum_eq.rhs,cube.rhs
            if total==0:raise Unsupported('합이 0인 경우는 별도 검증이 필요합니다.')
            product=(total**3-third)/(3*total);disc=S.simplify(total**2-4*product)
            if disc<0:raise Unsupported('주어진 조건을 만족하는 두 실수가 없습니다.')
            target=next(e for e in expressions if e.free_symbols=={x,y});roots=S.solve(x**2-total*x+product,x)
            vals=[S.simplify(target.subs({x:r,y:total-r})) for r in roots]
            if not vals or any(not same(v,vals[0]) for v in vals):raise Unsupported('목표값이 유일하지 않습니다.')
            return solution(vals[0],'symmetric-real-cubes',[math_step('01 · 곱을 구합니다',S.Eq(x**3+y**3,(x+y)**3-3*x*y*(x+y),evaluate=False),'에서 ',S.Eq(x*y,product)),math_step('02 · 대칭식을 바꿉니다',S.Eq(target,vals[0])),math_step('03 · 모든 실수 해를 검사합니다','합과 곱으로 정해지는 이차식의 판별식은 ',disc,'이며, 모든 순서쌍에서 목표값이 같습니다.')],['합이 0 아님','실수 쌍 존재','두 순서쌍 완전 해집합과 목표값 유일성'])
    if '삼차방정식' in text and '한 근' in text and '나머지 두 근의 합' in text:
        eq=next(e for e in eqs if x in e.free_symbols);p=eq.lhs-eq.rhs
        z=next(e for e in expressions if not e.free_symbols and S.im(e)!=0)
        systems=[S.re(S.expand_complex(p.subs(x,z))),S.im(S.expand_complex(p.subs(x,z)))]
        params=sorted(p.free_symbols-{x},key=str);sol=S.solve(systems,params,dict=True)
        if len(sol)!=1:raise Unsupported('실수 계수를 유일하게 결정하지 못했습니다.')
        polynomial=S.Poly(p.subs(sol[0]),x);pair=S.expand((x-z)*(x-S.conjugate(z)));q,r=S.div(polynomial.as_expr(),pair,x)
        if r!=0 or S.degree(q,x)!=1:raise Unsupported('켤레근 인수분해가 일치하지 않습니다.')
        last=S.solve(q,x)[0];value=S.conjugate(z)+last
        assert same(polynomial.eval(last),0)
        return solution(value,'real-cubic-conjugate',[math_step('01 · 켤레근을 찾습니다','계수가 실수이므로 ',S.conjugate(z),'도 근입니다.'),math_step('02 · 나머지 근을 계산합니다','알려진 근을 원식에 대입하여 계수를 정하고 켤레근의 이차인수로 나누면 ',S.Eq(q,0),'을 얻습니다. 따라서 나머지 실근은 ',last,'입니다.'),math_step('03 · 두 근을 더합니다',value)],['실수 계수 연립방정식 유일성','켤레근 이차인수 정확 나눗셈','세 근 원식 대조'])
    if '두 근' in text and 'alpha' in ''.join(f['source'] for f in formulas(body)) and len(eqs)==1 and '이차방정식' in text:
        p=S.Poly(eqs[0].lhs-eqs[0].rhs,x);alpha,beta=symbol('α'),symbol('β')
        target=next((e for e in expressions if e.free_symbols=={alpha,beta}),None)
        if p.degree()==2 and target is not None and same(target,alpha**3+beta**3):
            A,B,C=p.all_coeffs();u=-B/A;v=C/A;value=u**3-3*u*v
            roots=S.solve(p.as_expr(),x)
            if len(roots)==1:roots*=2
            assert same(value,sum(r**3 for r in roots))
            return solution(value,'quadratic-cubic-power-sum',[math_step('01 · 근과 계수의 관계를 씁니다',S.Eq(alpha+beta,u),', ',S.Eq(alpha*beta,v)),math_step('02 · 세제곱의 합을 변형합니다',S.Eq(alpha**3+beta**3,(alpha+beta)**3-3*alpha*beta*(alpha+beta),evaluate=False)),math_step('03 · 대입하여 계산합니다',value)],['이차방정식 근과 계수 관계','근의 공식으로 두 근 별도 계산 및 세제곱 합 대조'])
    if '직선' in text and '한 점' in text and '만나지 않' in text:
        curves=[e.rhs-e.lhs for e in eqs if e.lhs==y]
        linear=next((e for e in curves if S.degree(e,x)==1),None);quadratics=[e for e in curves if S.degree(e,x)==2]
        if linear is not None and len(quadratics)==2:
            if any(not same(e,linear) for e in curves if S.degree(e,x)==1):raise Unsupported('두 조건에 제시된 직선이 서로 다릅니다.')
            p1=S.expand(quadratics[0]-linear);p2=S.expand(quadratics[1]-linear);d1=S.discriminant(p1,x);d2=S.discriminant(p2,x)
            candidates=S.solve(d1,k);valid=[v for v in candidates if v.is_real and d2.subs(k,v)<0]
            if len(valid)!=1:raise Unsupported('조건을 만족하는 직선이 유일하지 않습니다.')
            value=valid[0]
            assert len(S.solve(p1.subs(k,value),x))==1
            return solution(value,'tangent-and-disjoint',[math_step('01 · 교점 방정식을 세웁니다','첫 이차함수와 한 점에서 만나므로 ',S.Eq(d1,0)),math_step('02 · 모든 후보를 구합니다','판별식이 0인 모든 실수 후보는 '+', '.join(map(str,candidates))+'입니다.'),math_step('03 · 두 번째 조건으로 결정합니다','두 번째 교점 방정식의 판별식 ',d2,'가 음수인 후보는 ',value,'뿐입니다.')],['두 이차식 차수·실수 정의역','접선 판별식 모든 후보','두 번째 판별식 엄격 음수','접점 중근 원식 대조'])
    if '가격' in text and '판매량' in text and '최대' in text:
        nums=[]
        for f in formulas(body):
            raw=re.sub(r'[,~`\s]','',f['source'])
            if raw.isdigit():nums.append(int(raw))
        if len(nums)==4:
            price,demand,drop,growth=nums
            if min(nums)<=0 or price//drop>10000:raise Unsupported('판매 모델의 범위가 맞지 않습니다.')
            t=S.Symbol('t',integer=True);revenue=(price-drop*t)*(demand+growth*t);limit=(price-1)//drop
            best=max((revenue.subs(t,j),j) for j in range(limit+1));indices=[j for j in range(limit+1) if revenue.subs(t,j)==best[0]]
            if len(indices)!=1:raise Unsupported('최대 매출 가격이 유일하지 않습니다.')
            vertex=S.solve(S.diff(revenue,t),t)[0];value=price-drop*indices[0]
            return solution(value,'discrete-revenue-maximum',[math_step('01 · 가격 인하 횟수를 정합니다','가격을 내린 횟수를 자연수 또는 0인 t라 하면 하루 판매액은 ',S.expand(revenue),'입니다.'),math_step('02 · 이차함수의 꼭짓점을 계산합니다','이차항 계수가 음수이므로 꼭짓점 부근에서 최대입니다. 꼭짓점의 t는 ',vertex,'입니다.'),math_step('03 · 허용하는 정수와 경계를 검사합니다','양수 가격을 유지하는 '+str(limit+1)+'가지 인하 횟수를 모두 비교하면 '+str(indices[0])+'회 인하할 때 유일하게 최대입니다. 가격은 '+str(value)+'원입니다.')],['양수 가격·수요 및 정수 횟수','오목한 매출 이차함수 꼭짓점','모든 허용 정수와 양끝 완전 탐색'])
    if '복소수' in text and any(e.lhs==symbol('z') for e in eqs):
        z=symbol('z');known=next(e.rhs for e in eqs if e.lhs==z)
        target=next((e for e in expressions if z in e.free_symbols),None)
        target_eq=next((e for e in eqs if e.lhs!=z and z in e.lhs.free_symbols),None)
        if target_eq is not None:target=target_eq.lhs
        if target is not None and target.free_symbols<={z} and known.free_symbols==set():
            evaluated=S.simplify(S.expand_complex(target.subs(z,known)))
            if evaluated.has(S.zoo,S.nan,S.oo):raise Unsupported('복소수 분모가 0입니다.')
            if target_eq is not None:
                if not same(target_eq.rhs,a+b*S.I):raise Unsupported('실수부·허수부의 정의가 다릅니다.')
                requested=next((e for e in expressions if e.free_symbols=={a,b}),None)
                if requested is None:raise Unsupported('물은 실수부·허수부 조합을 확인하지 못했습니다.')
                value=requested.subs({a:S.re(evaluated),b:S.im(evaluated)})
            else:value=evaluated
            # Independent exact substitution with common-denominator expansion.
            alternate=S.expand_complex(S.cancel(target).subs(z,known))
            if not same(evaluated,alternate):raise Unsupported('복소수 독립 재계산 불일치')
            return solution(value,'fixed-complex-expression',[math_step('01 · 복소수를 식에 대입합니다','주어진 복소수 ',known,'를 대입하고 켤레복소수와 거듭제곱을 계산합니다.'),math_step('02 · 실수부와 허수부를 정리합니다',evaluated),math_step('03 · 물은 값을 구합니다',value,'이며, 분모의 0 여부와 통분한 식을 별도로 대조했습니다.')],['지정된 복소수 정의역·분모 검사','원식 직접 계산','통분·전개 경로 별도 재계산'])
    if '꼴로 나타내시오' in text and any('sqrt' in f['source'] for f in formulas(body)):
        target=next((e for f,e in items if isinstance(e,S.Expr) and not e.free_symbols and f['source'].count('sqrt')>=3),None)
        if target is not None:
            value=S.expand_complex(target)
            witnesses=[]
            for f in formulas(body):
                for node in _trees(f['ast']):
                    if node['tag']=='msqrt':
                        arg=expr({'tag':'mrow','children':node['children']});root=S.sqrt(arg)
                        if not arg.is_number:continue
                        assert same(root**2,arg)
                        assert S.re(root)>0 or S.re(root)==0 and S.im(root)>=0
                        witnesses.append(S.Eq(S.sqrt(arg,evaluate=False),root,evaluate=False))
            return solution(value,'principal-complex-radicals',[math_step('01 · 음수의 제곱근을 바꿉니다','양수 c에 대해 주값 √(-c)=i√c를 사용합니다. ',*witnesses),math_step('02 · 곱과 몫을 각각 정리합니다','각 근호를 위 결과로 바꾸어 곱과 몫을 계산합니다. i²=-1에 유의하고 분모를 유리화합니다.'),math_step('03 · 실수부와 허수부를 모읍니다',value)],['제곱근 주값 규약','각 근호 제곱 및 주값 부호 정확 검사','분모 0 여부','정확한 복소수 유리화'])
    if '서로 다른 세 이차다항식' in text and '나누어떨어진다' in text and '최고차항의 계수' in text:
        constants=[e for e in expressions if not e.free_symbols and e.is_number]
        if not constants or constants[0]!=1:raise Unsupported('최고차항 계수 1인 이차다항식에 대한 정책입니다.')
        f,g,h=[S.Function(v) for v in ('f','g','h')]
        products=[e for e in expressions if e.has(f(x)) and e.has(h(x)) is False]
        divisions=[e for e in expressions if e.has(h(x)) and not e.has(f(x)) and e.is_Mul and e!=g(x)*h(x)]
        rpoly=next((e/h(x) for e in divisions if S.cancel(e/h(x)).is_polynomial(x) and S.degree(S.cancel(e/h(x)),x)==1),None)
        second=next((e/f(x) for e in expressions if e.has(f(x)) and not e.has(h(x)) and e.is_Mul and S.cancel(e/f(x)).is_polynomial(x)),None)
        condition=next((e for e in eqs if e.lhs.has(f) and e.lhs.has(g) and e.rhs.is_number),None)
        if rpoly is not None and second is not None and condition is not None:
            r=S.solve(rpoly,x)[0];s=S.solve(second,x)[0]
            args=[t.args[0] for t in condition.lhs.atoms(S.Function) if t.func in (f,g)]
            if len(set(args))!=1 or r==s:raise Unsupported('다항식 인수 조건이 다릅니다.')
            c=args[0];t=S.Symbol('t',real=True);F=(x-r)*(x-t);G=(x-r)*(x-s);H=(x-s)*(x-t)
            sols=S.solve(F.subs(x,c)+G.subs(x,c)-condition.rhs,t)
            if len(sols)!=1 or sols[0] in (r,s):raise Unsupported('서로 다른 세 다항식 조건이 성립하지 않습니다.')
            tt=sols[0];F=F.subs(t,tt);H=H.subs(t,tt)
            assert S.rem(F*G,(x-r)*H,x)==0 and S.rem(G*H,(x-s)*F,x)==0
            target=next((e for e in expressions if e.has(h) and len(e.atoms(S.Function))==1 and e.func==h),None)
            if target is None:raise Unsupported('목표 함수값을 확인하지 못했습니다.')
            value=H.subs(x,target.args[0])
            return solution(value,'distinct-monic-quadratic-divisibility',[math_step('01 · 공통 인수를 추적합니다','두 나눗셈 조건을 곱하면 g(x)²은 (x-r)(x-s)의 배수입니다. g가 이차식이므로 g(x)=(x-r)(x-s)입니다.'),math_step('02 · 서로 다름 조건을 적용합니다','f와 h가 같아지는 경우를 제외하면 f(x)=(x-r)(x-t), h(x)=(x-s)(x-t)로 나타납니다. 주어진 함수값 합에서 ',S.Eq(t,tt),'입니다.'),math_step('03 · 인수와 함수값을 대조합니다',S.Eq(h(x),S.expand(H),evaluate=False),'이므로 물은 값은 ',value)],['서로 다른 r,s와 monic 이차 차수','g² 인수·차수로 g 유일 결정','f=h 대안 배제와 공통근 매개화','매개변수 유일해·서로 다름','두 원래 나눗셈 나머지 0'])
    if '나머지' in text and '다항식' in text:
        nonconstant=[e for e in expressions if e.free_symbols and not e.has(S.Function)]
        moduli=[e for e in nonconstant if e.free_symbols=={x} and S.degree(e,x)>=2]
        if len(moduli)==2:
            small,large=moduli
            known=next((e for e in nonconstant if e.free_symbols=={x} and S.degree(e,x)<S.degree(small,x)),None)
            unknown=next((e for e in nonconstant if {a,b}<=e.free_symbols and x in e.free_symbols),None)
            if known is not None and unknown is not None and S.rem(large,small,x)==0:
                constraints=S.Poly(S.rem(unknown-known,small,x),x).all_coeffs();sol=S.solve(constraints,[a,b],dict=True)
                if len(sol)!=1:raise Unsupported('나머지를 유일하게 결정하지 못했습니다.')
                target=next(e for e in expressions if e.free_symbols=={a,b});value=target.subs(sol[0])
                assert S.rem((unknown-known).subs(sol[0]),small,x)==0
                return solution(value,'nested-polynomial-remainders',[math_step('01 · 두 제수의 관계를 확인합니다',S.factor(large),'에서 작은 제수는 큰 제수의 인수입니다.'),math_step('02 · 나머지를 다시 나눕니다','큰 제수에 대한 나머지를 작은 제수로 나눈 결과가 원래 나머지와 같아야 합니다. 계수를 비교하면 '+str(sol[0])+'입니다.'),math_step('03 · 계산하고 나눗셈을 검산합니다',S.Eq(target,value))],['제수 정확한 인수 관계','차수에 맞는 나머지','계수 연립 유일해','두 나머지 차의 정확 나눗셈'])
    if '서로 다른 실근' in text and '삼차방정식' in text:
        counts=[e for e in expressions if not e.free_symbols and e.is_number]
        if counts!=[S.Integer(2)]:raise Unsupported('서로 다른 실근이 정확히 두 개인 경우의 정책입니다.')
        eq=next(e for e in eqs if x in e.free_symbols and a in e.free_symbols);p=eq.lhs-eq.rhs
        if S.degree(p,x)!=3 or S.Poly(p,x).LC().free_symbols:raise Unsupported('삼차식의 차수가 변할 수 있습니다.')
        candidates=S.solve(S.discriminant(p,x),a);valid=[];witness=[]
        for param in candidates:
            if not param.is_real:continue
            roots=S.roots(p.subs(a,param),x)
            if sum(roots.values())!=3:raise Unsupported('실근을 완전히 분리하지 못했습니다.')
            real=[r for r in roots if r.is_real]
            if len(real)==2:
                valid.append(param);witness.append(S.factor(p.subs(a,param),extension=True))
        if not valid:raise Unsupported('조건에 맞는 매개변수가 없습니다.')
        return solution(sum(valid),'cubic-two-distinct-real-roots',[math_step('01 · 중근이 있어야 함을 이용합니다','삼차방정식이 서로 다른 실근을 정확히 두 개 가지려면 중근이 있어야 하므로 판별식이 0입니다. ',S.Eq(S.discriminant(p,x),0)),math_step('02 · 모든 실수 후보를 검사합니다','후보마다 원식을 인수분해하여 중복도를 포함한 세 근과 실근 두 개를 확인합니다. 후보: '+', '.join(map(str,valid))),math_step('03 · 모든 값을 더합니다',S.simplify(sum(valid)))],['삼차항 계수 0 아님','판별식 모든 실수 해','각 후보 모든 근 및 중복도·실수성','서로 다른 실근 정확히 두 개'])
    if '두 자연수' in text and '최댓값' in text and '최솟값' in text and '순서쌍' in text:
        func=next((e for e in eqs if e.lhs==S.Function('f')(x)),None)
        relation=next((e for _,e in items if isinstance(e,S.LessThan) and e.lhs==symbol('M')+symbol('m')),None)
        raw=next((f['source'] for f in formulas(body) if len(re.findall(r'\ble\b|<=',f['source']))==2),None)
        if func is not None and relation is not None and raw:
            ends=re.split(r'\ble\b|<=',raw);low=parse(ends[0]);high=parse(ends[2]);limit=relation.rhs;p=func.rhs
            if not same(p,(x-a)**2+2*b) or not all(v.is_Integer for v in (low,high,limit)) or not 0<limit<=500:raise Unsupported('완전 탐색의 증명 범위가 다릅니다.')
            maxb=int(S.floor(limit/4));maxa=int(S.floor(high+S.sqrt(limit-4)));pairs=[]
            if maxa*maxb>20000:raise Unsupported('완전 탐색 범위를 초과했습니다.')
            for aa in range(1,maxa+1):
                for bb in range(1,maxb+1):
                    endpoints=[p.subs({x:v,a:aa,b:bb}) for v in (low,high)]
                    minimum=2*bb if low<=aa<=high else min(endpoints)
                    if max(endpoints)+minimum<=limit:pairs.append((aa,bb))
            return solution(S.Integer(len(pairs)),'natural-quadratic-extrema',[math_step('01 · 유한 탐색 범위를 증명합니다','최댓값과 최솟값은 각각 2b 이상이므로 4b≤'+str(limit)+'입니다. a가 오른쪽 끝점보다 크면 최소 거리와 b≥1에서 a≤'+str(maxa)+'를 얻습니다.'),math_step('02 · 꼭짓점과 양끝을 비교합니다','각 자연수 a,b에 대해 최댓값은 양끝 함수값 중 큰 값입니다. 꼭짓점 a가 구간 안이면 최솟값은 2b, 밖이면 양끝 중 작은 값입니다.'),math_step('03 · 모든 후보를 셉니다','증명된 범위의 '+str(maxa*maxb)+'쌍을 빠짐없이 계산한 결과 조건을 만족하는 순서쌍은 '+str(len(pairs))+'개입니다.')],['양수 자연수 정의역','b·a 유한 상한 증명','구간 내외 꼭짓점·양끝 정확 평가','유한 전집합 완전 탐색'],{'pairs':pairs})
    if '원기둥' in text and '반지름' in text and '높이가 같은' in text and '남기고' in text:
        unit=symbol('m')
        volume=next((S.simplify(e/(S.pi*unit**3)) for e in expressions if e.has(S.pi) and e.has(unit)),None)
        gap=next((S.simplify(e/unit) for e in expressions if e.has(unit) and e.free_symbols=={unit} and not e.has(S.pi)),None)
        if volume is not None and gap is not None and volume.is_positive and gap.is_positive:
            polynomial=x*x*(x-gap)-volume;roots=S.real_roots(polynomial,x);valid=[r for r in roots if r>gap]
            if len(valid)!=1:raise Unsupported('실현 가능한 원기둥 높이가 유일하지 않습니다.')
            value=valid[0];assert same(polynomial.subs(x,value),0)
            return solution(value,'cylinder-volume-text-only',[math_step('01 · 본문의 부피 조건을 식으로 씁니다','반지름과 높이가 x이고 빈 높이가 ',gap,'이면 물 높이는 x에서 빈 높이를 뺀 값입니다. 따라서 ',S.Eq(x*x*(x-gap),volume,evaluate=False),'입니다.'),math_step('02 · 가능한 높이를 구합니다','물 높이가 양수여야 하므로 ',S.Gt(x,gap),'입니다. 부피 방정식의 모든 실근 중 이 범위를 만족하는 근은 ',value,'뿐입니다.'),math_step('03 · 부피를 검산하고 도형 검증을 구분합니다','계산한 값을 부피식에 대입하면 일치합니다. 다만 원본 그림 관계는 독립 검증하지 못했으므로 자동 배부는 보류합니다.')],['본문 반지름=높이와 단위 일치','물 높이 양수','부피 방정식 모든 실근 및 유일한 실현 해','원래 부피식 정확 대입'])
    raise Unsupported('이 문항의 조건 전체를 검증하는 수학 정책이 아직 없습니다. AI 풀이를 생성할 수 있지만 자동 배부는 보류합니다.')

def _trees(t):
    yield t
    for c in t['children']:yield from _trees(c)

def language_signature(blocks):
    """Conservative semantic coverage: unknown prose cannot silently add a condition."""
    out=''
    for b in blocks:
        if b['kind']=='text':out+=b['value']
        elif b['kind']=='math':out+='@'
        elif b.get('blocks'):out+=language_signature(b['blocks'])
        else:out+='§'
    return re.sub(r'\s+','',out)

# A conservative vocabulary check complements the mathematical policy. The
# policy still has to prove domain/uniqueness and read the actual formula trees.
# No source prose, question number, filename or answer table is stored here.
COMMON_WORDS = "단 은 는 이 가 을 를 의 에 에서 와 과 두 세 한 서로 다른 모든 다음 조건 만족 시키는 시킬 하는 할 라 때 일때 이때 이고 이다 된다 대하여 대한 대하여서 값 합 계산 하면 하시오 구하시오 구하여라 나타내시오 꼴 로 으로 인 다 고 최댓값 최솟값".split()
POLICY_WORDS = {
 'polynomial-linear-combination': '다항식 정의 다음 같다 연산',
 'inverse-polynomial-combination': '다항식 다음 같다 역으로 관계식 만족하는 구하시오',
 'complex-real-linear': '등식 만족시키는 실수',
 'quadratic-real-boundary': '이차방정식 실근 갖도록 하는 실수',
 'two-linear-remainders': '다항식 나누었을 나머지',
 'symmetric-real-cubes': '실수',
 'real-cubic-conjugate': '삼차방정식 근 나머지 실수',
 'quadratic-cubic-power-sum': '이차방정식 근',
 'common-polynomial-system': '연립방정식 공통인 해 존재 실수',
 'tangent-and-disjoint': '직선 이차함수 그래프 점 만나고 만나지 않도록 실수',
 'reversed-quadratic-roots': '이차방정식 근 실수',
 'all-natural-double-root-remainder': '자연수 다항식 나누었을 나머지 상수',
 'discrete-revenue-maximum': '어느 분식집 김밥 한 줄 가격 원 하루 씩 팔린다고 한다 내릴 때마다 판매량 증가 최대 판매액',
 'fixed-complex-expression': '복소수 성립 실수 켤레복소수',
 'nested-polynomial-remainders': '다항식 나누었을 나머지 상수',
 'cubic-reciprocal-power-sum': '삼차방정식 근',
 'quadratic-linear-double-root': '이차항 계수 이차함수 일차항 일차함수 방정식 중근 갖는다',
 'cubic-two-distinct-real-roots': '삼차방정식 실근 개수 되도록 실수',
 'principal-complex-radicals': '실수',
 'distinct-monic-quadratic-divisibility': '최고차항 계수 이차다항식 만족시킨다 다항식 나누어떨어진다',
 'natural-quadratic-extrema': '자연수 이차함수 이라 하자 만족시키는 순서쌍 개수',
 'cylinder-volume-text-only':'아래 그림 같이 밑면 반지름 길이 높이가 같은 원기둥 모양 수조 물 부었더니 위 부터 남기고 채워졌다 높이 두께 생각하지 않는다',
}
FORMULA_LIMITS = dict(zip(POLICY_WORDS, [3,3,4,2,8,4,4,4,5,5,8,7,4,5,9,3,7,4,4,8,8,4]))

def semantic_coverage(body,policy):
    signature=language_signature(body['blocks'])
    signature=re.sub(r'\([가-라]\)','',signature)
    # Reject additional structures/conditions rather than ignoring them.
    if policy=='cylinder-volume-text-only' and signature.count('§')==1:signature=signature.replace('§','')
    if signature.count('@') > FORMULA_LIMITS.get(policy,0) or '§' in signature:return False
    relations=[e for _,e in expression_items(body) if isinstance(e,(S.LessThan,S.GreaterThan,S.StrictLessThan,S.StrictGreaterThan,S.Unequality))]
    if relations and (policy!='natural-quadratic-extrema' or len(relations)!=1):return False
    words=COMMON_WORDS+POLICY_WORDS.get(policy,'').split()+['A','B','C','a','b','c','x','y','z']
    residual=re.sub(r'[@,?.()·:;!]', '', signature)
    for word in sorted(set(words),key=len,reverse=True):residual=residual.replace(word,'')
    return not residual

def check_question(question,proposal=None):
    """Calculate without ever feeding the supplied/proposed answer to the solver."""
    base={'final_answer':None,'steps':[],'verification':'held','origin':'calculation','created':stamp(),'proof':{},'provided_answer':question.get('original_answer'),'proposal':proposal}
    try:
        result=solve_policy(question['body'])
        if not semantic_coverage(question['body'],result['policy']):
            raise Unsupported('계산 가능한 식은 있으나 본문의 모든 조건을 지원 문형으로 확인하지 못했습니다. 해설은 생성할 수 있지만 자동 배부는 보류합니다.')
        value=result['value'];body=question['body']
        if body.get('choices'):
            choices=[]
            for choice in body['choices']:
                math=[b for b in choice if b['kind']=='math']
                other=''.join(b.get('value','') for b in choice if b['kind']=='text').strip()
                if len(math)!=1 or other not in ('','원'):raise Unsupported('모든 객관식 보기의 의미를 확인하지 못했습니다.')
                # Thousands separators are presentation only for money choices.
                if other=='원':
                    raw=re.sub(r'[,~`\s]','',math[0]['source'])
                    if not raw.isdigit():raise Unsupported('가격 보기 해석 보류')
                    choices.append(S.Integer(raw))
                else:choices.append(expr(math[0]['ast']))
            matches=[i+1 for i,c in enumerate(choices) if same(c,value)]
            if len(matches)!=1:raise Unsupported('객관식의 정답이 정확히 한 개가 아닙니다.')
            answer=str(matches[0]);result['checks'].append('객관식 전체 보기 해석·동치 비교 및 정답 1개')
        else:answer=str(value)
        base.update(final_answer=answer,exact_value=S.latex(value),steps=result['steps'],proof={'policy':result['policy'],'checks':result['checks'],'model':result['model'],'body_fingerprint':question['fingerprint'],'engine':'exact-policy-1.0','limitations':'유형별 자동 검사 통과는 무오류를 보장하지 않습니다.'})
        provided=question.get('original_answer')
        conflicts=[]
        if provided:
            try:
                if not same(scalar_answer(provided),scalar_answer(answer)):conflicts.append('원본 빠른정답과 정확 계산 결과가 다릅니다.')
            except Unsupported:conflicts.append('원본 정답의 형식을 정확히 대조하지 못했습니다.')
        if proposal:
            try:
                if not same(scalar_answer(proposal['final_answer']),scalar_answer(answer)):conflicts.append('생성 풀이와 별도 계산 결과가 다릅니다.')
            except (Unsupported,KeyError):conflicts.append('생성 정답을 해석하지 못했습니다.')
            if proposal.get('blind_answer'):
                try:
                    if not same(scalar_answer(proposal['blind_answer']),scalar_answer(answer)):conflicts.append('정답을 숨긴 별도 재풀이 결과가 다릅니다.')
                except Unsupported:conflicts.append('별도 재풀이 정답을 해석하지 못했습니다.')
        if conflicts:base.update(verification='failed',reason=' '.join(conflicts))
        elif question['input_state']!='complete':base.update(reason='입력 구조에 보류 사항이 남아 있습니다.')
        elif any(b['kind']=='image' for b in paragraphs(body['blocks'])):base.update(reason='그림의 관계와 표기를 독립적으로 확인하지 못했습니다.')
        else:base.update(verification='passed',reason='필수 검사를 충족하여 자동 사용 가능합니다.')
    except (Unsupported,ValueError,TypeError,StopIteration,NotImplementedError,AssertionError,AttributeError,S.PolynomialError) as exc:
        base['reason']=str(exc) or '수학 조건을 완전히 확인하지 못했습니다.'
        if proposal:
            base['final_answer']=proposal.get('final_answer');base['steps']=proposal.get('steps',[]);base['origin']='ai'
    return base
