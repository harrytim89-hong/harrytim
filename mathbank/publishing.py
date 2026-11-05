"""Structured -> Typst PDF and editable native HWPX, with release gates."""
import json
from pathlib import Path
import re
import shutil
import tempfile
from .equations import Node, parse, from_latex, render
from .hwpx import plain, walk_blocks
from .validation import printable
from .store import digest, uid, now

FONTS = Path(__file__).parent / 'assets/fonts'


def text(value):
    return '#text(' + json.dumps(str(value), ensure_ascii=False) + ')'


def inline(value, target='typst'):
    result = []
    for part in re.split(r'(\$\$.*?\$\$|\$[^$]*\$)', str(value), flags=re.S):
        if part.startswith('$') and part.endswith('$') and len(part) > 1:
            tree = from_latex(part.strip('$'))
            result.append('$' + render(tree, target).strip() + '$' if target == 'typst' else ('equation', render(tree, target)))
        elif part:
            result.append(text(part) if target == 'typst' else ('text', part))
    return ''.join(result) if target == 'typst' else result


def check_exam(exam, kind):
    if kind not in ('questions', 'answers', 'solutions', 'textbook'):
        raise ValueError('출력 종류 오류')
    gate = 'questions' if kind == 'textbook' else kind
    if not exam.get('questions'):
        raise ValueError('출력할 문항이 없습니다.')
    for i, q in enumerate(exam['questions'], 1):
        if not printable(q, gate) and not exam.get('draft'):
            raise ValueError(f'{i}번: 입력/수학 검증을 통과하지 않았습니다. 사유: {q.get("error", "검증 대기")}')


def managed_asset(store, b):
    relative = b.get('path', '')
    if not re.fullmatch(r'assets/[a-f0-9]{64}\.[a-z0-9]{1,8}', relative):
        raise ValueError('허용되지 않은 그림 경로')
    path = store.root / relative
    if not path.is_file() or digest(path.read_bytes()) != b.get('hash'):
        raise ValueError('그림 파일 누락 또는 해시 불일치')
    return path


def block_typst(blocks, store, build):
    result = []
    for b in blocks:
        kind = b['type']
        if kind == 'text': result.append(text(b['text']))
        elif kind == 'equation':
            if not b.get('supported'): raise ValueError('미지원 수식은 PDF에서 누락하지 않습니다: ' + b.get('issue', ''))
            result.append('$' + render(Node.load(b['ast']), 'typst').strip() + '$')
        elif kind == 'paragraph':
            result.append(block_typst(b['children'], store, build) + '\n\n')
        elif kind in ('box', 'note'):
            result.append('#block(stroke: 0.5pt, inset: 5pt, width: 100%)[\n' + block_typst(b['children'], store, build) + '\n]')
        elif kind == 'table':
            if not b['rows']: continue
            columns = max(sum(c.get('colspan', 1) for c in row) for row in b['rows'])
            cells = []
            for row in b['rows']:
                for cell in row:
                    cells.append('#table.cell(colspan: ' + str(cell.get('colspan', 1)) + ', rowspan: ' + str(cell.get('rowspan', 1)) + ')[\n' + block_typst(cell['blocks'], store, build) + '\n]')
            result.append('#table(columns: ' + str(columns) + ', inset: 4pt, stroke: 0.4pt,\n' + ',\n'.join('[' + c + ']' for c in cells) + ')\n')
        elif kind == 'image':
            path = managed_asset(store, b)
            name = path.name
            if path.suffix.lower() == '.bmp':
                # Typst cannot decode BMP. Convert this one raster object
                # losslessly for rendering; keep the original asset unchanged.
                from PySide6.QtGui import QImage
                raster = QImage(str(path))
                name = path.stem + '.png'
                if raster.isNull() or not raster.save(str(build/name), 'PNG'):
                    raise ValueError('원본 BMP 그림을 출력용 PNG로 읽지 못했습니다.')
            else:
                shutil.copyfile(path, build / name)
            result.append('#align(center, image(' + json.dumps(name) + ', width: 80%))\n')
        else:
            raise ValueError('미지원 개체를 누락한 출력은 저장하지 않습니다: ' + str(b.get('role', kind)))
    return ''.join(result)


