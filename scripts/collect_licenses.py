"""License texts from the installed distribution metadata, no credentials/data."""
import importlib.metadata as metadata
import shutil
import sys
from pathlib import Path
target=Path(sys.argv[1]);target.mkdir(parents=True,exist_ok=True);index=[]
for dist in metadata.distributions():
    name=dist.metadata.get('Name','unknown');version=dist.version
    license_value=dist.metadata.get('License-Expression') or dist.metadata.get('License') or 'See bundled license'
    index.append(f'{name} {version}: {license_value}')
    for entry in dist.files or []:
        if any(word in str(entry).lower() for word in ('license','copying','notice','copyright')) and entry.suffix.lower() not in ('.py','.pyc','.pyd','.dll'):
            source=Path(dist.locate_file(entry))
            if source.is_file():
                dest=target/name/str(entry);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest)
font=Path(__file__).resolve().parents[1]/'studio/ui/assets/fonts/LICENSE.txt';shutil.copy2(font,target/'NotoSansCJK-LICENSE.txt')
python_license=Path(sys.base_prefix)/'LICENSE.txt'
if python_license.exists():shutil.copy2(python_license,target/'Python-LICENSE.txt')
(target/'INDEX.txt').write_text('\n\n'.join(sorted(index)),encoding='utf-8')
(target/'QT-NOTICE.txt').write_text('PySide6 / Qt 6.8.3: LGPLv3/GPL/commercial. This distribution dynamically links unmodified Qt DLLs. Users may replace the Qt/PySide libraries and debug modifications. Qt sources: https://download.qt.io/archive/qt/6.8/6.8.3/submodules/ . PySide sources: https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.8.3-src/ . Qt WebEngine includes Chromium third-party notices in QtWebEngineCore resources and Qt documentation. No PyMuPDF is used. Python PSF and bundled package license texts are included in this folder.',encoding='utf-8')
