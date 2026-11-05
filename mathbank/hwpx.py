"""Bounded ZIP/XML HWPX reader, reference-aware assets, conservative segmentation.

No HWP/PDF conversion and no AI is used to save an imported question.
"""
import copy
import json
import posixpath
import re
import zipfile
from pathlib import Path, PurePosixPath
from defusedxml import ElementTree as ET
from . import equations
from .store import digest, now, uid
from .validation import initial_stages, mark

NUMBER = re.compile(r"^\s*(?:\[\s*(\d{1,4})\s*\]|(\d{1,4})[.)])\s*")
CHOICE = re.compile(r"([①②③④⑤])\s*")


def local(tag):
    return tag.rsplit('}', 1)[-1]


def attr(element, name, default=''):
    return next((v for k, v in element.attrib.items() if local(k) == name), default)


class Package:
    def __init__(self, path):
        self.zip = zipfile.ZipFile(path)
        try:
            infos = self.zip.infolist()
            names = [i.filename for i in infos]
            if len(names) != len(set(names)) or len(names) > 10000:
                raise ValueError("HWPX에 중복 항목이 있거나 파일 수 제한을 초과했습니다.")
            if sum(i.file_size for i in infos) > 250_000_000 or any(i.file_size > 30_000_000 for i in infos):
                raise ValueError("HWPX 압축 해제 크기 제한을 초과했습니다.")
            if any('\\' in n or n.startswith('/') or '..' in PurePosixPath(n).parts for n in names):
                raise ValueError("HWPX 내부 경로가 안전하지 않습니다.")
            if 'Contents/content.hpf' not in names:
                raise ValueError("HWPX content.hpf가 없습니다. HWP 확장자를 바꾸지 말고 한글에서 HWPX로 저장하세요.")
            self.names = set(names)
            if 'mimetype' not in self.names or self.zip.read('mimetype').strip() != b'application/hwp+zip':
                raise ValueError('HWPX mimetype이 올바르지 않습니다. 한글에서 HWPX로 저장하세요.')
            self.hpf = self.xml('Contents/content.hpf')
            self.manifest = {}
            for e in self.hpf.iter():
                if local(e.tag) == 'item':
                    identifier, href = attr(e, 'id'), attr(e, 'href')
                    resolved = posixpath.normpath(posixpath.join('Contents', href))
                    # Hancom also uses package-root paths such as BinData/image1.png.
                    target = href if href in self.names else resolved
                    if target not in self.names or target.startswith('../') or ':' in target:
                        raise ValueError(f"HWPX manifest 참조가 없습니다: {href}")
                    if identifier in self.manifest:
                        raise ValueError("HWPX manifest ID 중복")
                    self.manifest[identifier] = (target, attr(e, 'media-type'))
            self.sections = []
            for e in self.hpf.iter():
                if local(e.tag) != 'itemref':
                    continue
                ref = attr(e, 'idref')
                if ref not in self.manifest:
                    raise ValueError("HWPX spine 참조 오류")
                target = self.manifest[ref][0]
                if re.search(r'(?:^|/)section[^/]*\.xml$', target, re.I):
                    self.sections.append(target)
            if not self.sections:
                raise ValueError("HWPX spine에서 본문 구역을 찾지 못했습니다.")
            self.header = next((p for p, _ in self.manifest.values() if p.endswith('/header.xml')), None)
            self.styles, self.paras = {}, {}
            if self.header:
                for e in self.xml(self.header).iter():
                    if local(e.tag) == 'style':
                        self.styles[attr(e, 'id')] = attr(e, 'name')
                    elif local(e.tag) == 'paraPr':
                        self.paras[attr(e, 'id')] = ET.tostring(e, encoding='unicode')
        except Exception:
            self.zip.close()
            raise

    def xml(self, path):
        data = self.zip.read(path)
        if len(data) > 20_000_000:
            raise ValueError("HWPX XML 크기 제한")
        return ET.fromstring(data)

    def close(self):
        self.zip.close()


def plain(blocks):
    out = []
    for b in blocks:
        kind = b['type']
        if kind == 'text':
            out.append(b['text'])
        elif kind == 'equation':
            out.append('$' + b.get('latex', b['source']) + '$')
        elif kind == 'paragraph':
            out.append(plain(b['children']) + '\n')
        elif kind == 'table':
            out.append('\n'.join(' | '.join(plain(c['blocks']) for c in r) for r in b['rows']) + '\n')
        elif 'children' in b:
            out.append(plain(b['children']) + '\n')
    return ''.join(out)


