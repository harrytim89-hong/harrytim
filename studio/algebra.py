"""A bounded, non-evaluating MathML expression reader for exact checks."""
from __future__ import annotations
import re
import sympy as S
from .formula import equation

class Unsupported(ValueError): pass

def symbol(name):
    if name=='i':return S.I
    if name=='π':return S.pi
    if name in ('f','g','h'):return S.Function(name)
    if not re.fullmatch(r'[A-Za-zαβγ][A-Za-z0-9_αβγ]*',name):raise Unsupported('검사할 수 없는 문자: '+name)
    return S.Symbol(name, real=True) if name not in ('z','α','β') else S.Symbol(name)

def tokens(t):
    tag=t['tag'];text=t.get('text','').strip();cs=t['children']
    if tag in ('math','mrow','mstyle','mtd'):return [x for c in cs for x in tokens(c)]
    if tag=='mspace':return []
    if tag=='mn':
        if not re.fullmatch(r'\d+(?:\.\d+)?',text) or len(text)>30:raise Unsupported('숫자 범위를 초과했습니다.')
        return [S.Rational(text)]
    if tag=='mi':
        if text in ('sin','cos','log','ln','lim','max','min'):raise Unsupported('이 함수의 검증 규칙이 없습니다.')
        return [symbol(c) for c in text]
    if tag=='mo':
        text={'−':'-','×':'*','⋅':'*','·':'*','÷':'/','≤':'<=','≥':'>=','≠':'!=','{':'(', '}':')','[':'(',']':')'}.get(text,text)
        if text in ('+','-','*','/','(',')','=',',','<','>','<=','>=','!='):return [text]
        raise Unsupported('미지원 계산 기호: '+text)
    if tag=='mfrac':
        a,b=expr(cs[0]),expr(cs[1])
        if b==0:raise Unsupported('분모가 0입니다.')
        return [a/b]
    if tag in ('msup','msub','msubsup'):
        if tag=='msub':
            base=''.join(str(x) for x in tokens(cs[0]));index=expr(cs[1])
            return [symbol(base+'_'+str(index))]
        base=expr(cs[0]) if tag=='msup' else symbol(''.join(str(x) for x in tokens(cs[0]))+'_'+str(expr(cs[1])))
        power=expr(cs[1] if tag=='msup' else cs[2])
        if power.is_number and (not power.is_Rational or abs(power)>30):raise Unsupported('지수의 검사 범위를 초과했습니다.')
        return [base**power]
    if tag=='msqrt':return [S.sqrt(expr({'tag':'mrow','children':cs}))]
    if tag=='mover' and cs[1].get('text','') in ('¯','―','‾','̅'):return [S.conjugate(expr(cs[0]))]
    if tag=='mtext' and not text:return []
    raise Unsupported('미지원 계산 구조: '+tag)

class Reader:
    def __init__(self,seq):self.seq=seq;self.index=0
    def peek(self):return self.seq[self.index] if self.index<len(self.seq) else None
    def take(self):r=self.peek();self.index+=1;return r
    def parse(self,minimum=0):
        t=self.take()
        if t is None:raise Unsupported('빈 수식입니다.')
        if t=='+':left=self.parse(30)
        elif t=='-':left=-self.parse(30)
        elif t=='(':
            left=self.parse()
            if self.take()!=')':raise Unsupported('괄호가 일치하지 않습니다.')
        elif isinstance(t,(S.Basic,S.FunctionClass)):left=t
        else:raise Unsupported('계산할 수 없는 수식입니다.')
        while True:
            nxt=self.peek()
            if nxt is None or nxt in (')',',','=','<=','>=','<','>','!='):break
            implicit=isinstance(nxt,(S.Basic,S.FunctionClass)) or nxt=='('
            op='*' if implicit else nxt
            precedence=10 if op in ('+','-') else 20 if op in ('*','/') else -1
            if isinstance(left,S.FunctionClass) and nxt=='(':
                self.take();arg=self.parse()
                if self.take()!=')':raise Unsupported('함수 괄호가 일치하지 않습니다.')
                left=left(arg);continue
            if precedence<minimum:break
            if not implicit:self.take()
            right=self.parse(precedence+1)
            if op=='+':left=left+right
            elif op=='-':left=left-right
            elif op=='*':left=left*right
            elif op=='/':
                if right==0:raise Unsupported('분모가 0입니다.')
                left=left/right
        return left

def expr(tree):
    seq=tokens(tree)
    if len(seq)>300:raise Unsupported('수식의 계산 크기를 초과했습니다.')
    r=Reader(seq);left=r.parse()
    op=r.peek()
    if op in ('=','<=','>=','<','>','!='):
        r.take();right=r.parse()
        cls={'=':S.Eq,'<=':S.Le,'>=':S.Ge,'<':S.Lt,'>':S.Gt,'!=':S.Ne}[op]
        left=cls(left,right,evaluate=False)
    if r.peek() is not None:raise Unsupported('여러 식이 섞여 있습니다.')
    return left

def parse(text,kind='eqedit'):
    return expr(equation(text,kind)['ast'])

def same(a,b):
    try:return S.simplify(a-b)==0
    except (TypeError,ValueError):return False

def scalar_answer(text):
    text=str(text).strip().replace('−','-')
    if len(text)>300:raise Unsupported('답안이 너무 깁니다.')
    if '\\' in text:return parse(text,'latex')
    # All strings pass through a grammar, never eval/sympify/parse_expr.
    return parse(text.replace('**','^'))