def settings_for(exam):
    defaults = {'academy': 'MATHBANK', 'subject': '수학', 'date': '', 'student': '', 'class': '',
                'font': 'Noto Sans CJK KR', 'font_size': 10, 'columns': 2, 'per_page': 4,
                'space_mm': 35, 'margin_mm': 16, 'gap_mm': 10, 'color': True}
    defaults.update(exam.get('output_settings', {}))
    for k, low, high in [('font_size', 8, 16), ('columns', 1, 2), ('per_page', 1, 10), ('space_mm', 0, 120), ('margin_mm', 10, 30), ('gap_mm', 4, 20)]:
        if type(defaults[k]) not in (int, float) or not low <= defaults[k] <= high:
            raise ValueError('출력 설정 범위 오류: ' + k)
    return defaults


def header(exam, kind, s):
    suffix = {'questions': '문제지', 'answers': '빠른정답', 'solutions': '상세해설', 'textbook': '유형별 교재'}[kind]
    return ('#text(size: 9pt, fill: accent)[' + text(s['academy'] + ' / ' + suffix) + ']\n'
        '#v(3mm)\n#text(size: 22pt, weight: "bold")[' + text(exam['title']) + ']\n#v(3mm)\n' +
        text(f"{s['subject']}   {s['date']}   {s['class']}   이름: {s['student'] or '________________'}") +
        '\n#v(4mm)\n#line(length: 100%, stroke: accent)\n#v(4mm)\n' +
        (text('초안 · 자동 배부 불가 · 미검증 항목 포함') + '\n\n' if exam.get('draft') else ''))


