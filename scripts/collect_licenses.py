"""Collect installed dependency license notices, never credentials or user data."""
from importlib.metadata import distributions
from pathlib import Path
import re
import shutil
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else 'artifacts/licenses')
root.mkdir(parents=True, exist_ok=True)
for distribution in distributions():
    name = re.sub(r'[^a-zA-Z0-9_.-]', '_', distribution.metadata['Name'])
    directory = root / name
    directory.mkdir(exist_ok=True)
    (directory / 'METADATA.txt').write_text(distribution.read_text("METADATA") or "", encoding='utf-8')
    for file in distribution.files or []:
        if any(term in file.name.lower() for term in ('license','copying','notice')) and file.suffix.lower() not in ('.py','.pyc'):
            source = Path(distribution.locate_file(file))
            if source.is_file() and source.stat().st_size < 2_000_000:
                target = directory / re.sub(r'[^a-zA-Z0-9_.-]', '_', str(file))
                shutil.copyfile(source, target)
