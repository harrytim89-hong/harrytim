"""Bounded numeric equality audit; never eval/sympify untrusted model text."""
import ast
from fractions import Fraction
import re


def numeric(expression):
    if len(expression) > 150:
        raise ValueError('expression too long')
    root = ast.parse(expression.replace('^', '**'), mode='eval')
    if sum(1 for _ in ast.walk(root)) > 60:
        raise ValueError('expression too complex')
    def visit(node):
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            if abs(node.value) > 10**12:
                raise ValueError('number too large')
            return Fraction(str(node.value))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        if isinstance(node, ast.BinOp):
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add): return left + right
            if isinstance(node.op, ast.Sub): return left - right
            if isinstance(node.op, ast.Mult): return left * right
            if isinstance(node.op, ast.Div): return left / right
            if isinstance(node.op, ast.Pow) and right.denominator == 1 and abs(right) <= 20:
                if left.numerator.bit_length() > 1000: raise ValueError('power too large')
                return left ** int(right)
        raise ValueError('unsupported arithmetic')
    return visit(root)


def audit(steps):
    checked, errors = 0, []
    for step in steps:
        for equation in re.findall(r'\$([^$]+)\$', step):
            sides = equation.split('=')
            if len(sides) < 2 or any(not re.fullmatch(r'[\d\s.+*/()^\-]+', side) for side in sides):
                continue
            try:
                values = [numeric(side) for side in sides]
            except (ValueError, SyntaxError, ZeroDivisionError, OverflowError):
                continue
            checked += 1
            if len(set(values)) != 1:
                errors.append('계산 불일치: ' + equation)
    return {'checked_equalities':checked, 'errors':errors}
