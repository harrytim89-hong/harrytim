"""Bounded HWPX input with explicit references, boundaries and provenance."""
from __future__ import annotations
import io
import posixpath
import re
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath
from defusedxml import ElementTree as ET
from .formula import equation, local
from .model import checksum, identity, encode, stamp, plain_text, paragraphs

LIMIT=100_000_000
SKIP={'secPr','linesegarray','colPr','header','footer','pageNum','pageHiding','pageBorderFill','lineNumber','bookmark','fieldBegin','fieldEnd'}
SHAPES={'line','ellipse','arc','polygon','curve','connectLine','ole','container','video','chart','textart'}
MARKERS='①②③④⑤'

def elements(node,name): return [n for n in node.iter() if local(n.tag)==name]
def node_text(node): return ''.join(n.text or '' for n in node.iter() if local(n.tag)=='t')

def read_package(path):
    path=Path(path); data=path.read_bytes()
    if len(data)>LIMIT: raise ValueError('원본 파일은 100MB 이하로 가져와 주세요.')
    audit={};converted=None
    if data.startswith(bytes.fromhex('d0cf11e0a1b11ae1')):
        from hwpx.hwp5.package import convert
        try:converted=convert(data)
        except Exception as exc:raise ValueError('HWP 변환에 실패했습니다. 암호·배포용·DRM 자료는 한글에서 보호를 해제한 HWPX로 저장해 주세요. 상세: '+str(exc)[:300]) from exc
        files=converted.files
        audit={'converter':'python-hwpx 6.11.0','unconverted':dict(converted.report.unconverted),'dropped':dict(converted.report.dropped)}
    elif zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            infos=z.infolist()
            if len(infos)>20000 or sum(i.file_size for i in infos)>LIMIT*5: raise ValueError('HWPX 압축 해제 크기 제한을 초과했습니다.')
            if len(set(i.filename for i in infos))!=len(infos): raise ValueError('중복 경로가 있는 HWPX입니다.')
            for i in infos:
                if i.flag_bits&1: raise ValueError('암호화된 자료는 한글에서 암호를 해제한 후 가져와 주세요.')
                if '\\' in i.filename or i.filename.startswith('/') or '..' in PurePosixPath(i.filename).parts: raise ValueError('안전하지 않은 HWPX 경로입니다.')
            files={i.filename:z.read(i) for i in infos}
    else: raise ValueError('HWP/HWPX 파일이 아닙니다. 한글에서 HWPX 형식으로 저장해 주세요.')
    if 'Contents/content.hpf' not in files: raise ValueError('문서 목차 content.hpf가 없습니다.')
    package=ET.fromstring(files['Contents/content.hpf'])
    manifest={}
    for item in elements(package,'item'):
        href=item.get('href','')
        if href in files: resolved=href
        else: resolved=posixpath.normpath(posixpath.join('Contents',href))
        if resolved not in files or resolved.startswith('../') or '\\' in resolved:
            raise ValueError('목록의 개체를 찾을 수 없습니다: '+href)
        manifest[item.get('id')]=resolved
    sections=[]
    for ref in elements(package,'itemref'):
        target=manifest.get(ref.get('idref'))
        if not target: raise ValueError('spine 문서 순서 참조가 잘못되었습니다.')
        root=ET.fromstring(files[target])
        if local(root.tag)=='sec': sections.append((target,root))
    if not sections: raise ValueError('문서 목차에 본문 구역이 없습니다.')
    if converted:
        from hwpx.hwp5 import records as rec
        from hwpx.hwp5.controls import EquationEdit
        from hwpx.hwp5.bodytext import split_text
        # RecordStream.records already includes every level (children also point
        # at those same records). Walking children here would count them twice.
        records=[r for s in converted.source.sections for r in s.records]
        native_math=Counter(EquationEdit.decode(r.payload).script for r in records if r.tag==rec.EQEDIT)
        xml_math=Counter(n.text or '' for _,root in sections for n in elements(root,'script'))
        native_text=Counter()
        for r in records:
            if r.tag==rec.PARA_TEXT:
                chunks,_=split_text(r.payload)
                value=' '.join(''.join(c.text for c in chunks if c.kind=='text').split())
                if value: native_text[value]+=1
        xml_text=Counter()
        for _,root in sections:
            for p in elements(root,'p'):
                value=' '.join(''.join(n.text or '' for run in p if local(run.tag)=='run' for n in run if local(n.tag)=='t').split())
                if value: xml_text[value]+=1
        audit['formula_preserved']=native_math==xml_math
        audit['text_preserved']=native_text==xml_text
        audit['native_formulas']=sum(native_math.values()); audit['native_text_paragraphs']=sum(native_text.values())
        audit['native_tables']=sum(r.tag==rec.TABLE for r in records)
        audit['native_pictures']=sum(r.tag==rec.SHAPE_COMPONENT_PICTURE for r in records)
        audit['objects_preserved']=(audit['native_tables']==sum(len(elements(root,'tbl')) for _,root in sections) and audit['native_pictures']==sum(len(elements(root,'pic')) for _,root in sections))
    return data,files,manifest,sections,audit