def walk_blocks(blocks):
    for b in blocks:
        yield b
        yield from walk_blocks(b.get('children', []))
        for row in b.get('rows', []):
            for cell in row:
                yield from walk_blocks(cell['blocks'])


def parse_paragraph(p, locator, assets):
    issues = []
    def read(e, depth=0):
        if depth > 50:
            raise ValueError("HWPX 개체 중첩 제한")
        kind = local(e.tag)
        if kind == 't':
            result = []
            if e.text:
                result.append({'type': 'text', 'text': e.text})
            for c in e:
                ck = local(c.tag)
                result.append({'type': 'text', 'text': '\n' if ck == 'lineBreak' else '\t' if ck == 'tab' else ''.join(c.itertext())})
                if c.tail:
                    result.append({'type': 'text', 'text': c.tail})
            return result
        if kind == 'equation':
            script = next((x.text or '' for x in e.iter() if local(x.tag) == 'script'), '')
            b = equations.block(script)
            b['raw_xml'] = ET.tostring(e, encoding='unicode')
            if not b['supported']:
                issues.append(b['issue'])
            return [b]
        if kind == 'pic':
            ref = next((attr(x, 'binaryItemIDRef') for x in e.iter() if attr(x, 'binaryItemIDRef')), '')
            asset = assets.get(ref)
            b = {'type': 'image', 'ref': ref, 'raw_xml': ET.tostring(e, encoding='unicode')}
            if asset:
                b.update(asset)
                if asset['kind'] not in ('image/png', 'image/jpeg', 'image/gif', 'image/bmp'):
                    issues.append('미지원 그림 형식: ' + asset['kind'])
                # Cropping/rotation/shape effects are preserved in XML but not normalized yet.
                crops = [x for x in e.iter() if local(x.tag) == 'imgClip']
                if any(any(attr(x, k, '0') != '0' for k in ('left', 'top')) for x in crops):
                    issues.append('그림 자르기 배치 확인 필요')
            else:
                issues.append('그림 참조 누락: ' + ref)
            return [b]
        if kind == 'tbl':
            rows = []
            for row in (x for x in e if local(x.tag) == 'tr'):
                cells = []
                for cell in (x for x in row if local(x.tag) == 'tc'):
                    blocks = []
                    for sub in cell:
                        if local(sub.tag) == 'subList':
                            for para in sub:
                                if local(para.tag) == 'p':
                                    b, errors = parse_paragraph(para, locator, assets)
                                    blocks.append(b)
                                    issues.extend(errors)
                    span = next((x for x in cell if local(x.tag) == 'cellSpan'), None)
                    cells.append({'blocks': blocks, 'colspan': int(attr(span, 'colSpan', '1')) if span is not None else 1,
                                  'rowspan': int(attr(span, 'rowSpan', '1')) if span is not None else 1})
                rows.append(cells)
            return [{'type': 'table', 'rows': rows, 'raw_xml': ET.tostring(e, encoding='unicode')}]
        if kind in ('footNote', 'endNote', 'drawText'):
            content = []
            for sub in e.iter():
                if local(sub.tag) == 'subList':
                    for para in sub:
                        if local(para.tag) == 'p':
                            b, errors = parse_paragraph(para, locator, assets)
                            content.append(b)
                            issues.extend(errors)
            return [{'type': 'note' if kind != 'drawText' else 'box', 'role': kind,
                     'children': content, 'raw_xml': ET.tostring(e, encoding='unicode')}]
        if kind in ('line', 'ellipse', 'polygon', 'arc', 'curve', 'connectLine', 'ole', 'chart', 'video', 'container'):
            issues.append('미지원 개체: ' + kind)
            return [{'type': 'unsupported', 'role': kind, 'raw_xml': ET.tostring(e, encoding='unicode')}]
        if kind == 'rect':
            texts = [x for x in e.iter() if local(x.tag) == 'drawText']
            if texts:
                return [b for x in texts for b in read(x, depth + 1)]
            issues.append('미지원 사각형 도형')
            return [{'type': 'unsupported', 'role': kind, 'raw_xml': ET.tostring(e, encoding='unicode')}]
        if kind in ('secPr', 'linesegarray', 'autoNum', 'newNum', 'pageNum', 'colPr', 'header', 'footer',
                    'bookmark', 'fieldBegin', 'fieldEnd', 'ctrlPr'):
            return []
        if kind in ('run', 'ctrl', 'subList', 'p'):
            return [b for child in e for b in read(child, depth + 1)]
        # Unknown run children are preserved and held instead of silently dropped.
        issues.append('미지원 XML 개체: ' + kind)
        return [{'type': 'unsupported', 'role': kind, 'raw_xml': ET.tostring(e, encoding='unicode')}]
    children = [b for c in p for b in read(c)]
    return {'type': 'paragraph', 'children': children, 'location': locator,
            'style_id': attr(p, 'styleIDRef'), 'para_pr': attr(p, 'paraPrIDRef'),
            'raw_xml': ET.tostring(p, encoding='unicode')}, list(dict.fromkeys(issues))


