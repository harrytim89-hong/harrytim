"""Two renderers from the same structured snapshot. No user code execution."""
from __future__ import annotations
import json
import shutil
import zipfile
from pathlib import Path
import typst
from .formula import typst as formula_typst,to_eqedit,text_quote,equation
from .model import identity,checksum,stamp,plain_text

ASSETS=Path(__file__).parent/'ui/assets'
LABEL={'correct':'정답','wrong':'오답','blank':'무응답','partial':'부분정답','pending':'채점 대기','ungraded':'미채점'}

def content_text(value):return '#text('+text_quote(value)+')'
def math_content(b):
    tree=b['ast']
    node=tree
    while node['tag'] in ('math','mrow') and len(node['children'])==1:node=node['children'][0]
    if len(b['latex'])>65 and node['tag'] in ('math','mrow'):
        groups=[[]];depth=0
        for c in node['children']:
            if c['tag']=='mo' and c['text'] in ('(','['):depth+=1
            if c['tag']=='mo' and c['text'] in (')',']'):depth-=1
            if depth==0 and c['tag']=='mo' and c['text']==',':groups.append([])
            else:groups[-1].append(c)
        if len(groups)>1:return '#linebreak()'.join('#math.equation(block:false,$ '+formula_typst({'tag':'mrow','children':cs})+' $)' for cs in groups)
    return '#math.equation(block: false, $ '+formula_typst(tree)+' $)'

