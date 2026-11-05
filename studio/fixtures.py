"""Newly authored, public-domain synthetic documents for repeatable checks.

Never contains a user's exam, answer sheet or student information.
"""
from pathlib import Path
import zipfile

def make_fixture(path,notes=False,objects=False):
    from hwpx import HwpxDocument
    doc=HwpxDocument.new();doc.paragraphs[0].text='MathBank Studio · 공개 검증용 자체 작성 자료'
    p=doc.add_paragraph('' if notes else '1. ')
    if notes:doc.notes.add_endnote('2',paragraph=p)
    doc.add_paragraph('다항식 A, B의 정의는 다음과 같다.')
    doc.add_paragraph().add_equation('A=3x^2+2x y-2y^2,~B=-x^2+3x y+4y^2')
    p=doc.add_paragraph('이때, ');p.add_equation('2A+B');p.add_run('를 계산하면? [5점]')
    choices=['4x^2+7xy','5x^2+7xy','5x^2+5xy+2y^2','7x^2+7xy','5x^2-xy']
    for i,script in enumerate(choices):
        p=doc.add_paragraph('①②③④⑤'[i]+' ');p.add_equation(script)
    p=doc.add_paragraph('' if notes else '2. ')
    if notes:doc.notes.add_endnote('2',paragraph=p)
    doc.add_paragraph('이차방정식')
    doc.add_paragraph().add_equation('x^2-6x+a-2=0')
    doc.add_paragraph('이 실근을 갖도록 하는 실수 a의 최댓값은? [5점]')
    for i,number in enumerate((10,11,12,13,14)):
        p=doc.add_paragraph('①②③④⑤'[i]+' ');p.add_equation(str(number))
    if objects:
        table=doc.add_table(2,2,width=30000)
        for row in range(2):
            for col in range(2):table.cell(row,col).text=f'조건 {row+1}-{col+1}'
        from PySide6.QtGui import QImage
        from PySide6.QtCore import QBuffer,QIODevice
        image=QImage(80,60,QImage.Format_RGB32);image.fill(0xff7788cc);buffer=QBuffer();buffer.open(QIODevice.WriteOnly);image.save(buffer,'PNG')
        doc.add_picture(bytes(buffer.data()),'png',width_mm=20)
    doc.save_to_path(path)
    return Path(path)

def native_fixture(hwpx_path,hwp_path):
    from hwpx.hwp5.writer import write_hwp5
    with zipfile.ZipFile(hwpx_path) as z:files={n:z.read(n) for n in z.namelist()}
    Path(hwp_path).write_bytes(write_hwp5(files))
    return Path(hwp_path)