class Decoder:
    def __init__(self,store,files,manifest,answer_notes=False):
        self.store,self.files,self.manifest=store,files,manifest
        self.answer_notes=answer_notes;self.issues=[]

    def issue(self,node,reason):
        self.issues.append({'reason':reason,'object':local(node.tag),'id':node.get('id')})
        return {'kind':'unsupported','label':reason,'xml':ET.tostring(node,encoding='unicode')}

    def parse(self,node):
        tag=local(node.tag)
        if tag in SKIP: return []
        if tag=='t':
            text=node.text or ''
            for child in node:
                text+= ('\t' if local(child.tag)=='tab' else '\n' if local(child.tag)=='lineBreak' else '')+(child.tail or '')
            return [{'kind':'text','value':text}] if text else []
        if tag=='equation':
            scripts=elements(node,'script');script=scripts[0].text if scripts else ''
            try: result=equation(script or '')
            except Exception as exc:
                return [self.issue(node,'수식 해석 보류: '+str(exc)[:180])]
            result['source_object']=node.get('id'); return [result]
        if tag=='p':
            children=[b for c in node if local(c.tag)=='run' for b in self.parse(c)]
            return [{'kind':'paragraph','blocks':children,'style':node.get('styleIDRef'),'paragraph_id':node.get('id')}] if children else []
        if tag in ('endNote','footNote'):
            if self.answer_notes: return []
            return [{'kind':'note','number':node.get('number'),'blocks':[b for c in node for b in self.parse(c)]}]
        if tag=='tbl':
            rows=[]
            for tr in node:
                if local(tr.tag)!='tr': continue
                row=[]
                for tc in tr:
                    if local(tc.tag)!='tc': continue
                    span=next(iter(elements(tc,'cellSpan')),None)
                    blocks=[b for sub in tc if local(sub.tag)=='subList' for b in self.parse(sub)]
                    row.append({'blocks':blocks,'colspan':int(span.get('colSpan','1')) if span is not None else 1,'rowspan':int(span.get('rowSpan','1')) if span is not None else 1})
                rows.append(row)
            result=[{'kind':'table','rows':rows}]
            for caption in node:
                if local(caption.tag)=='caption':result.extend(b for sub in caption if local(sub.tag)=='subList' for b in self.parse(sub))
            return result
        if tag=='rect':
            draw=elements(node,'drawText')
            if not draw: return [self.issue(node,'텍스트가 없는 도형의 관계를 확인해 주세요.')]
            return [{'kind':'box','blocks':[b for n in draw for sub in n if local(sub.tag)=='subList' for b in self.parse(sub)]}]
        if tag=='pic':
            refs=elements(node,'img')
            ref=refs[0].get('binaryItemIDRef') if refs else None
            path=self.manifest.get(ref)
            if not path: return [self.issue(node,'그림의 원본 참조를 찾을 수 없습니다.')]
            suffix=Path(path).suffix.lower()
            if suffix not in ('.png','.jpg','.jpeg','.bmp','.gif'): return [self.issue(node,'미지원 그림 형식: '+suffix)]
            data=self.files[path]
            if len(data)>20_000_000: return [self.issue(node,'그림이 20MB를 초과했습니다.')]
            relative=self.store.blob(data,'assets',suffix)
            return [{'kind':'image','asset_id':checksum(data),'path':relative,'source_ref':ref,'source_part':path,'hash':checksum(data),'alt':'원본 그림'}]
        if tag in SHAPES: return [self.issue(node,'도형 관계를 자동 해석할 수 없습니다: '+tag)]
        if tag=='autoNum':
            if node.get('numType') in ('PAGE','ENDNOTE','FOOTNOTE'): return []
            return [{'kind':'text','value':node.get('num','')+'. '}]
        if tag in ('run','ctrl','subList'):
            return [b for child in node for b in self.parse(child)]
        return [self.issue(node,'미지원 본문 개체: '+tag)]

def choice_split(blocks):
    content=[];choices=[];current=None
    for block in blocks:
        if block['kind']!='paragraph':
            (current if current is not None else content).append(block);continue
        before=[]
        for inline in block['blocks']:
            if inline['kind']=='text':
                pieces=re.split('(['+MARKERS+'])',inline['value'])
                for text in pieces:
                    if text in MARKERS and len(text)==1:
                        expected=MARKERS[len(choices)] if len(choices)<5 else None
                        if text!=expected: return blocks,[],['객관식 보기 번호가 연속되지 않습니다.']
                        current=[];choices.append(current)
                    elif text:
                        (current if current is not None else before).append({'kind':'text','value':text})
            else: (current if current is not None else before).append(inline)
        if before: content.append({**block,'blocks':before})
    if choices and len(choices)!=5: return blocks,[],['객관식 보기 5개를 확인하지 못했습니다.']
    return content,choices,[]