class PDF:
    def __init__(self,store,directory):self.store=store;self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True)
    def blocks(self,blocks):
        out=[]
        for b in blocks:
            kind=b['kind']
            if kind=='text':out.append(content_text(b['value']))
            elif kind=='math':out.append(math_content(b))
            elif kind=='paragraph':out.append(self.blocks(b['blocks'])+'\n\n')
            elif kind in ('box','note'):
                out.append('#block(width:100%,inset:9pt,stroke:0.5pt + rgb("#cdd3df"),radius:4pt)['+self.blocks(b['blocks'])+']\n\n')
            elif kind=='table':
                cols=max((sum(c.get('colspan',1) for c in r) for r in b['rows']),default=1)
                cells=[]
                for row in b['rows']:
                    for cell in row:cells.append('table.cell(colspan:'+str(cell.get('colspan',1))+',rowspan:'+str(cell.get('rowspan',1))+')['+self.blocks(cell['blocks'])+']')
                out.append('#table(columns:'+str(cols)+',inset:5pt,stroke:0.4pt + rgb("#cdd3df"),'+','.join(cells)+')\n\n')
            elif kind=='image':
                from PySide6.QtGui import QImage
                src=self.store.path(b['path']);image=QImage(str(src))
                if image.isNull() or image.width()*image.height()>30_000_000:raise ValueError('원본 그림을 읽지 못했습니다.')
                name='asset-'+b['hash']+'.png';image.save(str(self.directory/name),'PNG')
                out.append('#align(center)[#image('+text_quote(name)+',width:70%)]\n\n')
            elif kind=='unsupported':out.append('#text(fill:red)['+content_text('입력 보류: '+b['label'])+']\n\n')
            else:raise ValueError('미지원 출력 블록: '+kind)
        return ''.join(out)

    def prelude(self,exam,student='',kind='문제지'):
        settings=exam['settings'];academy=settings.get('academy','MATHBANK STUDIO');title=exam['title']
        size=float(settings.get('font_size',10));size=max(8,min(size,15));mono=settings.get('monochrome',False)
        accent='#242b37' if mono else '#555de8'
        return '''#set document(title: '''+text_quote(title+' · '+kind)+''', author: '''+text_quote(academy)+''')
#set text(font: ("Noto Sans CJK KR", "DejaVu Serif"), size: '''+str(size)+'''pt, lang: "ko")
#set par(leading: 0.8em, justify: false)
#set page(paper:"a4", margin:(top:20mm,bottom:18mm,left:17mm,right:17mm), footer: context align(right, text(size:8pt, fill:rgb("#7b8494"))[MATHBANK STUDIO · #counter(page).display()]))
#let accent = rgb("'''+accent+'''")
#let choices(items) = layout(size => {
  let ws = items.map(it => measure(it).width)
  if calc.max(..ws) * 5 + 24pt < size.width { grid(columns: (1fr,1fr,1fr,1fr,1fr), gutter:4pt, ..items) }
  else if calc.max(..ws) * 3 + 16pt < size.width {grid(columns:(1fr,1fr,1fr),gutter:8pt,..items)}
  else {stack(spacing:5pt,..items)}
})
#let slot(body) = layout(size => {
 let h = measure(block(width:size.width, body)).height
 if h < 90mm {block(height:100mm,breakable:false,body)} else {block(breakable:true,body)}
})
#text(size:9pt,weight:"bold",fill:accent)['''+content_text(academy)+''']
#v(5pt)
#text(size:23pt,weight:"bold")['''+content_text(title)+''']
#v(7pt)
#text(size:9pt,fill:rgb("#667085"))['''+content_text(' · '.join(filter(None,[kind,exam['exam_date'],student,'초안 · 배부 전 검증 필요' if exam['status']=='draft' else ''])) )+''']
#v(9pt)
#line(length:100%,stroke:1.2pt + accent)
#v(12pt)
'''

    def exam(self,exam,kind,student=''):
        source=self.prelude(exam,student,{'questions':'문제지','answers':'빠른정답','solutions':'상세해설','workbook':'유형별 교재'}[kind])
        items=exam['items']
        if kind=='answers':
            cells=[]
            for item in items:
                q=item['snapshot'];a=q.get('answer') or {};cells.extend(['['+content_text(str(item['position']).zfill(2))+']','['+content_text(a.get('final_answer') or q.get('original_answer') or '미생성')+']'])
            source+='#table(columns:(1fr,2fr,1fr,2fr),inset:9pt,stroke:0.5pt + rgb("#dbe0e9"),'+','.join(cells)+')'
        else:
            columns=max(1,min(2,int(exam['settings'].get('columns',2))))
            source+='#columns('+str(columns)+',gutter:10mm)[\n'
            previous=None
            for item in items:
                q=item['snapshot'];a=q.get('answer') or {};num=item['position'];cl=q['classification']
                if kind=='workbook' and (cl['unit'],cl['type'])!=previous:
                    source+='#block(fill:rgb("#f0f2fa"),inset:8pt,width:100%)['+content_text(cl['unit']+' · '+cl['type'])+']\n\n';previous=(cl['unit'],cl['type'])
                heading='#block(breakable:false)[#text(weight:"bold",size:12pt,fill:accent)['+content_text(str(num).zfill(2))+'] #h(4pt) #text(size:8pt,fill:rgb("#747d90"))['+content_text(cl['unit']+'  ·  난이도 '+str(q['difficulty'])+'/10  ·  '+str(item['points'])+'점')+']\n\n'
                if kind=='solutions':
                    source+=heading+content_text('정답  '+(a.get('final_answer') or q.get('original_answer') or '미생성'))+']\n\n'
                    if a.get('verification')!='passed':source+=content_text('검증 보류 · '+a.get('reason','해설을 먼저 생성해 주세요.'))+'\n\n'
                    for step in a.get('steps',[]):source+='#text(weight:"bold",size:9pt,fill:accent)['+content_text(step['title'])+']\n\n'+self.blocks(step['blocks'])
                    source+='#v(10pt)\n'
                else:
                    body=self.blocks(q['body']['blocks'])
                    if q['body'].get('choices'):
                        choice_items=['['+content_text('①②③④⑤'[i]+' ')+self.blocks(c)+']' for i,c in enumerate(q['body']['choices'])]
                        body+='#choices(('+','.join(choice_items)+',))\n\n'
                    source+='#slot['+heading+']\n'+body+']\n'
            source+=']'
        return self.compile(source,kind)

    def compile(self,source,stem):
        file=self.directory/(stem+'.typ');file.write_text(source,encoding='utf-8')
        target=self.directory/(stem+'.pdf')
        try:typst.compile(str(file),output=str(target),root=str(self.directory),font_paths=[str(ASSETS/'fonts')],ignore_system_fonts=False)
        except Exception as exc:raise ValueError('PDF 조판 실패: '+str(exc)[:1200]) from exc
        return target

    def report(self,data):
        a=data['attempt'];exam=data['exam'];source=self.prelude(exam,a['name'],'학습 성적표')
        if a['state']=='absent':source+=content_text('미응시 · 점수와 정답률 집계에서 제외됩니다.');return self.compile(source,'report')
        source+='#grid(columns:(1fr,1fr,1fr),gutter:12pt,'
        for title,value in [('취득점수',f"{data['score']:g} / {data['maximum']:g}"),('정답 문항',f"{data['correct']} / {data['count']}"),('시험 난이도',f"{data['exam_difficulty']} / 10")]:
            source+='[ #block(fill:rgb("#f1f3fa"),radius:5pt,inset:12pt,width:100%)['+content_text(title)+'\n\n#text(size:19pt,weight:"bold")['+content_text(value)+']] ],'
        source+=')\n#v(15pt)\n'+content_text(a['school']+' · '+a['grade']+' · '+(a['class_name'] or '반 미지정')+' · '+str(a['round'])+'회차')+'\n\n'
        if data['pending']:source+=content_text('채점 대기 '+str(data['pending'])+'문항 · 현재 점수는 잠정치입니다.')+'\n\n'
        source+='#table(columns:(0.5fr,2fr,1fr,1fr,1fr),inset:6pt,stroke:0.4pt + rgb("#dbe0e9"),[번호],[단원 / 유형],[제출 답],[결과],[점수],'
        for item in data['items']:
            q=item['snapshot'];values=[str(item['position']),q['classification']['unit']+' / '+q['classification']['type'],item['submitted'],LABEL[item['status']],('—' if item['score'] is None else f"{item['score']:g}")+f" / {item['points']:g}"]
            source+=','.join('['+content_text(v)+']' for v in values)+','
        source+=')\n#v(15pt)\n#text(weight:"bold")[단원별 학습 기록]\n\n'
        for unit,g in data['groups']['unit'].items():
            rate=g['score']/g['maximum']*100
            source+=content_text(f"{unit} · {g['count']}문항 · 정답 {g['correct']}개 · 득점률 {rate:.1f}%")+'\n\n'
        weak=[unit for unit,g in data['groups']['unit'].items() if g['score']<g['maximum']]
        source+=content_text('다음 학습: '+(' / '.join(weak)+'의 오답·부분정답·무응답 문항을 다시 풀어 보세요.' if weak else '이번 시험의 모든 문항을 해결했습니다. 검증된 사고변형으로 개념을 확장해 보세요.'))+'\n\n'
        source+='#text(size:8pt,fill:rgb("#747d90"))['+content_text('표본 1명. 정답률=만점 문항 수/출제 문항 수. 득점률=취득점수/만점(부분점수 포함). 미응시는 제외. 시험 난이도는 문항 난이도의 단순평균이며 추정값입니다. 타 학교 예상점수는 비교 자료가 없어 산정하지 않습니다.')+']'
        return self.compile(source,'report')

