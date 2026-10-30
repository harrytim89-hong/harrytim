"""Persistent, bounded, per-page/per-question processing; no teacher approval state."""
import copy
import json
from pathlib import Path
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
import pymupdf
from .provider import ProviderError, Cancelled
from .validation import initial_stages, mark, validate_content, compare_readings, validate_reading

READ_PROMPT = r'''Perform a fresh independent reading of ONLY the source IMAGE.
Return {"text":string,"choices":[string],"uncertain":boolean}.
Preserve numbers, signs, exponents, conditions and choice order EXACTLY, using $LaTeX$ for math.
Exclude question numbering. Do not solve, classify, explain or reference any prior transcription.
Mark uncertain=true if any source content is unreadable. Diagram relations are checked separately.
'''

CONTENT_PROMPT = r'''Read the source exactly, preserving every number, sign, condition and choice order.
Do not invent illegible content. Return {"text": string, "choices": [string],
"diagram": [objects], "answer": string, "solution": [step strings], "course": string,
"unit": string, "level": integer 1..5, "reason": string, "uncertain": boolean}.
Use $LaTeX$ for math. Korean prose. Separate choices from text. No question numbering in text.
Diagram coordinates are 0..1000; types: line(x1,y1,x2,y2), circle(cx,cy,r),
text(x,y,label), polyline(points:[[x,y],...]). Preserve only observed relations.
If a diagram cannot be reconstructed faithfully set uncertain=true; never omit a visible diagram.
Solve step by step only within the given course. Lv1 direct formula, Lv2 familiar method,
Lv3 reorganizing conditions, Lv4 decisive nonstandard observation, Lv5 further deep reasoning.
If unreadable, uncertain=true. Do not fabricate an answer.'''


def crop(store, question, output, dpi=180):
    document = store.document(question["document_id"])
    from .store import digest
    if digest((store.root / document["path"]).read_bytes()) != document["hash"]:
        raise ValueError("원본 PDF 해시가 변경되었습니다. 새 자료로 등록하세요.")
    images = []
    with pymupdf.open(store.root / document["path"]) as pdf:
        for i, region in enumerate(question["regions"]):
            page = pdf[region["page"]]
            box = pymupdf.Rect(region["box"])
            if box.is_empty or not page.rect.contains(box):
                raise ValueError("문항 영역이 페이지 범위를 벗어났습니다.")
            path = Path(output) / f"crop-{i}.png"
            page.get_pixmap(clip=box, dpi=dpi).save(path)
            images.append(path)
    return images