def classify(body,metadata):
    text=plain_text(body['blocks'])
    unit='미분류';kind='미분류';difficulty=5
    if any(w in text for w in ('다항식','나머지','이차식')): unit='다항식';kind='다항식의 연산' if '연산' in text or 'A' in text and 'B' in text else '나머지정리'
    if any(w in text for w in ('방정식','중근','실근','최댓값','최솟값')): unit='방정식과 부등식';kind='방정식과 실근'
    if any(w in text for w in ('복소수','허수','켤레')) or 'i =' in text and '\\sqrt' in text: unit='복소수';kind='복소수의 연산'
    if '판매액' in text:unit='방정식과 부등식';kind='이차함수의 활용'
    if '원기둥' in text:unit='기하';kind='입체도형의 부피'
    if '자연수' in text:kind='정수 조건 탐색';difficulty=7
    if body['answer_format']=='short': difficulty=7
    return {'course':metadata.get('course','미상'),'unit':unit,'type':kind,'certainty':'suggested','basis':'본문 어휘에 의한 자동 제안'},difficulty

def detach_original_points(blocks):
    points=None
    for block in blocks:
        if block['kind']!='paragraph':continue
        runs=block['blocks']
        values=[b['value'] if b['kind']=='text' else b.get('latex','') if b['kind']=='math' else '\ufffc' for b in runs]
        match=re.search(r'\s*\[(\d+(?:\.\d+)?)\s*점\]\s*$',''.join(values))
        if not match:continue
        points=float(match[1]);remaining=len(match[0])
        while remaining and runs:
            b=runs[-1];value=values.pop()
            if len(value)<=remaining:remaining-=len(value);runs.pop()
            elif b['kind']=='text':b['value']=value[:-remaining];remaining=0
            else:break
    return points