def classify(text, course=''):
    unit = next((name for key, name in [('방정식', '방정식'), ('함수', '함수'), ('확률', '확률'),
                  ('집합', '집합'), ('미분', '미분'), ('적분', '적분'), ('삼각', '삼각비와 삼각함수'),
                  ('수열', '수열'), ('다항식', '다항식')] if key in text), '미분류')
    if '복소수' in text or re.search(r'\bi\s*=\s*\\sqrt',text): unit='복소수'
    elif '나머지' in text and '다항식' in text: unit='나머지정리'
    elif '판매액' in text and '최대' in text: unit='이차함수'
    return {'course': course, 'unit': unit, 'type': '미분류', 'difficulty': 5,
            'classification_origin': {'kind': 'rule_proposal', 'confirmed': False}, 'level': 3}


def note_question_profile(paragraphs):
    """Recognize an exam made of standalone sequential endnote anchors.

    Ordinary inline foot/endnotes are NOT treated as answers. Each eligible
    anchor must occupy its own paragraph, and the document must contain choices.
    """
    anchors = [p for p in paragraphs if p.get('endnote') is not None]
    if len(anchors) < 2: return False
    numbers = [attr(p['endnote'], 'number') for p in anchors]
    if numbers != [str(n) for n in range(1, len(anchors)+1)]: return False
    for p in anchors:
        other = [b for b in p['block']['children'] if b['type'] != 'note']
        t = plain(other).strip()
        if t and not re.fullmatch(r'\[서답형\s*\d+\]', t): return False
    return sum(bool(CHOICE.match(p['text'].strip())) for p in paragraphs) >= len(anchors)


