"""EqEdit grammar -> a sanitized MathML tree -> independent safe renderers."""
from __future__ import annotations
import re
import html
import json
from defusedxml import ElementTree as ET
from hwpx.equation import eqedit_to_latex, latex_to_mathml, latex_to_eqedit

ALLOWED={'math','mrow','mi','mn','mo','mfrac','msqrt','mroot','msup','msub','msubsup','munder','mover','munderover','mtable','mtr','mtd','mstyle','mspace','mtext','mfenced','menclose','mpadded','mphantom'}

def local(tag): return tag.rsplit('}',1)[-1]

def ast_from_xml(node):
    tag=local(node.tag)
    if tag not in ALLOWED: raise ValueError('미지원 수식 구조: '+tag)
    result={'tag':tag,'text':node.text or '', 'children':[ast_from_xml(c) for c in node]}
    if tag=='mfenced': result['open']=node.get('open','(');result['close']=node.get('close',')')
    # A HWP spacing mark between x and its script is not the base of the script.
    out=[]
    for c in result['children']:
        if c['tag'] in ('msub','msup','msubsup') and c['children'] and c['children'][0]['tag'] in ('mspace',) and out:
            c['children'][0]=out.pop()
        if c['tag'] in ('msub','msup','msubsup') and c['children'] and c['children'][0]['tag']=='mo' and c['children'][0]['text'] in (')',']'):
            close=c['children'][0]['text']; opening='(' if close==')' else '[';depth=0;start=None
            for i in range(len(out)-1,-1,-1):
                token=out[i]
                if token['tag']=='mo' and token['text']==close:depth+=1
                if token['tag']=='mo' and token['text']==opening:
                    if depth==0:start=i;break
                    depth-=1
            if start is None: raise ValueError('수식 첨자 앞 괄호가 일치하지 않습니다.')
            c['children'][0]={'tag':'mrow','text':'','children':out[start:]+[c['children'][0]]}
            out=out[:start]
        out.append(c)
    result['children']=out
    return result

def mathml(tree):
    tag=tree['tag']; attrs=' xmlns="http://www.w3.org/1998/Math/MathML"' if tag=='math' else ''
    if tag not in ALLOWED:raise ValueError('허용하지 않는 수식 태그입니다.')
    if tag=='mfenced': attrs+=' open="'+html.escape(tree.get('open','('),quote=True)+'" close="'+html.escape(tree.get('close',')'),quote=True)+'"'
    return '<'+tag+attrs+'>'+html.escape(tree.get('text',''))+''.join(mathml(c) for c in tree['children'])+'</'+tag+'>'

def equation(source,kind='eqedit'):
    if not isinstance(source,str) or len(source)>10000: raise ValueError('수식 길이가 제한을 초과했습니다.')
    original=source
    # Empty groups used as a visual spacing base must bind powers to the prior atom.
    if kind=='eqedit':
        source=re.sub(r'(?<=[A-Za-z0-9])\s*\{\s*\}\s*(?=[_^])','',source)
        # The upstream grammar expects a delimiter separated from right/left.
        # Use ordinary paired delimiters; no sizing information is semantic.
        source=re.sub(r'\b(?:left|right)\s*(?=[()\[\]])','',source)
        source=re.sub(r'\ble\b','<=',source)
        source=re.sub(r'\bge\b','>=',source)
        source=re.sub(r'(?<=[A-Za-z0-9])`+(?=\s*[_^])','',source)
        latex=eqedit_to_latex(source)
    else: latex=source
    tree=ast_from_xml(ET.fromstring(latex_to_mathml(latex)))
    result={'kind':'math','source':original,'source_format':kind,'latex':latex,'ast':tree,'mathml':mathml(tree)}
    result['typst']=typst(tree) # Unsupported rendering is an input-quality issue.
    return result

def text_quote(text): return json.dumps(str(text),ensure_ascii=False)

SYMBOLS={'α':'alpha','β':'beta','γ':'gamma','δ':'delta','θ':'theta','λ':'lambda','μ':'mu','π':'pi','σ':'sigma','ω':'omega','Ω':'Omega','Δ':'Delta','∞':'infinity','∑':'sum','∏':'product','∫':'integral','∈':'in','∉':'in.not','⊂':'subset','⊆':'subset.eq','∩':'sect','∪':'union','∅':'emptyset','≤':'<=','≥':'>=','≠':'!=','−':'-','×':'times','·':'dot','⋅':'dot','÷':'div','±':'plus.minus','∓':'minus.plus','→':'arrow.r','⇒':'arrow.r.double','⇔':'arrow.l.r.double','∴':'therefore','∵':'because','∠':'angle','⊥':'perp','∥':'parallel','′':"'",'″':"''",'…':'dots.h','⋯':'dots.h','|':'bar.v','{':'brace.l','}':'brace.r','[':'bracket.l',']':'bracket.r','(':'(',')':')'}

def typst(t):
    tag=t['tag'];cs=t['children'];text=t.get('text','').strip()
    rec=lambda i:typst(cs[i])
    if tag in ('math','mrow','mstyle','mpadded','mtd'): return ' '.join(typst(c) for c in cs)
    if tag=='mspace': return 'thin'
    if tag=='mn':
        if not re.fullmatch(r'[0-9.]+',text): raise ValueError('미지원 수식 숫자')
        return text
    if tag in ('mi','mo'):
        if text in SYMBOLS: return SYMBOLS[text]
        if re.fullmatch(r'[a-zA-Z0-9+\-=<>/!,;:.]+',text):
            if len(text)>1 and text.isalpha(): return 'upright('+text_quote(text)+')'
            return text
        return 'text('+text_quote(text)+')'
    if tag=='mtext': return 'text('+text_quote(text)+')'
    if tag=='mfrac': return 'frac('+rec(0)+','+rec(1)+')'
    if tag=='msqrt': return 'sqrt('+ ' '.join(typst(c) for c in cs)+')'
    if tag=='mroot': return 'root('+rec(1)+','+rec(0)+')'
    if tag=='msup': return 'attach('+rec(0)+',tr:'+rec(1)+')'
    if tag=='msub': return 'attach('+rec(0)+',br:'+rec(1)+')'
    if tag=='msubsup': return 'attach('+rec(0)+',br:'+rec(1)+',tr:'+rec(2)+')'
    if tag=='mover':
        accent=cs[1].get('text','')
        if accent in ('¯','―','‾','̅','⏞'): return 'overline('+rec(0)+')'
        if accent in ('^','ˆ','̂'): return 'hat('+rec(0)+')'
        if accent in ('→','⃗'): return 'arrow('+rec(0)+')'
        raise ValueError('미지원 윗첨자 장식: '+accent)
    if tag in ('munder','munderover'):
        return '('+rec(0)+')_('+rec(1)+')'+('^('+rec(2)+')' if len(cs)>2 else '')
    if tag=='mtr': return ','.join(typst(c) for c in cs)
    if tag=='mtable': return 'mat('+ ';'.join(typst(c) for c in cs)+')'
    if tag=='mfenced': return 'lr('+typst({'tag':'mo','text':t.get('open','('),'children':[]})+' '+ ' , '.join(typst(c) for c in cs)+' '+typst({'tag':'mo','text':t.get('close',')'),'children':[]})+')'
    raise ValueError('미지원 수식 조판: '+tag)

def to_eqedit(item):
    if item.get('source_format')=='eqedit': return item['source']
    return latex_to_eqedit(item['latex'])