class Pipeline:
    def __init__(self, store, provider, workers=1):
        self.store, self.provider = store, provider
        self.workers = max(1, min(2, workers))
        self.cancel = threading.Event()
        self.lock = threading.Lock()

    def enqueue_document(self, identifier):
        document = self.store.document(identifier)
        for page in range(document["pages"]):
            target = f"{identifier}:{page}"
            if not self.store.completed_page(target):
                self.store.enqueue("page", target)

    def run(self):
        if not self.lock.acquire(blocking=False):
            return
        self.cancel.clear()
        try:
            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                futures = [pool.submit(self.run_worker) for _ in range(self.workers)]
                for future in futures:
                    future.result()
        finally:
            self.lock.release()

    def run_worker(self):
        while not self.cancel.is_set():
            job = self.store.claim_job()
            if not job:
                return
            try:
                if job["kind"] == "page":
                    self.process_page(job)
                else:
                    self.process_question(job)
            except Cancelled as exc:
                self.store.job_status(job["id"], "cancelled", str(exc))
            except ProviderError as exc:
                self.store.job_status(job["id"], "paused", str(exc))
                self.cancel.set()
            except Exception as exc:
                self.store.job_status(job["id"], "exception", f"{type(exc).__name__}: {str(exc)[:300]}")

    def process_page(self, job):
        document_id, number = job["target"].rsplit(":", 1)
        if self.store.document_trashed(document_id):
            self.store.job_status(job['id'], 'cancelled', '삭제된 자료')
            return
        document = self.store.document(document_id)
        with tempfile.TemporaryDirectory() as temp:
            with pymupdf.open(self.store.root / document["path"]) as pdf:
                page = pdf[int(number)]
                image = Path(temp) / "page.png"
                page.get_pixmap(dpi=160).save(image)
                width, height = page.rect.width, page.rect.height
            result = self.provider.call('''Locate complete mathematical QUESTIONS only, exclude answers, headers and footers.
Return {"kind":"questions|blank|answers|uncertain", "regions":[{"number":string,
"box":[left,top,right,bottom]}], "reason":string}. Coordinates are normalized 0..1000.
Read columns in order. Include choices and figures. If a question crosses pages or shared context cannot
be included without ambiguity, kind=uncertain; do not silently truncate.''', [image], self.cancel)
            kind, regions = result.get("kind"), result.get("regions")
            if kind in ("blank", "answers"):
                self.store.job_status(job["id"], "skipped", f"페이지 역할: {kind}")
                return
            if kind != "questions" or not isinstance(regions, list) or not regions or len(regions) > 100:
                raise ValueError("경계 불명확 또는 문항 0개: " + str(result.get("reason", ""))[:200])
            for region in regions:
                box = region.get("box")
                if not isinstance(box, list) or len(box) != 4 or any(type(v) not in (int, float) for v in box) or not (0 <= box[0] < box[2] <= 1000 and 0 <= box[1] < box[3] <= 1000):
                    raise ValueError("AI 분리 좌표 오류")
            for region in regions:
                box = region["box"]
                identifier = self.store.add_question(document_id, [{"page": int(number), "box":
                    [box[0] * width / 1000, box[1] * height / 1000, box[2] * width / 1000, box[3] * height / 1000]}], str(region.get("number", "")))
                q = self.store.question(identifier)
                if q["stages"]["comparison"]["state"] != "passed":
                    self.store.enqueue("question", identifier, q["version"])
            self.store.job_status(job["id"], "done")

    def process_question(self, job):
        q = self.store.question(job["target"])
        if q["version"] != job["version"]:
            self.store.job_status(job["id"], "stale", "편집 후 이전 작업 무효화")
            return
        if self.store.is_trashed(q):
            self.store.job_status(job["id"], "cancelled", "삭제된 문항")
            return
        document = self.store.document(q["document_id"])
        stages = initial_stages()
        for key in stages:
            stages[key]["version"] = q["version"]
        mark(stages, "segmentation", "passed", q["version"])
        errors, candidate = [], q["content"]
        for attempt, (dpi, method) in enumerate([(180, "기본 영역 판독"), (260, "고해상도 독립 판독"), (320, "최대 확대 조건·부호 중심 판독")], 1):
            self.store.job_status(job["id"], "running", attempt=attempt, method=method)
            with tempfile.TemporaryDirectory() as temp:
                images = crop(self.store, q, temp, dpi)
                try:
                    candidate = copy.deepcopy(q["content"]) if q["user_modified"] else self.provider.call(
                        CONTENT_PROMPT + "\nCourse scope: " + document["course"] + "\nMethod: " + method, images, self.cancel)
                    validate_content(candidate)
                    if candidate.get("uncertain", True):
                        raise ValueError("원문 판독 또는 도형 재작성 불확실")
                    mark(stages, "transcription", "passed", q["version"])
                    independent = self.provider.call(READ_PROMPT, images, self.cancel)
                    validate_reading(independent)
                    issues = compare_readings(candidate, independent)
                    if independent.get("uncertain", True):
                        issues.append("독립 판독 불확실")
                    if issues:
                        raise ValueError("; ".join(issues))
                    review = self.provider.call('''Independently check this candidate against the ORIGINAL IMAGE.
Check conditions, signs, exponents, all choices, diagram relations, answer and every solution step.
Check course restrictions. Return {"source_ok":boolean,"diagram_ok":boolean,"answer_ok":boolean,
"solution_ok":boolean,"course_ok":boolean,"reasons":[string]}. Do not approve uncertain results.
Candidate: ''' + json.dumps(candidate, ensure_ascii=False), images, self.cancel)
                    for field in ("source_ok", "diagram_ok", "answer_ok", "solution_ok", "course_ok"):
                        if type(review.get(field)) is not bool:
                            raise ValueError("검사 응답 스키마 오류")
                    if not review["source_ok"] or not review["diagram_ok"]:
                        raise ValueError("원문·도형 대조 실패: " + str(review.get("reasons", [])))
                    mark(stages, "comparison", "passed", q["version"], "독립 전사 + 숫자·부호 검사 + 원본 영상 대조")
                    mark(stages, "diagram", "passed", q["version"])
                    for key, flag in (("answer", "answer_ok"), ("solution", "solution_ok"), ("classification", "course_ok")):
                        ok = review[flag] and (bool(candidate.get(key)) if key in ("answer", "solution") else bool(candidate.get("unit")))
                        mark(stages, key, "passed" if ok else "exception", q["version"], "AI 독립 검토; 도구 검산 미적용")
                    from .arithmetic import audit
                    calculation = audit(candidate.get("solution", []))
                    candidate["calculation_audit"] = calculation
                    if calculation["errors"]:
                        mark(stages, "solution", "exception", q["version"], "; ".join(calculation["errors"]))
                    error = "; ".join(k for k in stages if stages[k]["state"] == "exception")
                    if not self.save_result(q, candidate, stages, error):
                        self.store.job_status(job["id"], "stale", "편집 이후 도착한 결과를 폐기했습니다.")
                        return
                    self.store.job_status(job["id"], "done" if not error else "exception", error, attempt, method)
                    return
                except ValueError as exc:
                    errors.append({"attempt": attempt, "method": method, "reason": str(exc)[:500]})
                    self.store.put_record("attempt", {"question_id": q["id"], "version": q["version"], **errors[-1]})
        for key in ("comparison", "diagram"):
            mark(stages, key, "exception", q["version"], errors[-1]["reason"])
        self.save_result(q, candidate, stages, errors[-1]["reason"])
        self.store.job_status(job["id"], "exception", errors[-1]["reason"], 3, "자동 재처리 한도 도달")

    def save_result(self, q, candidate, stages, error):
        if self.store.is_trashed(q):
            return False
        if q["user_modified"]:
            # Update only checks, never user content. Version check remains atomic.
            with self.store.connect() as db:
                result = db.execute("UPDATE questions SET stages=?,error=? WHERE id=? AND version=?",
                           (json.dumps(stages), error, q["id"], q["version"]))
                return result.rowcount == 1
        else:
            return self.store.update_question(q["id"], q["version"], candidate, stages, error)