def import_hwpx(store, path, course='', rule=None, metadata=None, cancel=None, progress=None):
    path = Path(path)
    if path.stat().st_size > 100_000_000:
        raise ValueError("HWPX 원본 크기 제한을 초과했습니다.")
    payload = path.read_bytes()
    sha = digest(payload)
    with store.connect() as db:
        old = db.execute('SELECT id FROM documents WHERE hash=?', (sha,)).fetchone()
        if old:
            store_id = old[0]
    if old:
        store.restore_trash('document', store_id)
        with store.connect() as db:
            row = db.execute('SELECT import_result FROM source_info WHERE document_id=?', (store_id,)).fetchone()
        return dict(json.loads(row[0]) if row else {}, document_id=store_id, added=False)
    try:
        pkg = Package(path)
    except zipfile.BadZipFile as exc:
        raise ValueError('HWPX ZIP 구조를 읽지 못했습니다. 파일 손상 여부와 실제 HWPX 형식을 확인하세요.') from exc
    try:
        identifier = uid()
        rule = rule or {'number_style': 'coherent', 'start': 1}
        assets = {}
        for ref, (name, media) in pkg.manifest.items():
            if media.startswith('image/') or name.lower().startswith('bindata/'):
                data = pkg.zip.read(name)
                suffix = PurePosixPath(name).suffix.lower().lstrip('.')
                suffix = suffix if re.fullmatch('[a-z0-9]{1,8}', suffix) else 'bin'
                relative = f'assets/{digest(data)}.{suffix}'
                (store.root / 'assets').mkdir(exist_ok=True)
                (store.root / relative).write_bytes(data)
                assets[ref] = {'asset_id': uid(), 'path': relative, 'hash': digest(data), 'kind': media or 'application/octet-stream'}
        paragraphs = []
        for section in pkg.sections:
            root = pkg.xml(section)
            for index, p in enumerate(c for c in root if local(c.tag) == 'p'):
                b, issues = parse_paragraph(p, {'section': section, 'paragraph': index, 'object_id': attr(p, 'id')}, assets)
                text = plain([b])
                m = NUMBER.match(text)
                auto = next((x for x in p.iter() if local(x.tag) == 'autoNum' and attr(x, 'numType') in ('PARAGRAPH', 'NUMBER')), None)
                number = (m.group(1) or m.group(2)) if m else attr(auto, 'num') if auto is not None else ''
                style_name = pkg.styles.get(b['style_id'], '')
                paragraphs.append({'block': b, 'issues': issues, 'text': text, 'number': number,
                                   'prefix': m.end() if m else 0, 'auto': auto is not None,
                                   'style_name': style_name,
                                   'endnote': next((x for x in p.iter() if local(x.tag) == 'endNote'), None)})
        if note_question_profile(paragraphs):
            rule = dict(rule, boundary='standalone-sequential-endnote', answer_link='direct-endnote-reference')
            for p in paragraphs:
                note = p['endnote']
                if note is not None:
                    notes = [b for b in p['block']['children'] if b['type'] == 'note' and b.get('role') == 'endNote']
                    p['number'] = attr(note, 'number')
                    p['auto'] = True
                    p['prefix'] = 0
                    p['answer_note'] = notes[0] if len(notes) == 1 else None
                    p['block']['children'] = [b for b in p['block']['children'] if b not in notes]
                    label = plain(p['block']['children']).strip()
                    p['source_label'] = label or p['number']
                    if re.fullmatch(r'\[서답형\s*\d+\]', label):
                        p['block']['children'] = []
                    p['text'] = plain([p['block']])
                elif p['text'].strip() == '정답 및 해설':
                    p['end_marker'] = True
        candidates = [p for p in paragraphs if p['number']]
        signatures = {(p['block']['style_id'], p['block']['para_pr']) for p in candidates}
        nums = [int(p['number']) for p in candidates]
        coherent = len(nums) >= 2 and nums == list(range(nums[0], nums[0] + len(nums))) and len(signatures) == 1
        groups, current = [], None
        for p in paragraphs:
            if cancel and cancel.is_set():
                raise ValueError('가져오기를 취소했습니다. 저장 전이므로 다시 가져올 수 있습니다.')
            if p.get('end_marker'):
                if current: groups.append(current)
                current = None
                break
            if p['number']:
                if current:
                    groups.append(current)
                boundary_ok = p['auto'] or bool(re.search('문항|문제|Question', p['style_name'], re.I)) or coherent or rule.get('number_style') == 'explicit'
                current = {'number': p['number'], 'blocks': [], 'issues': [] if boundary_ok else ['문항 시작 경계 확인 필요'], 'prefix': p['prefix'],
                           'answer_note': p.get('answer_note'), 'source_label': p.get('source_label', p['number'])}
            if current is None and (p['text'].strip() or p['block']['children']):
                current = {'number': '', 'blocks': [], 'issues': ['번호 없는 공통지문/문항 경계 확인 필요'], 'prefix': 0}
            if current:
                current['blocks'].append(p['block'])
                current['issues'].extend(p['issues'])
        if current:
            groups.append(current)
        if not groups:
            raise ValueError('본문 문항이 없습니다.')
        relative = f'sources/{sha}.hwpx'
        (store.root / relative).write_bytes(payload)
        result = {'document_id': identifier, 'added': True, 'saved': len(groups), 'ready_input': 0,
                  'held': 0, 'failed': 0, 'issues': [], 'question_ids': []}
        with store.connect() as db:
            db.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?)', (identifier, path.name, sha, relative, len(pkg.sections), course, now()))
            for ref, a in assets.items():
                db.execute('INSERT INTO assets VALUES(?,?,?,?,?,?)', (a['asset_id'], identifier, ref, a['kind'], a['path'], a['hash']))
            for i, group in enumerate(groups):
                content = {'format': 'structured-v2', 'blocks': group['blocks'], 'choices': [], 'diagram': [],
                           'answer': '', 'solution': [], 'uncertain': bool(group['issues']), 'reason': 'HWPX 구조 분류 제안',
                           'source': {'document_id': identifier, 'number': group['number'], 'metadata': metadata or {},
                                      'location': group['blocks'][0]['location']},
                           'origins': {'problem': {'kind': 'source', 'document_id': identifier},
                                       'answer': {'kind': 'missing'}, 'solution': {'kind': 'missing'}},
                           'storage_status': 'saved', 'input_status': 'held' if group['issues'] else 'complete',
                           'answer_status': 'missing', 'solution_status': 'missing', 'verification_status': 'unverified'}
                # Remove only a real numbering prefix from the first text node; raw XML retains it.
                if group['prefix']:
                    remaining = group['prefix']
                    for b in walk_blocks(group['blocks']):
                        if b['type'] == 'text' and remaining:
                            cut = min(remaining, len(b['text']))
                            b['text'] = b['text'][cut:]
                            remaining -= cut
                # Choice paragraphs retain structured content; strings are an auxiliary index.
                kept, choice_blocks = [], []
                for b in content['blocks']:
                    t = plain([b]).strip()
                    if CHOICE.match(t):
                        segments = CHOICE.split(t)
                        content['choices'].extend(segments[j+1].strip() for j in range(1, len(segments), 2))
                        choice_blocks.append(b)
                    else:
                        kept.append(b)
                content['blocks'], content['choice_blocks'] = kept, choice_blocks
                note = group.get('answer_note')
                if note:
                    # The answer is bound to its own control, never matched by
                    # a bare question number from another document.
                    answer = plain(note['children']).strip()
                    if content['choices'] and not re.fullmatch('[1-5①②③④⑤]', answer):
                        group['issues'].append('미주 객관식 정답 형식 확인 필요')
                    elif answer and '\n' not in answer and len(answer) <= 100:
                        answer = str('①②③④⑤'.index(answer)+1) if answer in '①②③④⑤' else answer
                        content['answer'] = answer
                        content['answer_status'] = 'provided'
                        content['origins']['answer'] = {'kind':'source_quick_answer', 'document_id':identifier,
                            'control':'endNote', 'number':group['number'], 'location':group['blocks'][0]['location']}
                    else:
                        group['issues'].append('미주 정답/해설 범위 확인 필요')
                    content['source_answer_note'] = note
                content['source']['label'] = group.get('source_label', group['number'])
                content['input_status'] = 'held' if group['issues'] else 'complete'
                content['uncertain'] = bool(group['issues'])
                content['text'] = plain(kept).strip() or '(본문 없는 개체 문항)'
                content.update(classify(content['text'], course))
                stages = initial_stages()
                for key in ('segmentation', 'transcription', 'diagram', 'comparison', 'classification'):
                    mark(stages, key, 'passed' if not group['issues'] else 'exception', 1, 'HWPX 구조 보존' if not group['issues'] else '; '.join(group['issues']))
                qid = uid()
                db.execute("INSERT INTO questions VALUES(?,?,1,?,?,?,?,0,?,?)", (qid, identifier,
                    json.dumps([b['location'] for b in group['blocks']], sort_keys=True), group['number'],
                    json.dumps(content, ensure_ascii=False), json.dumps(stages), '; '.join(dict.fromkeys(group['issues'])), now()))
                result['question_ids'].append(qid)
                result['held' if group['issues'] else 'ready_input'] += 1
                if group['issues']:
                    result['issues'].append({'number': group['number'], 'reasons': list(dict.fromkeys(group['issues'])), 'location': content['source']['location']})
                if progress:
                    progress(i + 1, len(groups))
            db.execute('INSERT INTO source_info VALUES(?,?,?,?,?)', (identifier, 'hwpx', json.dumps(metadata or {}, ensure_ascii=False),
                       json.dumps(result, ensure_ascii=False), json.dumps(rule, ensure_ascii=False)))
        return result
    finally:
        pkg.close()


def source_result(store, document_id):
    with store.connect() as db:
        row = db.execute('SELECT * FROM source_info WHERE document_id=?', (document_id,)).fetchone()
    return {k: json.loads(row[k]) if k in ('metadata', 'import_result', 'rule') else row[k] for k in row.keys()} if row else {}
