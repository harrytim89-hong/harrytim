"""Document-local boundary evidence; never requires users to renumber a file."""
from __future__ import annotations
import copy
import re
from collections import defaultdict
from dataclasses import dataclass,field
from defusedxml import ElementTree as ET
from xml.etree.ElementTree import Element
from .formula import local

SKIP={'header','footer','endNote','footNote','secPr','linesegarray'}
CUES=re.compile(r'\?|？|구하|값은|계산하|계산하면|나타내|증명하|고르|옳은|옳지|몇|만족|최댓값|최솟값')
# Decimal literals such as 0.8 or 1.5 must not become question numbers.
PREFIX=re.compile(r'^\s*(?:(?P<label>\[?\s*(?:문제|문항|물음|서답형|서술형)\s*(?P<ln>\d{1,4})\s*\]?[.):．]?)[\s\u3000]*|(?P<bracket>[\[【(（]\s*(?P<bn>\d{1,4})\s*[\]】)）])\s*|(?P<plain>(?P<pn>\d{1,4})\s*[.．](?!\d)|(?P<rn>\d{1,4})\s*[)）])\s*)')

def descendants(node,name):return [n for n in node.iter() if local(n.tag)==name]

def visible_text(p):
    """Own inline text only: exclude nested tables, answers and running headers."""
    def read(n):
        tag=local(n.tag)
        if tag in SKIP or tag in ('tbl','rect','equation'):return ''
        if tag=='lineBreak':return '\n'
        if tag=='tab':return '\t'
        if tag=='t':return (n.text or '')+''.join(read(c)+(c.tail or '') for c in n)
        return ''.join(read(c) for c in n)
    return read(p)

def prefix(p):
    match=PREFIX.match(visible_text(p))
    if not match:return None
    number=int(next(match[k] for k in ('ln','bn','pn','rn') if match[k] is not None))
    if not number:return None
    family='label' if match['label'] else 'bracket' if match['bracket'] else 'dot' if match['pn'] else 'paren'
    return number,family,match[0]

def own_notes(p):
    result=[]
    def visit(n):
        tag=local(n.tag)
        if tag in ('endNote','footNote'):result.append(n);return
        if tag in ('tbl','rect','header','footer','secPr'):return
        for c in n:visit(c)
    visit(p);return result

def quick_answer(note):
    text=''.join(n.text or '' for n in note.iter() if local(n.tag)=='t').strip()
    scripts=[n.text or '' for n in note.iter() if local(n.tag)=='script']
    if scripts:
        return not text and len(scripts)==1 and len(scripts[0])<=100
    return bool(re.fullmatch(r'[①-⑤1-5]|[-+−]?\d+(?:\.\d+)?(?:\s*/\s*[-+]?\d+)?',text))

@dataclass
class Unit:
    part:str
    paragraph:int
    node:object
    location:str

@dataclass
class Start:
    index:int
    number:int|None
    family:str
    label:str=''
    note:object=None
    level:int=0
    issues:list=field(default_factory=list)

def _sequence(items):
    return len(items)>=2 and all(b.number==a.number+1 for a,b in zip(items,items[1:]))

def _container_question_evidence(container):
    # A condition table with numbered rows is not a set of questions.
    ps=[p for p in container.iter() if local(p.tag)=='p']
    starts=[(i,prefix(p)) for i,p in enumerate(ps) if prefix(p)]
    if not starts:return False
    nums=[v[1][0] for v in starts]
    if len(nums)>1 and not all(b==a+1 for a,b in zip(nums,nums[1:])):return False
    for offset,(i,mark) in enumerate(starts):
        end=starts[offset+1][0] if offset+1<len(starts) else len(ps)
        text=' '.join(visible_text(p) for p in ps[i:end])
        if mark[1]!='label' and not CUES.search(text):return False
    return True