def hwpx_exam(store,exam,target,kind='questions',student=''):
    from hwpx import HwpxDocument
    doc=HwpxDocument.new();doc.paragraphs[0].text=exam['settings'].get('academy','MATHBANK STUDIO')
    doc.add_paragraph().add_run(exam['title'],size=20,bold=True)
    doc.add_paragraph(' · '.join(filter(None,[{'questions':'문제지','answers':'빠른정답','solutions':'상세해설','workbook':'유형별 교재'}[kind],exam['exam_date'],student,'초안' if exam['status']=='draft' else ''])))
    def put(blocks,paragraph=None):
        p=paragraph
        for block in blocks:
            k=block['kind']
            if k in ('paragraph','box','note'):
                p=paragraph if paragraph is not None else doc.add_paragraph()
                put(block['blocks'],p)
                if paragraph is not None:p.add_run('\n')
                p=None
            elif k in ('text','math'):
                if p is None:p=doc.add_paragraph()
                if k=='text':p.add_run(block['value'])
                else:p.add_equation(to_eqedit(block))
            elif k=='image':
                src=store.path(block['path']);doc.add_picture(src.read_bytes(),src.suffix.lstrip('.'),width_mm=55);p=None
            elif k=='table':
                cols=max(sum(c.get('colspan',1) for c in r) for r in block['rows']);table=doc.add_table(len(block['rows']),cols,width=45000)
                for ri,row in enumerate(block['rows']):
                    ci=0
                    for cell in row:
                        span=cell.get('colspan',1)
                        if span>1 or cell.get('rowspan',1)>1:table.merge_cells(ri,ci,ri+cell.get('rowspan',1)-1,ci+span-1)
                        put(cell['blocks'],table.cell(ri,ci).paragraphs[0]);ci+=span
                p=None
            elif k=='unsupported':doc.add_paragraph('입력 보류: '+block['label']);p=None
    for item in exam['items']:
        q=item['snapshot'];a=q.get('answer') or {};doc.add_paragraph(f"{item['position']}.  [{item['points']:g}점]")
        if kind=='answers':doc.add_paragraph(a.get('final_answer') or q.get('original_answer') or '미생성')
        elif kind=='solutions':
            doc.add_paragraph('정답: '+(a.get('final_answer') or q.get('original_answer') or '미생성'))
            for step in a.get('steps',[]):doc.add_paragraph(step['title']);put(step['blocks'])
        else:
            put(q['body']['blocks'])
            for i,choice in enumerate(q['body'].get('choices',[])):
                p=doc.add_paragraph('①②③④⑤'[i]+' ');put(choice,p)
            doc.add_paragraph('\n\n')
    doc.save_to_path(target)
    # Structural reopen is a check, not a claim of Hancom round-trip compatibility.
    reopened=HwpxDocument.open(target)
    if not reopened.paragraphs:raise ValueError('생성한 HWPX를 다시 읽지 못했습니다.')
    return Path(target)

def export_packet(store,eid,kind='questions',student_id=None,fmt='pdf'):
    exam=store.exam(eid);student=next((s for s in store.students() if s['id']==student_id),None)
    student_name=student['name']+' · '+(student['class_name'] or '') if student else ''
    directory=store.root/'outputs'/identity();directory.mkdir()
    if fmt=='pdf':path=PDF(store,directory).exam(exam,kind,student_name)
    else:path=hwpx_exam(store,exam,directory/(kind+'.hwpx'),kind,student_name)
    with store.transaction() as db:
        db.execute('INSERT INTO exports VALUES(?,?,?,?,?,?,?)',(identity(),eid,student_id,kind,path.relative_to(store.root).as_posix(),checksum(path.read_bytes()),stamp()))
    return str(path)
