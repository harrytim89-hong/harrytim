"""Offline interchange never grants a verification pass."""
import json
from pathlib import Path
import tempfile
import zipfile
from .store import digest
from .pipeline import crop, CONTENT_PROMPT
from .validation import validate_content, initial_stages


def identity(store, q):
    return {"question_id": q["id"], "version": q["version"],
            "source_hash": store.document(q["document_id"])["hash"],
            "regions_hash": digest(json.dumps(q["regions"], sort_keys=True).encode())}


def export_request(store, identifier, destination):
    q = store.question(identifier)
    with tempfile.TemporaryDirectory() as temp:
        images = crop(store, q, temp, dpi=260)
        request = dict(identity(store, q), prompt=CONTENT_PROMPT,
                       response_format={"identity": identity(store, q), "content": "Use the requested JSON content object here"})
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("request.json", json.dumps(request, ensure_ascii=False, indent=2))
            for image in images:
                archive.write(image, image.name)


def import_response(store, path):
    path = Path(path)
    if path.stat().st_size > 1_000_000:
        raise ValueError("응답 파일 크기 제한 초과")
    result = json.loads(path.read_text(encoding="utf-8"))
    q = store.question(result["identity"]["question_id"])
    if result["identity"] != identity(store, q):
        raise ValueError("문항 ID·원본 해시·입력 버전이 일치하지 않습니다.")
    if q["user_modified"]:
        raise ValueError("사용자 수정값이 있습니다. 가져오기로 덮어쓰지 않습니다.")
    content = validate_content(result["content"])
    stages = initial_stages()
    for value in stages.values():
        value["version"] = q["version"]
    if not store.update_question(q["id"], q["version"], content, stages, "가져온 결과: 독립 원본 검사 대기"):
        raise ValueError("문항이 변경되었습니다. 최신 요청 패키지를 사용하세요.")
    store.enqueue("question", q["id"], q["version"])
    return q["id"]
