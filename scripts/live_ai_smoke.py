"""Explicit live subscription test using synthetic data, never student data."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pymupdf
from mathbank.store import Store
from mathbank.provider import CodexProvider
from mathbank.pipeline import Pipeline
from mathbank.validation import printable

root = Path(__file__).resolve().parents[1] / 'artifacts' / 'live-ai'
root.mkdir(parents=True, exist_ok=True)
path = root / 'synthetic-question.pdf'
pdf = pymupdf.open()
page = pdf.new_page()
page.insert_text((70, 100), '1. Calculate 1 + 1.\n\nA. 1\nB. 2\nC. 3', fontsize=20)
pdf.save(path)
pdf.close()
store = Store(root / 'data')
document, _ = store.add_document(path, 'elementary arithmetic')
pipeline = Pipeline(store, CodexProvider(enabled=True,timeout=60))
pipeline.enqueue_document(document)
pipeline.run()
questions, total = store.questions()
result = {'fixture':'synthetic-question.pdf', 'input_pages':1, 'questions':total,
          'source_passed':sum(printable(q) for q in questions),
          'jobs':store.jobs(), 'note':'Synthetic simple arithmetic only. Not representative textbook accuracy.'}
(root / 'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False,indent=2))
sys.exit(0 if result['source_passed'] == 1 else 1)
