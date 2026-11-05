"""Exact, bounded algebra checks. No sympify/parse_expr on external strings.

Automatic proof policies currently cover explicitly phrased real polynomial
equations of degree 1/2, evaluations, and inverse coefficient questions.
Everything else remains held, even when two model responses agree.
"""
import ast
import hashlib
import json
import re
import sympy as sp
from .equations import Node, parse

X = sp.Symbol('x', real=True)


def safe_expr(text, variables=None, allow_complex=False):
    text = str(text).strip().strip('$').replace('−', '-').replace('^', '**')
    if len(text) > 500:
        raise ValueError('계산식 길이 제한')
    # Translate a tightly bounded LaTeX subset using balanced groups, never eval.
    def latex_group(s, start):
        if start >= len(s) or s[start] != '{':
            raise ValueError('수식 중괄호 오류')
        depth = 1
        end = start + 1
        while end < len(s) and depth:
            depth += (s[end] == '{') - (s[end] == '}')
            end += 1
        if depth:
            raise ValueError('수식 중괄호 오류')
        return s[start + 1:end - 1], end
    for _ in range(30):
        match = re.search(r'\\(frac|sqrt)\s*', text)
        if not match:
            break
        a, end = latex_group(text, match.end())
        if match.group(1) == 'frac':
            b, end = latex_group(text, end)
            replacement = f'(({a})/({b}))'
        else:
            replacement = f'sqrt({a})'
        text = text[:match.start()] + replacement + text[end:]
    text = text.replace('{', '(').replace('}', ')')
    tokens = re.findall(r'\*\*|sqrt|[A-Za-z]|\d+(?:\.\d+)?|[()+\-*/]', text)
    if re.sub(r'\s+', '', text) != ''.join(tokens):
        raise ValueError('미지원 계산식')
    fixed = []
    for token in tokens:
        if fixed:
            a = fixed[-1]
            if (a == ')' or a.isalpha() and a != 'sqrt' or a[-1:].isdigit()) and (token == '(' or token.isalpha() or token[0].isdigit()):
                fixed.append('*')
        fixed.append(token)
    try:
        tree = ast.parse(''.join(fixed), mode='eval')
    except (SyntaxError, RecursionError) as exc:
        raise ValueError('계산식 구문 오류') from exc
    if len(list(ast.walk(tree))) > 150:
        raise ValueError('계산식 복잡도 제한')
    variables = variables or {'x': X, 'a': sp.Symbol('a', real=True)}
    def bounded(value):
        if value.is_number:
            for number in value.atoms(sp.Integer):
                if abs(int(number)).bit_length() > 4096: raise ValueError('중간 계산 수치 크기 제한')
        if sp.count_ops(value) > 150: raise ValueError('중간 계산 복잡도 제한')
        return value
    def visit(n):
        if isinstance(n, ast.Constant) and type(n.value) in (int, float):
            if abs(n.value) > 10**12:
                raise ValueError('계산 수치 범위 제한')
            return sp.Rational(str(n.value))
        if isinstance(n, ast.Name) and n.id in variables:
            return variables[n.id]
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.UAdd, ast.USub)):
            return visit(n.operand) * (-1 if isinstance(n.op, ast.USub) else 1)
        if isinstance(n, ast.BinOp):
            left, right = visit(n.left), visit(n.right)
            if isinstance(n.op, ast.Add): return bounded(left + right)
            if isinstance(n.op, ast.Sub): return bounded(left - right)
            if isinstance(n.op, ast.Mult): return bounded(left * right)
            if isinstance(n.op, ast.Div):
                if right == 0: raise ValueError('분모 0')
                # Variable denominators require a domain proof not supplied here.
                if right.free_symbols: raise ValueError('문자 분모 정의역 검사 미지원')
                return bounded(left / right)
            if isinstance(n.op, ast.Pow) and right.is_Integer and abs(right) <= 6:
                return bounded(left ** right)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'sqrt' and len(n.args) == 1 and not n.keywords:
            val = visit(n.args[0])
            if val.free_symbols or val.is_real is not True or val < 0 and not allow_complex: raise ValueError('근호 정의역 검사 미지원')
            return sp.sqrt(val)
        raise ValueError('허용되지 않은 계산식')
    return visit(tree.body)