def typst_source(exam, kind, store, build):
    check_exam(exam, kind)
    s = settings_for(exam)
    accent = 'rgb("087e82")' if s['color'] else 'black'
    source = (f'#let accent = {accent}\n#set page(paper: "a4", margin: {s["margin_mm"]}mm, '
              'footer: context align(center, counter(page).display("1")))\n'
              '#set text(font: ' + json.dumps(s['font']) + f', size: {s["font_size"]}pt, lang: "ko")\n'
              '#set par(leading: 0.65em, justify: false)\n#set math.equation(numbering: none)\n' + header(exam, kind, s))
    questions = []
    last_group = None
    for i, q in enumerate(exam['questions'], 1):
        c = q['content']
        entry = '#block(breakable: false)[#text(weight: "bold", fill: accent)[' + text(f'{i:02d}') + '] ' + text(f"[{exam['points'][i-1]}점]   {c.get('unit', '미분류')} / 난이도 {c.get('difficulty', c.get('level', 3)*2)}/10") + ']\n'
        if not printable(q, 'questions' if kind == 'textbook' else kind):
            entry += '#block(fill: luma(94%), inset: 4pt)[' + text('검사 보류: ' + (q.get('error') or '정답·해설 검사 대기')) + ']\n'
        if kind in ('questions', 'textbook'):
            if c.get('blocks'):
                entry += block_typst(c['blocks'], store, build)
            else:
                entry += inline(c.get('text', '')) + '\n\n'
            if c.get('diagram'):
                from .output import svg
                name = f'diagram-{i}.svg'
                (build / name).write_text(svg(c['diagram']), encoding='utf-8')
                entry += '#image(' + json.dumps(name) + ', width: 65%)\n'
            if c.get('choices'):
                # Typst measures actual content width before selecting a 5/3/1 layout.
                items = ','.join('[' + text(str(n) + '. ') + inline(choice) + ']' for n, choice in enumerate(c['choices'], 1))
                entry += '#layout(size => { let opts = (' + items + ',); let w = size.width; '
                entry += 'let widest = calc.max(..opts.map(c => measure(c).width)); '
                entry += 'let cols = if widest * 5 + 16pt < w { 5 } else if widest * 3 + 8pt < w { 3 } else { 1 }; '
                entry += 'grid(columns: (1fr,) * cols, gutter: 4pt, ..opts) })\n'
            if kind == 'textbook':
                grouping = (c.get('unit'), c.get('type'))
                if grouping != last_group:
                    entry = '#heading(level: 2)[' + text(' / '.join(x or '미분류' for x in grouping)) + ']\n' + entry
                    last_group = grouping
            entry += f'#v({s["space_mm"]}mm)\n'
        else:
            entry += '#block(breakable: false)[' + text('정답: ') + inline(c.get('answer') or '미생성') + ']\n'
            if kind == 'solutions':
                steps = [text(f'{n}. ') + inline(step) for n, step in enumerate(c.get('solution', []), 1)]
                entry = '#block(breakable: false)[\n' + entry + ('\n\n' + steps[0] if steps else '') + '\n]\n'
                entry += '\n\n'.join(steps[1:]) + '\n'
        questions.append(entry)
    if kind in ('solutions', 'answers'):
        source += '#columns(2, gutter: ' + str(s['gap_mm']) + 'mm)[\n' + '\n#v(3mm)\n'.join(questions) + '\n]'
    else:
        # Continuous columns are safe for long questions. A preferred cell height
        # gives four short questions per A4; overflow flows without shrinking.
        per_col = max(1, int(s['per_page']) // int(s['columns']))
        minimum = max(0, (297 - 2*s['margin_mm'] - 64) / per_col)
        if kind == 'questions':
            questions = ['#layout(size => { let item = [\n' + q + '\n]; '
                'let measured = measure(block(width: size.width, item)).height; '
                'if measured > 180mm { block(breakable: true, item) } else { '
                'block(height: calc.max(' + str(minimum) + 'mm, measured), breakable: false, item) } })\n' for q in questions]
        source += f'#columns({int(s["columns"])}, gutter: {s["gap_mm"]}mm)[\n' + '\n'.join(questions) + '\n]'
    return source


def export_pdf(store, exam, destination, kind='questions', attempt_id=None):
    import typst
    destination = Path(destination)
    with tempfile.TemporaryDirectory(prefix='mathbank-typeset-') as directory:
        build = Path(directory)
        source = typst_source(exam, kind, store, build)
        entry = build / 'document.typ'
        entry.write_text(source, encoding='utf-8')
        # Compiler root contains only generated template and verified images.
        compiled = typst.compile(str(entry), root=str(build), font_paths=[str(FONTS)])
        if not compiled.startswith(b'%PDF'): raise ValueError('PDF 생성 실패')
        temporary = destination.with_suffix(destination.suffix + '.tmp')
        temporary.write_bytes(compiled)
        temporary.replace(destination)
    record_output(store, exam, kind + '_pdf', destination, attempt_id)
    return destination


def hwpx_add_inline(paragraph, value):
    for kind, part in inline(value, 'hwp'):
        if kind == 'equation': paragraph.add_equation(part)
        else: paragraph.add_run(part)


def hwpx_blocks(document, blocks, store, target=None):
    for b in blocks:
        kind = b['type']
        if kind == 'paragraph':
            para = target or document.add_paragraph('')
            hwpx_blocks(document, b['children'], store, para)
        elif kind in ('text', 'equation'):
            para = target or document.add_paragraph('')
            if kind == 'text': para.add_run(b['text'])
            else:
                # A draft may preserve an unsupported original EqEdit script as
                # an editable equation. It receives no mathematical pass.
                para.add_equation(render(Node.load(b['ast']), 'hwp') if b.get('supported') else b['source'])
        elif kind in ('note', 'box'):
            hwpx_blocks(document, b['children'], store)
        elif kind == 'table':
            if not b['rows']: continue
            if any(c.get('colspan', 1) != 1 or c.get('rowspan', 1) != 1 for r in b['rows'] for c in r):
                raise ValueError('병합 셀 HWPX 출력은 아직 지원하지 않습니다. PDF로 출력하세요.')
            columns = max(len(r) for r in b['rows'])
            table = document.add_table(len(b['rows']), columns, width=45000)
            for r, row in enumerate(b['rows']):
                for c, cell in enumerate(row):
                    paragraph = table.cell(r, c).paragraphs[0]
                    for block in cell['blocks']:
                        if block['type'] != 'paragraph': raise ValueError('중첩 표 출력 미지원')
                        hwpx_blocks(document, block['children'], store, paragraph)
        elif kind == 'image':
            path = managed_asset(store, b)
            document.add_picture(path.read_bytes(), path.suffix.lstrip('.'), width_mm=60)
        else: raise ValueError('미지원 개체 HWPX 출력: ' + b.get('role', kind))


def export_hwpx(store, exam, destination, kind='questions', attempt_id=None):
    from hwpx import HwpxDocument
    check_exam(exam, kind)
    doc = HwpxDocument.new()
    try:
        s = settings_for(exam)
        doc.paragraphs[0].text = exam['title']
        doc.add_paragraph(f"{s['academy']} / {s['subject']} / {s['date']} / {s['student']}")
        if exam.get('draft'): doc.add_paragraph('초안 · 검증 미완료 · 자동 배부 불가')
        for i, q in enumerate(exam['questions'], 1):
            c = q['content']
            doc.add_paragraph(f"{i}. [{exam['points'][i-1]}점]")
            if not printable(q, 'questions' if kind == 'textbook' else kind):
                doc.add_paragraph('검사 보류: ' + (q.get('error') or '정답·해설 검사 대기'))
            if kind in ('questions', 'textbook'):
                if c.get('blocks'): hwpx_blocks(doc, c['blocks'], store)
                else: hwpx_add_inline(doc.add_paragraph(''), c.get('text', ''))
                if c.get('diagram'): raise ValueError('구조화 도형의 네이티브 HWPX 출력은 미지원입니다. PDF로 출력하세요.')
                for n, choice in enumerate(c.get('choices', []), 1):
                    hwpx_add_inline(doc.add_paragraph(str(n) + ') '), choice)
                doc.add_paragraph('\n\n')
            else:
                hwpx_add_inline(doc.add_paragraph('정답: '), c.get('answer') or '미생성')
                if kind == 'solutions':
                    for n, step in enumerate(c.get('solution', []), 1):
                        hwpx_add_inline(doc.add_paragraph(f'{n}) '), step)
        destination = Path(destination)
        tmp = destination.with_suffix('.tmp.hwpx')
        try:
            doc.save_to_path(tmp)
            from hwpx.tools.package_validator import validate_package
            report = validate_package(tmp)
            if not report.ok:
                raise ValueError('HWPX 패키지 검사 실패: ' + str(report))
            tmp.replace(destination)
        finally:
            tmp.unlink(missing_ok=True)
    finally:
        doc.close()
    record_output(store, exam, kind + '_hwpx', destination, attempt_id)
    return destination


def record_output(store, exam, kind, path, attempt_id=None):
    path = Path(path)
    payload = path.read_bytes()
    relative = 'outputs/' + digest(payload) + path.suffix.lower()
    (store.root/'outputs').mkdir(exist_ok=True)
    (store.root/relative).write_bytes(payload)
    with store.connect() as db:
        exam_id = exam.get('id')
        if not exam_id or not db.execute('SELECT 1 FROM records WHERE id=?', (exam_id,)).fetchone(): return
        db.execute('INSERT INTO distributions VALUES(?,?,?,?,?,?,?)', (uid(), attempt_id, exam_id, kind,
                   relative, digest(payload), now()))


def report_typst(report):
    student, exam = report['student'], report['exam']
    source = '#set page(paper: "a4", margin: 16mm, footer: context align(center, counter(page).display()))\n#set text(font: "Noto Sans CJK KR", size: 10pt, lang: "ko")\n'
    source += '#text(size: 22pt, weight: "bold")[' + text(student['name'] + ' · 학습 성적표') + ']\n#v(4mm)\n'
    source += text(f"{student.get('school', '')} / {student.get('grade', '')}학년 / {student.get('class', '')} / {exam['title']}") + '\n\n'
    source += text(f"시행일: {exam.get('date', exam.get('output_settings', {}).get('date', '미상'))} / 응시 회차: {report.get('round', 1)}") + '\n\n'
    source += '#text(size: 20pt)[' + text(f"{report['earned']} / {report['possible']}점") + ']\n\n'
    source += text('득점률 = 취득점수 / 전체 배점(부분점수 반영). 정답률 = 완전 정답 문항 수 / 전체 문항 수. 미채점 포함 시 잠정 결과.') + '\n\n'
    correct = sum(g['status'] == 'O' for g in report['grades'])
    source += text(f"정답 {correct}/{len(report['grades'])}문항 · 채점 {report['graded']}문항 · 표본 1명 · 순위/백분위/다른 학교 예상점수: 산정 불가") + '\n\n'
    cells = [text(v) for v in ('번호', '단원 / 유형', '난이도', '답 / 결과', '점수')]
    for i, (q, g) in enumerate(zip(exam['questions'], report['grades']), 1):
        c = q['content']; d = c.get('difficulty', c.get('level', 3)*2)
        score = exam['points'][i-1] if g['status'] == 'O' else g.get('score', 0) if g['status'] == '부분점수' else 0
        cells.extend(text(v) for v in (str(i), c.get('unit', '미분류') + ' / ' + c.get('type', '미분류'),
            f"{d}/10 " + '●'*d + '○'*(10-d), str(g.get('answer', '')) + ' / ' + g['status'], f"{score}/{exam['points'][i-1]}"))
    source += '#table(columns: (0.5fr, 2fr, 2fr, 1.5fr, 0.8fr), inset: 4pt, stroke: 0.3pt,\n' + ',\n'.join('[' + c + ']' for c in cells) + ')\n\n'
    for key, value in report['matrix'].items():
        source += text(f"{key}: {value['earned']}/{value['possible']}점 · 미채점 {value['pending']}문항") + '\n\n'
    for key, title in [('weakness', '보완할 내용'), ('strength', '잘한 점'), ('summary', '총평 / 다음 과제')]:
        source += '#heading(level: 2)[' + text(title) + ']\n' + text(report.get('notes', {}).get(key, '기록 없음')) + '\n\n'
    return source


def export_report_pdf(store, report, destination):
    import typst
    with tempfile.TemporaryDirectory(prefix='mathbank-report-') as directory:
        p = Path(directory) / 'report.typ'
        p.write_text(report_typst(report), encoding='utf-8')
        data = typst.compile(str(p), root=directory, font_paths=[str(FONTS)])
        Path(destination).write_bytes(data)
    record_output(store, report['exam'], 'report_pdf', destination, report.get('attempt_id'))
    return Path(destination)


def export_class_reports(store, reports, destination):
    import pymupdf
    from .pdf_lock import PDF_LOCK
    if not reports: raise ValueError('출력할 성적표가 없습니다.')
    with tempfile.TemporaryDirectory(prefix='mathbank-class-') as temp, PDF_LOCK, pymupdf.open() as combined:
        for i, report in enumerate(reports):
            path = export_report_pdf(store, report, Path(temp)/f'{i}.pdf')
            with pymupdf.open(path) as pdf: combined.insert_pdf(pdf)
        combined.save(destination)
