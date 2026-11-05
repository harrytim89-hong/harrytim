"""Small, explicit HWP equation grammar. Unsupported syntax is never guessed."""
from dataclasses import dataclass
import re


class UnsupportedEquation(ValueError):
    pass


@dataclass(frozen=True)
class Node:
    kind: str
    value: str = ""
    children: tuple = ()

    def data(self):
        return {"kind": self.kind, "value": self.value,
                "children": [n.data() for n in self.children]}

    @classmethod
    def load(cls, data):
        return cls(data["kind"], data.get("value", ""), tuple(cls.load(c) for c in data.get("children", [])))


SYMBOLS = {"pi": (r"\pi", "pi"), "infty": (r"\infty", "infinity"),
           "in": (r"\in", "in"), "leq": (r"\leq", "lt.eq"),
           "geq": (r"\geq", "gt.eq"), "neq": (r"\ne", "eq.not"),
           "times": (r"\times", "times"), "cdot": (r"\cdot", "dot"),
           "cup": (r"\cup", "union"), "cap": (r"\cap", "inter")}
SYMBOLS['pm'] = (r'\pm', 'plus.minus')
for _name in ('alpha', 'beta', 'gamma', 'delta', 'theta', 'lambda', 'mu', 'sigma', 'omega'):
    SYMBOLS[_name] = ('\\' + _name, _name)
SYMBOLS['le'] = SYMBOLS['leq']
SYMBOLS['ge'] = SYMBOLS['geq']


def from_latex(source):
    """Balanced macro conversion into the same grammar, never executable markup."""
    def group(s, pos):
        while pos < len(s) and s[pos].isspace(): pos += 1
        if pos >= len(s) or s[pos] != '{': raise UnsupportedEquation('LaTeX 인자 오류')
        depth, end = 1, pos + 1
        while end < len(s) and depth:
            depth += (s[end] == '{') - (s[end] == '}')
            end += 1
        if depth: raise UnsupportedEquation('LaTeX 괄호 오류')
        return s[pos+1:end-1], end
    def convert(s, depth=0):
        if depth > 30: raise UnsupportedEquation('LaTeX 중첩 제한')
        out, pos = [], 0
        while pos < len(s):
            if s[pos] != '\\':
                out.append(s[pos]); pos += 1; continue
            m = re.match(r'\\([A-Za-z]+)', s[pos:])
            if not m: raise UnsupportedEquation('LaTeX 명령 오류')
            command = m.group(1)
            pos += len(m.group())
            if command in ('left', 'right'): continue
            if command == 'frac':
                a, end = group(s, pos); b, pos = group(s, end)
                out.append(' {{' + convert(a, depth+1) + '} over {' + convert(b, depth+1) + '}} ')
            elif command in ('sqrt', 'overline'):
                a, pos = group(s, pos)
                out.append(' ' + command + ' {' + convert(a, depth+1) + '} ')
            elif command in SYMBOLS or command in ('sin', 'cos', 'tan', 'log', 'ln', 'exp'):
                out.append(' ' + command + ' ')
            else: raise UnsupportedEquation('미지원 LaTeX 명령: ' + command)
        return ''.join(out)
    return parse(convert(source))


