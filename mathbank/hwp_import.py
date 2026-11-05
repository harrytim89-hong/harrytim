"""HWP 5 input through audited native-record -> HWPX conversion.

The original is kept. A no-warning converter report alone is insufficient:
equation scripts, picture/table counts and note controls are compared separately.
This verifies structure, not Hancom visual fidelity or mathematical correctness.
"""
from collections import Counter
import json
import re
from pathlib import Path
import tempfile
from defusedxml import ElementTree as ET
from .store import digest, now, uid
from .hwpx import import_hwpx, local, source_result


def convert_audited(payload):
    from hwpx.hwp5.package import convert, to_hwpx_bytes
    from hwpx.hwp5 import records as rec
    from hwpx.hwp5.controls import EquationEdit
    from hwpx.hwp5.bodytext import split_text
    if len(payload) > 100_000_000: raise ValueError('HWP 크기 제한을 초과했습니다.')
    converted = convert(payload)
    if converted.report.unconverted or converted.report.dropped:
        raise ValueError('HWP 변환에서 보존하지 못한 요소가 있습니다. 한글에서 HWPX로 저장하세요: ' +
            json.dumps({'unconverted':converted.report.unconverted,'dropped':converted.report.dropped},ensure_ascii=False))
    records = [r for s in converted.source.sections for r in s.records]
    roots = [ET.fromstring(data) for name,data in converted.files.items() if name.startswith('Contents/section') and name.endswith('.xml')]
    native_scripts = [EquationEdit.decode(r.payload).script for r in records if r.tag==rec.EQEDIT]
    xml_scripts = [e.text or '' for root in roots for e in root.iter() if local(e.tag)=='script']
    if Counter(native_scripts) != Counter(xml_scripts): raise ValueError('HWP 수식 원문 대조 실패: 수식이 누락/변경되었습니다.')
    normalize=lambda value:re.sub(r'\s','',value)
    original_text=[]
    for r in records:
        if r.tag==rec.PARA_TEXT:
            chunks,malformed=split_text(r.payload)
            if malformed:raise ValueError('HWP 텍스트 제어 레코드가 손상되었습니다.')
            t=normalize(''.join(c.text for c in chunks if c.kind=='text'))
            if t:original_text.append(t)
    converted_text=[]
    for name,data in converted.files.items():
        if not name.startswith(('Contents/section','Contents/masterpage')) or not name.endswith('.xml'):continue
        root=ET.fromstring(data);parents={child:parent for parent in root.iter() for child in parent}
        paragraph_text={p:[] for p in root.iter() if local(p.tag)=='p'}
        for e in root.iter():
            if local(e.tag)!='t':continue
            owner=parents.get(e)
            while owner is not None and local(owner.tag)!='p':owner=parents.get(owner)
            if owner is not None:paragraph_text[owner].append(e.text or '')
        converted_text.extend(t for v in paragraph_text.values() if (t:=normalize(''.join(v))))
    if Counter(original_text)!=Counter(converted_text):raise ValueError('HWP 문단 텍스트 대조 실패: 한글에서 HWPX로 저장한 사본이 필요합니다.')
    counts = {'equations':len(native_scripts), 'pictures':sum(r.tag==rec.SHAPE_COMPONENT_PICTURE for r in records),
              'tables':sum(r.tag==rec.TABLE for r in records),
              'endnotes':sum(r.tag==rec.CTRL_HEADER and r.payload[:4]==b'  ne' for r in records)}
    xml_counts = Counter(local(e.tag) for root in roots for e in root.iter())
    for key,tag in [('pictures','pic'),('tables','tbl'),('endnotes','endNote')]:
        if counts[key] != xml_counts[tag]: raise ValueError('HWP 개체 수 대조 실패: ' + key)
    audit = {'converter':'python-hwpx 6.11.0', 'scope':'native-record structural audit; Hancom visual fidelity unverified',
             'source_sha256':digest(payload),'native_counts':counts,'equation_scripts_exact_match':True,
             'nonempty_text_paragraphs':len(original_text),'text_paragraph_multiset_match':True,
             'unconverted':dict(converted.report.unconverted),'dropped':dict(converted.report.dropped),
             'hancom_visual_verified':False,'created':now()}
    return to_hwpx_bytes(converted.files), audit


def import_hwp(store, path, course='', metadata=None, cancel=None, progress=None):
    path=Path(path)
    if path.stat().st_size > 100_000_000: raise ValueError('HWP 크기 제한을 초과했습니다.')
    payload=path.read_bytes();sha=digest(payload)
    with store.connect() as db:
        previous=db.execute('SELECT document_id FROM assets WHERE ref=?',('original-hwp:'+sha,)).fetchone()
    if previous:
        store.restore_trash('document',previous[0])
        info=source_result(store,previous[0])
        return dict(info['import_result'],added=False,conversion=info['metadata'].get('conversion'))
    if cancel and cancel.is_set(): raise ValueError('HWP 가져오기를 취소했습니다.')
    try:
        converted,audit=convert_audited(payload)
    except ValueError: raise
    except Exception as exc:
        raise ValueError('HWP 변환을 완료하지 못했습니다. 한글에서 HWPX로 저장한 사본이 필요합니다. ('+type(exc).__name__+')') from exc
    relative=f'sources/{sha}.hwp';(store.root/relative).write_bytes(payload)
    metadata=dict(metadata or {}, conversion=audit, original_name=path.name, original_path=relative)
    with tempfile.TemporaryDirectory(prefix='mathbank-hwp-') as temp:
        hwpx=Path(temp)/(path.stem+'.hwpx');hwpx.write_bytes(converted)
        result=import_hwpx(store,hwpx,course,metadata=metadata,cancel=cancel,progress=progress)
    with store.connect() as db:
        db.execute('INSERT OR IGNORE INTO assets VALUES(?,?,?,?,?,?)',(uid(),result['document_id'],'original-hwp:'+sha,'application/x-hwp',relative,sha))
        db.execute('UPDATE documents SET name=? WHERE id=?',(path.name,result['document_id']))
    result['conversion']=audit
    return result