def _line_units(p):
    """Split only real paragraph line breaks, never visual line wrapping."""
    text=visible_text(p);lines=text.splitlines()
    numbered=[PREFIX.match(s) for s in lines if PREFIX.match(s)]
    if len(numbered)<2:return [p]
    numbers=[int(next(m[k] for k in ('ln','bn','pn','rn') if m[k] is not None)) for m in numbered]
    if not all(b==a+1 for a,b in zip(numbers,numbers[1:])):return [p]
    # Preserve inline object order by splitting run text at actual line breaks.
    fragments=[];current=Element(p.tag,dict(p.attrib))
    def append_piece(run,child):
        newrun=Element(run.tag,dict(run.attrib));newrun.append(child);current.append(newrun)
    for run in p:
        if local(run.tag)!='run':continue
        for child in run:
            if local(child.tag)!='t':append_piece(run,copy.deepcopy(child));continue
            chunks=[child.text or '']
            for sub in child:
                if local(sub.tag)=='lineBreak':chunks.append(sub.tail or '')
                elif local(sub.tag)=='tab':chunks[-1]+='\t'+(sub.tail or '')
                else:chunks[-1]+=''.join(sub.itertext())+(sub.tail or '')
            expanded=[]
            for chunk in chunks:expanded.extend(chunk.split('\n'))
            for i,chunk in enumerate(expanded):
                if i:
                    fragments.append(current);current=Element(p.tag,dict(p.attrib))
                t=Element(child.tag,dict(child.attrib));t.text=chunk;append_piece(run,t)
    fragments.append(current)
    return fragments

def document_units(sections,review=False):
    units=[]
    def add(p,part,index,path):
        # Tables/text boxes used purely for page layout may enclose whole items.
        containers=[c for r in p if local(r.tag)=='run' for c in r if local(c.tag) in ('tbl','rect')]
        expandable={id(c) for c in containers if _container_question_evidence(c) or review and ''.join(n.text or '' for n in c.iter() if local(n.tag)=='t').count('⑤')>=2}
        own=visible_text(p).strip()
        if expandable and (not own or review):
            pending=Element(p.tag,dict(p.attrib));piece=0
            def flush():
                nonlocal pending,piece
                if list(pending):
                    units.append(Unit(part,index,pending,path+f'/piece[{piece}]'));piece+=1
                    pending=Element(p.tag,dict(p.attrib))
            for run in p:
                if local(run.tag)!='run':continue
                for child in run:
                    if id(child) in expandable:
                        flush()
                        row_index=0
                        for sub in child:
                            if local(sub.tag)=='tr':
                                for ci,cell in enumerate(sub):
                                    for sublist in cell:
                                        if local(sublist.tag)=='subList':
                                            for pi,para in enumerate(sublist):
                                                if local(para.tag)=='p':add(para,part,index,path+f'/table/row[{row_index}]/cell[{ci}]/p[{pi}]')
                                row_index+=1
                            elif local(sub.tag)=='drawText':
                                for sublist in sub:
                                    if local(sublist.tag)=='subList':
                                        for pi,para in enumerate(sublist):
                                            if local(para.tag)=='p':add(para,part,index,path+f'/textbox/p[{pi}]')
                    else:
                        r=Element(run.tag,dict(run.attrib));r.append(copy.deepcopy(child));pending.append(r)
            flush();return
        for line,fragment in enumerate(_line_units(p)):
            units.append(Unit(part,index,fragment,path+f'/line[{line}]'))
    for part,root in sections:
        for i,p in enumerate(root):
            if local(p.tag)=='p':add(p,part,i,f'{part}/p[{i}]')
    return units

def _headings(files):
    props={};numberings={}
    for name,data in files.items():
        if not name.endswith('header.xml'):continue
        root=ET.fromstring(data)
        for p in descendants(root,'paraPr'):
            heading=next(iter(descendants(p,'heading')),None)
            if heading is not None and heading.get('type','').upper()=='NUMBER':
                props[p.get('id')]=(heading.get('idRef','0'),int(heading.get('level','0')))
        for n in descendants(root,'numbering'):
            levels={}
            for head in descendants(n,'paraHead'):
                level=int(head.get('level','1'))-1
                levels[level]=int(head.get('start',n.get('start','1')))
            numberings[n.get('id')]=levels
    return props,numberings