class Parser:
    def __init__(self, source):
        if len(source) > 10000:
            raise UnsupportedEquation("수식 크기 제한")
        raw = re.findall(r"[A-Za-z]+|\d+(?:\.\d+)?|[^\s]", source)
        self.tokens = []
        reserved = set(SYMBOLS) | {'sqrt','over','overline','cases','matrix','int','sum','lim','sin','cos','tan','log','ln','exp'}
        for token in raw:
            if token in ('`', '~', 'left', 'right', 'it', 'rm'):
                continue
            if token.isalpha() and len(token) == 2 and token not in reserved:
                self.tokens.extend(token)
            else:
                self.tokens.append(token)
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else ""

    def take(self):
        t = self.peek()
        self.pos += 1
        return t

    def sequence(self, closing="", depth=0):
        if depth > 40:
            raise UnsupportedEquation("수식 중첩 제한")
        items = []
        while self.peek() and self.peek() not in closing:
            t = self.take()
            if t == "over":
                if not items:
                    raise UnsupportedEquation("분자 없음")
                left = items.pop()
                right = self.atom(depth + 1)
                while self.peek() in ('^', '_'):
                    op = self.take()
                    right = Node('sup' if op == '^' else 'sub', children=(right, self.atom(depth + 1)))
                items.append(Node('frac', children=(left, right)))
                continue
            if t in ("^", "_"):
                if not items:
                    raise UnsupportedEquation("첨자 대상 없음")
                base = items.pop()
                items.append(Node("sup" if t == "^" else "sub", children=(base, self.atom(depth + 1))))
            elif t in ("}", ")", "]"):
                raise UnsupportedEquation("괄호 불일치")
            else:
                self.pos -= 1
                item = self.atom(depth + 1)
                if item.kind == 'group' and item.value == '{' and not item.children[0].children and items and self.peek() in ('^','_'):
                    continue
                items.append(item)
        return Node("seq", children=tuple(items))

    def atom(self, depth):
        if depth > 40:
            raise UnsupportedEquation("수식 중첩 제한")
        t = self.take()
        if not t:
            raise UnsupportedEquation("불완전 수식")
        if t in ("{", "(", "["):
            close = {"{": "}", "(": ")", "[": "]"}[t]
            child = self.sequence(close, depth + 1)
            if self.take() != close:
                raise UnsupportedEquation("괄호 불일치")
            return Node("group", t, (child,))
        if t in ('sqrt', 'overline'):
            return Node(t, children=(self.atom(depth + 1),))
        if t == 'cases':
            if self.take() != '{': raise UnsupportedEquation('경우 나눔 괄호 오류')
            rows = []
            while self.peek() and self.peek() != '}':
                rows.append(self.sequence('#}', depth + 1))
                if self.peek() == '#': self.take()
            if self.take() != '}' or not rows: raise UnsupportedEquation('경우 나눔 구문 오류')
            return Node('cases', children=tuple(rows))
        if t in SYMBOLS:
            return Node("symbol", t)
        if t in ("sin", "cos", "tan", "log", "ln", "exp"):
            return Node("function", t)
        if re.fullmatch(r"\d+(?:\.\d+)?|[A-Za-z]|[+\-−*/=<>.,:;!|]", t):
            return Node("token", t.replace("−", "-"))
        raise UnsupportedEquation(f"미지원 수식 토큰: {t}")


def parse(source):
    p = Parser(source)
    node = p.sequence()
    if p.pos != len(p.tokens) or not node.children:
        raise UnsupportedEquation("빈 수식 또는 구문 오류")
    return node


def render(n, target):
    def ungroup(node):
        while True:
            if node.kind == 'group' and node.value == '{': node = node.children[0]
            elif node.kind == 'seq' and len(node.children)==1 and node.children[0].kind=='group' and node.children[0].value=='{': node=node.children[0]
            else: return render(node,target)
    if n.kind == "token":
        return n.value
    if n.kind == "symbol":
        return n.value if target == "hwp" else SYMBOLS[n.value][0 if target == "latex" else 1]
    if n.kind == "function":
        return "\\" + n.value if target == "latex" else n.value
    c = [render(x, target) for x in n.children]
    if n.kind == "seq":
        return " ".join(c)
    if n.kind == 'cases':
        if target == 'latex': return r'\begin{cases}' + r' \\ '.join(c) + r'\end{cases}'
        if target == 'typst': return 'cases(' + ','.join(c) + ')'
        return 'cases {' + ' # '.join(c) + '}'
    if n.kind == 'overline':
        child = n.children[0]
        inner = render(child.children[0], target) if child.kind == 'group' and child.value == '{' else c[0]
        return r'\overline{' + inner + '}' if target == 'latex' else 'overline(' + inner + ')' if target == 'typst' else 'overline {' + inner + '}'
    if n.kind == "group":
        if n.value == "{":
            if target=='typst' and n.children[0].kind=='seq' and len(n.children[0].children)==1:
                child=n.children[0].children[0]
                if child.kind in ('token','symbol','group','cases','overline'):return render(child,target)
            return "{" + c[0] + "}" if target != "typst" else "(" + c[0] + ")"
        return n.value + c[0] + {"(": ")", "[": "]"}[n.value]
    if n.kind == "frac":
        c = [ungroup(x) for x in n.children]
        return {"latex": lambda: r"\frac{" + c[0] + "}{" + c[1] + "}",
                "hwp": lambda: "{" + c[0] + "} over {" + c[1] + "}",
                "typst": lambda: "frac(" + c[0] + "," + c[1] + ")"}[target]()
    if n.kind == "sqrt":
        c[0]=ungroup(n.children[0])
        return (r"\sqrt{" + c[0] + "}" if target == "latex" else
                "sqrt(" + c[0] + ")" if target == "typst" else "sqrt {" + c[0] + "}")
    if n.kind in ("sup", "sub"):
        c[1]=ungroup(n.children[1])
        op = "^" if n.kind == "sup" else "_"
        return c[0] + op + ("(" + c[1] + ")" if target == "typst" else "{" + c[1] + "}")
    raise UnsupportedEquation("알 수 없는 내부 수식")


def block(source):
    result = {"type": "equation", "source": source, "syntax": "hwp"}
    try:
        tree = parse(source)
        result.update(ast=tree.data(), latex=render(tree, "latex"), supported=True)
    except UnsupportedEquation as exc:
        result.update(supported=False, issue=str(exc))
    return result
