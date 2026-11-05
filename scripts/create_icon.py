"""Render our newly drawn SVG into a Windows icon, using bundled Qt only."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import struct
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage,QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtCore import QBuffer,QIODevice
app=QApplication.instance() or QApplication([])
assets=Path(__file__).resolve().parents[1]/'studio/ui/assets';renderer=QSvgRenderer(str(assets/'mark.svg'));parts=[]
for size in (32,48,128,256):
    image=QImage(size,size,QImage.Format_ARGB32);image.fill(0);painter=QPainter(image);renderer.render(painter);painter.end();buffer=QBuffer();buffer.open(QIODevice.WriteOnly);image.save(buffer,'PNG');parts.append((size,bytes(buffer.data())))
offset=6+16*len(parts);headers=[]
for size,data in parts:headers.append(struct.pack('<BBBBHHII',size%256,size%256,0,0,1,32,len(data),offset));offset+=len(data)
(assets/'studio.ico').write_bytes(struct.pack('<HHH',0,1,len(parts))+b''.join(headers)+b''.join(data for _,data in parts))