def import_document(store,path,progress=lambda *args:None,cancel=lambda:False):
    path=Path(path)
    data,files,manifest,sections,audit=read_package(path)
    digest=checksum(data)
    existing=store.rows('SELECT id,trashed FROM documents WHERE hash=?',(digest,))
    if existing:
        return {'document_id':existing[0]['id'],'duplicate':True,'message':'같은 원본이 이미 자료실에 있습니다. 휴지통에 있다면 복구해 주세요.'}
    original=store.blob(data,'originals',path.suffix)
    memory=io.BytesIO()
    with zipfile.ZipFile(memory,'w',zipfile.ZIP_DEFLATED) as z:
        for name,value in files.items(): z.writestr(name,value)
    rendition=store.blob(memory.getvalue(),'renditions','.hwpx')
    source_paragraphs=[(part,index,p) for part,root in sections for index,p in enumerate(root) if local(p.tag)=='p']
    anchors=[]
    for i,(_,_,p) in enumerate(source_paragraphs):
        notes=elements(p,'endNote')
        if len(notes)!=1:continue
        # Only a standalone anchor; a normal prose endnote is never a question boundary.
        outside=''.join(n.text or '' for run in p if local(run.tag)=='run' for n in run if local(n.tag)=='t').strip()
        if not outside or re.fullmatch(r'\[서답형\s*\d+\]',outside):
            anchors.append((i,int(notes[0].get('number','0')),notes[0]))
    all_text=''.join(node_text(root) for _,root in sections)
    note_profile=len(anchors)>=2 and [a[1] for a in anchors]==list(range(1,len(anchors)+1)) and all(m in all_text for m in MARKERS)
    if note_profile:
        boundaries=anchors;profile='standalone-sequential-answer-endnotes'
    else:
        candidates=[]
        for i,(_,_,p) in enumerate(source_paragraphs):
            # Remove notes before looking for a leading number; decimal answers are not prefixes.
            text=''.join(n.text or '' for run in p if local(run.tag)=='run' for n in run if local(n.tag)=='t')
            match=re.match(r'^\s*(\d{1,3})[.)]\s+',text)
            auto=[n for n in elements(p,'autoNum') if n.get('numType') not in ('PAGE','ENDNOTE','FOOTNOTE')]
            if match or auto: candidates.append((i,int(match[1]) if match else int(auto[0].get('num','0')),None))
        valid=len(candidates)>=2 and [a[1] for a in candidates]==list(range(1,len(candidates)+1))
        if not valid: raise ValueError('문항 경계를 안전하게 확인하지 못했습니다. 문항 첫 문단을 “1. ”, “2. ”처럼 연속 번호로 지정한 HWPX로 저장해 주세요. 원본은 변경하지 않았습니다.')
        styles=[(source_paragraphs[a[0]][2].get('styleIDRef'),source_paragraphs[a[0]][2].get('paraPrIDRef')) for a in candidates]
        boundaries=candidates;profile='sequential-numbered-paragraphs'
        if len(set(styles))>1: profile+='-mixed-styles'
    header_text=[]
    for _,root in sections:
        for head in elements(root,'header'): header_text.extend((n.text or '').strip() for n in elements(head,'t') if n.text)
    metadata={'certainty':'confirmed_from_header','header_fields':header_text}
    for value in header_text:
        if value.endswith('학교'): metadata['school']=value
        if re.fullmatch(r'\d{4}년',value):metadata['year']=value[:-1]
        if re.fullmatch(r'\d학년',value):metadata['grade']=value
        if re.fullmatch(r'\d학기',value):metadata['semester']=value
        if value in ('중간고사','기말고사'):metadata['exam']=value
        if value in ('공통수학1','공통수학2','대수','미적분','확률과 통계'):metadata['course']=value
    did=identity();questions=[]
    global_problem=bool(audit.get('unconverted') or audit.get('dropped')) or any(audit.get(k) is False for k in ('formula_preserved','text_preserved','objects_preserved'))
    for offset,(start,number,note) in enumerate(boundaries):
        if cancel(): raise InterruptedError('가져오기를 취소했습니다. 저장된 문항은 없습니다.')
        end=boundaries[offset+1][0] if offset+1<len(boundaries) else len(source_paragraphs)
        decoder=Decoder(store,files,manifest,note_profile)
        blocks=[]
        for part,idx,p in source_paragraphs[start:end]:
            text=node_text(p).strip()
            if text=='정답 및 해설':break
            blocks.extend(decoder.parse(p))
        if not note_profile and blocks and blocks[0]['kind']=='paragraph':
            first=blocks[0]['blocks']
            if first and first[0]['kind']=='text': first[0]['value']=re.sub(r'^\s*\d{1,3}[.)]\s+','',first[0]['value'],count=1)
        if note_profile and blocks and blocks[0]['kind']=='paragraph':
            if re.fullmatch(r'\[서답형\s*\d+\]',plain_text(blocks[:1]).strip()): blocks.pop(0)
        blocks,choices,choice_issues=choice_split(blocks)
        original_points=detach_original_points(blocks)
        issues=decoder.issues+[{'reason':v} for v in choice_issues]
        if global_problem:issues.append({'reason':'HWP 변환 전후 구조 대조에서 확인이 필요합니다.','audit':audit})
        if 'mixed-styles' in profile: issues.append({'reason':'문항 첫 문단의 스타일이 서로 달라 경계를 확인해 주세요.'})
        body={'blocks':blocks,'choices':choices,'answer_format':'mc' if choices else 'short'}
        original_answer=None;original_steps=[]
        if note is not None:
            answer_decoder=Decoder(store,files,manifest,False)
            note_blocks=[b for c in note for b in answer_decoder.parse(c)]
            text=plain_text(note_blocks).strip().replace('$','')
            original_answer=text.strip()
            if len(text)>100 or '\n' in text: issues.append({'reason':'미주의 정답/해설 경계를 확인해 주세요.'})
        classification,difficulty=classify(body,metadata)
        questions.append({'body':body,'source':{'document_id':did,'number':number,'original_points':original_points,'part':source_paragraphs[start][0],'paragraph_start':source_paragraphs[start][1],'paragraph_end':source_paragraphs[end-1][1],'profile':profile,'answer_origin':'original_endnote' if original_answer else None},'classification':classification,'difficulty':difficulty,'input_state':'held' if issues else 'complete','issues':issues,'original_answer':original_answer,'original_steps':original_steps})
        progress(offset+1,len(boundaries),f'{number}번 문항 구조 분석')
    report={'profile':profile,'total':len(questions),'complete':sum(q['input_state']=='complete' for q in questions),'held':sum(q['input_state']!='complete' for q in questions),'audit':audit,'formulas':sum(b['kind']=='math' for q in questions for blocks in (q['body']['blocks'],*[c for c in q['body']['choices']]) for b in paragraphs(blocks)),'answer_count':sum(bool(q['original_answer']) for q in questions)}
    with store.transaction() as db:
        db.execute('INSERT INTO documents(id,hash,name,path,rendition,metadata,report,created) VALUES(?,?,?,?,?,?,?,?)',(did,digest,path.name,original,rendition,encode(metadata),encode(report),stamp()))
        ids=[store.insert_question(db,q,did) for q in questions]
    return {'document_id':did,'question_ids':ids,**report}