def answer_values(text):
    t = re.sub(r'^\s*[xa]\s*=\s*', '', text.strip().strip('$'))
    t = t.replace(r'\{', '').replace(r'\}', '').replace('실근 없음', '없음')
    if t.strip() in ('없음', '공집합', r'\varnothing'):
        return []
    values = [safe_expr(s, {}) for s in re.split(r'[,;]|또는', t)]
    if any(v.free_symbols or v.is_real is not True for v in values):
        raise ValueError('수치 정답이 아닙니다.')
    return values


def equivalent(a, b):
    if a.strip() == b.strip():
        return True
    try:
        av, bv = answer_values(a), answer_values(b)
        if len(av) != len(bv): return False
        unmatched = list(bv)
        for value in av:
            index = next((i for i, v in enumerate(unmatched) if sp.simplify(value-v) == 0), None)
            if index is None: return False
            unmatched.pop(index)
        return True
    except (ValueError, TypeError, ArithmeticError):
        return None


def material(content):
    keys = ('text', 'blocks', 'choices', 'choice_blocks', 'answer', 'solution', 'diagram', 'input_status')
    return {k: content.get(k) for k in keys}


def fingerprint(content):
    return hashlib.sha256(json.dumps(material(content), ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def problem_spec(content):
    text = content.get('text', '').strip()
    # Full matches intentionally prevent a model-supplied spec from changing the question.
    match = re.fullmatch(r'방정식\s*\$([^$]+)\$\s*의\s*모든\s*실근을\s*구하시오[.。]?', text)
    if match:
        sides = match.group(1).split('=')
        if len(sides) != 2: raise ValueError('등식 형태 오류')
        f = sp.expand(safe_expr(sides[0]) - safe_expr(sides[1]))
        if f.free_symbols - {X}: raise ValueError('미지수 조건 미지원')
        p = sp.Poly(f, X)
        if p.degree() not in (1, 2) or any(not c.is_Rational or abs(c) > 100000 for c in p.all_coeffs()):
            raise ValueError('일차·이차 유리계수 방정식만 자동 검증합니다.')
        return {'kind': 'roots', 'polynomial': p}
    match = re.fullmatch(r'다항식\s*\$([^$]+)\$\s*에서\s*\$x\s*=\s*([^$]+)\$\s*일\s*때의\s*값을\s*구하시오[.。]?', text)
    if match:
        f, x = safe_expr(match.group(1)), safe_expr(match.group(2))
        p = sp.Poly(f, X)
        if p.degree() > 4 or f.free_symbols - {X} or x.free_symbols or x.is_Rational is not True:
            raise ValueError('다항식 대입 검사 범위 초과')
        return {'kind': 'evaluation', 'polynomial': p, 'value': x}
    match = re.fullmatch(r'방정식\s*\$([^$]+)\$\s*의\s*한\s*실근이\s*\$x\s*=\s*([^$]+)\$\s*일\s*때,?\s*상수\s*\$a\$\s*의\s*값을\s*구하시오[.。]?', text)
    if match:
        sides = match.group(1).split('=')
        if len(sides) != 2: raise ValueError('등식 형태 오류')
        f = safe_expr(sides[0]) - safe_expr(sides[1])
        root = safe_expr(match.group(2))
        a = sp.Symbol('a', real=True)
        if root.free_symbols or f.free_symbols - {X, a}: raise ValueError('매개변수 조건 미지원')
        p = sp.Poly(f.subs(X, root), a)
        if p.degree() != 1: raise ValueError('상수 결정이 유일하지 않습니다.')
        return {'kind': 'coefficient', 'polynomial': p, 'root': root, 'original': f}
    raise ValueError('이 문항 표현에 적용할 필수 수학 검사 정책이 없습니다.')


def solve_exact(content):
    try:
        spec = problem_spec(content)
    except ValueError:
        from .exam_algebra import solve_exam
        return solve_exam(content)
    p = spec['polynomial']
    symbol = p.gens[0]
    f = p.as_expr()
    evidence = {'policy': 'rational-polynomial-v1', 'kind': spec['kind'], 'polynomial': str(f),
                'domain': 'real', 'method': 'exact algebra + independent substitution + degree/root-count', 'checks': []}
    if spec['kind'] == 'evaluation':
        v = spec['value']
        result = sp.expand(f).subs(X, v)
        # Independent Horner evaluation of the same polynomial.
        horner = sp.Integer(0)
        for coefficient in p.all_coeffs(): horner = horner * v + coefficient
        if sp.simplify(horner-result) != 0: raise ValueError('대입 검산 충돌')
        roots = [result]
        steps = [f'주어진 다항식에 $x={sp.latex(v)}$를 대입합니다.',
                 f'$({sp.latex(f)})_{{x={sp.latex(v)}}}={sp.latex(result)}$입니다.',
                 '각 항을 직접 대입한 값과 호너법으로 계산한 값이 일치합니다.']
        evidence['checks'] = ['direct substitution', 'independent Horner evaluation']
    else:
        if p.degree() == 1:
            a, b = p.all_coeffs()
            roots = [-b/a]
            steps = [f'식을 정리하면 ${sp.latex(f)}=0$입니다.',
                     f'일차항을 남기면 ${sp.latex(a)}{sp.latex(symbol)}={sp.latex(-b)}$입니다.',
                     f'계수 ${sp.latex(a)}$가 0이 아니므로 ${sp.latex(symbol)}={sp.latex(roots[0])}$로 유일하게 결정됩니다.']
        else:
            a, b, c = p.all_coeffs()
            discriminant = b*b - 4*a*c
            roots = [] if discriminant < 0 else sorted(set([sp.simplify((-b-sp.sqrt(discriminant))/(2*a)), sp.simplify((-b+sp.sqrt(discriminant))/(2*a))]), key=lambda x: float(x))
            steps = [f'식을 정리하면 ${sp.latex(f)}=0$입니다.',
                     f'판별식은 $D=({sp.latex(b)})^2-4({sp.latex(a)})({sp.latex(c)})={sp.latex(discriminant)}$입니다.',
                     '판별식이 음수이므로 실근이 없습니다.' if not roots else
                     f'근의 공식 $x=\\frac{{-b\\pm\\sqrt{{D}}}}{{2a}}$에 대입하면 실근은 ${", ".join(sp.latex(r) for r in roots)}$입니다.']
            evidence['discriminant'] = str(discriminant)
            evidence['expected_distinct_real_roots'] = 0 if discriminant < 0 else 1 if discriminant == 0 else 2
            if len(roots) != evidence['expected_distinct_real_roots']: raise ValueError('실근 개수 충돌')
        if any(sp.simplify(f.subs(symbol, r)) != 0 or r.is_real is not True for r in roots):
            raise ValueError('원식 대입/정의역 검산 실패')
        if spec['kind'] == 'coefficient':
            steps.insert(0, f'주어진 실근 $x={sp.latex(spec["root"])}$를 원래 방정식에 대입하여 상수에 대한 일차방정식을 얻습니다.')
        steps.append('구한 값을 정리 전 식에 다시 대입하여 등식이 성립함을 확인합니다. 차수와 실근 개수도 일치합니다.')
        evidence['checks'] = ['exact solution', 'substitution of every root', 'domain', 'completeness', 'uniqueness', 'nonzero leading coefficient']
    answer = ', '.join(sp.sstr(r) for r in roots) if roots else '없음'
    evidence['roots'] = [sp.sstr(r) for r in roots]
    return {'answer': answer, 'solution': steps, 'evidence': evidence, 'spec': spec}


def verify_candidate(content, proposed_answer, blind_answer=None):
    if content.get('variant') and content.get('variant_relation', {}).get('state') != 'passed':
        return {'state': 'held', 'reason': content.get('variant_relation', {}).get('reason', '원본과 변형의 개념/조건 관계 검사 정책이 없습니다.')}
    if content.get('input_status') != 'complete':
        return {'state': 'held', 'reason': '입력 품질 보류 문항입니다.'}
    if any(b['type'] in ('image', 'table', 'box', 'note', 'unsupported') for b in _blocks(content.get('blocks', []))):
        return {'state': 'held', 'reason': '그림·표·추가 조건을 포함한 문항의 의미 검증 정책이 없습니다.'}
    try:
        exact = solve_exact(content)
    except (ValueError, sp.PolynomialError, TypeError) as exc:
        return {'state': 'held', 'reason': str(exc)}
    expected = exact['answer']
    if content.get('choices') and not exact.get('answer_is_choice'):
        comparisons = [equivalent(choice, expected) for choice in content['choices']]
        if any(value is None for value in comparisons):
            return {'state':'held','reason':'모든 보기를 해석하지 못해 객관식 정답의 유일성을 검증할 수 없습니다.'}
        matches = [i+1 for i,value in enumerate(comparisons) if value is True]
        if len(matches) != 1:
            return {'state': 'failed', 'reason': '객관식 정답 보기의 개수가 1개가 아닙니다.'}
        expected = str(matches[0])
    if equivalent(proposed_answer, expected) is not True:
        return {'state': 'failed', 'reason': '제공/생성 정답과 독립 계산 정답이 충돌합니다.', 'expected': expected, 'evidence': exact['evidence']}
    if blind_answer is not None and equivalent(blind_answer, expected) is not True:
        return {'state': 'held', 'reason': '정답을 숨긴 별도 재풀이 결과가 일치하지 않습니다.', 'evidence': exact['evidence']}
    return {'state': 'passed', 'reason': '유형별 필수 계산 검사 통과', 'expected': expected,
            'canonical_solution': exact['solution'], 'evidence': exact['evidence']}


def variant_relation(parent, child, kind):
    from .exam_algebra import polynomial_relation
    if polynomial_relation(parent,child,kind):
        return {'state':'passed','reason':'동일 다항식 연산의 계수 변경' if kind=='numeric' else '원래 연산 결과를 조건으로 하는 역방향 다항식 결정 · 관계식 재대입 확인'}
    try:
        before, after = problem_spec(parent), problem_spec(child)
        if kind == 'numeric' and before['kind'] == after['kind'] == 'roots':
            p, q = before['polynomial'], after['polynomial']
            if p.degree() == q.degree() and p.as_expr() != q.as_expr():
                return {'state': 'passed', 'reason': '같은 차수의 유리계수 방정식 · 수치 변경 · 동일 풀이 정책'}
        if kind == 'thinking' and before['kind'] == 'roots' and after['kind'] == 'coefficient':
            p = before['polynomial']; a = sp.Symbol('a', real=True)
            restored = after['original'].subs(a, p.all_coeffs()[-1])
            if sp.expand(restored-p.as_expr()) == 0 and sp.simplify(p.as_expr().subs(X, after['root'])) == 0:
                return {'state': 'passed', 'reason': '원래 방정식의 실근을 조건으로 고정하고 상수항을 미지수로 바꾼 역방향 추론'}
    except (ValueError, TypeError, sp.PolynomialError):
        pass
    return {'state': 'held', 'reason': '변형의 개념 유지/사고 변화 관계를 검사할 정책이 없습니다.'}


def _blocks(blocks):
    for b in blocks:
        yield b
        yield from _blocks(b.get('children', []))
        for row in b.get('rows', []):
            for cell in row: yield from _blocks(cell['blocks'])