def detect(units,files):
    """Return starts and an auditable profile; ambiguous input stays stored."""
    notes=[]
    for i,u in enumerate(units):
        ns=own_notes(u.node)
        if len(ns)!=1 or not quick_answer(ns[0]):continue
        visible=visible_text(u.node).strip();mark=prefix(u.node)
        try:number=int(ns[0].get('number','0'))
        except ValueError:continue
        standalone=not visible or re.fullmatch(r'\[\s*(?:서답형|서술형)\s*\d+\s*\]',visible)
        if standalone or mark and mark[0]==number:
            notes.append(Start(i,number,'answer-note',mark[2] if mark else '',ns[0]))
    if notes and (_sequence(notes) or len(notes)==1):
        # A solitary scalar note embedded in prose is not an exam profile.
        has_items=all(CUES.search(' '.join(visible_text(u.node) for u in units[n.index:(notes[j+1].index if j+1<len(notes) else len(units))])) for j,n in enumerate(notes))
        if has_items:return notes,'sequential-answer-notes'
    heading_props,numberings=_headings(files)
    counters={};auto=[];plain=[]
    for i,u in enumerate(units):
        mark=prefix(u.node)
        if mark:plain.append(Start(i,mark[0],mark[1],mark[2]))
        heading=heading_props.get(u.node.get('paraPrIDRef'))
        if heading:
            nid,level=heading;key=(nid,level)
            number=counters.get(key,numberings.get(nid,{}).get(level,1)-1)+1;counters[key]=number
            for nested in list(counters):
                if nested[0]==nid and nested[1]>level:del counters[nested]
            auto.append(Start(i,number,'paragraph-numbering',level=level))
        # Figure/table/equation captions are not paragraph numbering.
        for n in u.node.iter():
            if local(n.tag)=='autoNum' and n.get('numType','').upper() in ('PARAGRAPH','NUMBER','USER'):
                try:auto.append(Start(i,int(n.get('num','0')),'inline-numbering'))
                except ValueError:pass
    if auto:
        level=min(n.level for n in auto);outer=[n for n in auto if n.level==level]
        if _sequence(outer) or len(outer)==1:return outer,'paragraph-numbering'
    groups=defaultdict(list)
    for candidate in plain:
        scope=(re.search(r'문제|문항|물음|서답형|서술형',candidate.label)[0] if candidate.family=='label' else '')
        groups[(candidate.family,scope)].append(candidate)
    ranked=[]
    for (family,scope),starts in groups.items():
        increasing=all(b.number>a.number for a,b in zip(starts,starts[1:]))
        if not increasing:continue
        # Numbered conditions/decimal data alone are not a document profile.
        cue_count=sum(bool(CUES.search(' '.join(visible_text(u.node) for u in units[s.index:(starts[j+1].index if j+1<len(starts) else len(units))]))) for j,s in enumerate(starts))
        style_count=len({(units[s.index].node.get('styleIDRef'),units[s.index].node.get('paraPrIDRef')) for s in starts})
        consecutive=_sequence(starts)
        if len(starts)>=2 and (consecutive or cue_count==len(starts)) or len(starts)==1 and (cue_count or family=='label'):
            priority={'label':4,'dot':3,'paren':2,'bracket':1}[family]
            ranked.append((priority,len(starts),-style_count,starts))
    if ranked:
        # The outer series starts first. A later "서답형 1" must not hide
        # preceding multiple-choice items just because its label is explicit.
        ranked.sort(key=lambda item:(-item[3][0].index,*item[:3]),reverse=True);starts=list(ranked[0][3])
        for _,_,_,extra in ranked[1:]:
            if extra[0].family=='label':
                starts.extend(s for s in extra if s.index not in {a.index for a in starts})
        starts.sort(key=lambda s:s.index)
        indices={s.index for s in starts}
        # Competing labels may indicate missed questions or subparts. Preserve
        # that local uncertainty rather than pretending the whole file failed.
        for other in plain:
            if other.index in indices:continue
            if other.family=='label' or starts[0].family in ('bracket','paren') and other.family=='dot' or CUES.search(visible_text(units[other.index].node)):
                owner=next((s for s in reversed(starts) if s.index<other.index),None)
                if owner:owner.issues.append({'reason':'다른 번호 형식의 시작 후보가 있어 경계를 확인해 주세요.','location':units[other.index].location})
        return starts,'numbered-paragraphs-'+starts[0].family
    return [Start(0,None,'unresolved',issues=[{'reason':'문항 경계를 자동 확정하지 못했습니다. 원문을 저장했습니다. 문항 나누기에서 시작 문단을 선택해 주세요.','code':'boundary_review'}])],'boundary-review'

def strip_prefix(blocks,label):
    """Remove an identified marker across runs without eating a decimal answer."""
    if not label or not blocks or blocks[0]['kind']!='paragraph':return
    remaining=len(label)
    for b in blocks[0]['blocks']:
        if b['kind']!='text':
            if remaining:return
            break
        count=min(remaining,len(b['value']));b['value']=b['value'][count:];remaining-=count
        if not remaining:break
