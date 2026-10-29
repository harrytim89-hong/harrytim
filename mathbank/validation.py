"""Conservative gates: source agreement never implies mathematical proof."""
import json
import re

STAGES = ("segmentation", "transcription", "diagram", "comparison", "answer", "solution", "classification")


def initial_stages():
    return {key: {"state": "pending", "version": 1, "reason": ""} for key in STAGES}


def mark(stages, key, state, version, reason=""):
    stages[key] = {"state": state, "version": version, "reason": reason}


def math_tokens(text):
    return re.findall(r"\d+(?:\.\d+)?|[+−\-*/=<>|^_]", text.replace(" ", ""))


def validate_content(content):
    if not isinstance(content, dict) or not isinstance(content.get("text"), str) or not content["text"].strip():
        raise ValueError("본문 전사 결과가 없습니다.")
    if len(json.dumps(content, ensure_ascii=False)) > 200_000:
        raise ValueError("문항 결과 크기 제한 초과")
    for key in ("choices", "solution"):
        if not isinstance(content.get(key), list) or any(not isinstance(s, str) for s in content[key]):
            raise ValueError(f"{key}는 문자열 배열이어야 합니다.")
    for key in ("answer", "unit", "course", "reason"):
        if not isinstance(content.get(key), str):
            raise ValueError(f"{key} 필드 형식 오류")
    if type(content.get("level")) is not int or content["level"] not in range(1, 6):
        raise ValueError("난이도는 Lv.1~5여야 합니다.")
    for text in [content["text"], *content["choices"], *content["solution"], content["answer"]]:
        if len(re.findall(r"(?<!\\)\$", text)) % 2:
            raise ValueError("수식 구분자 짝이 맞지 않습니다.")
    if type(content.get("uncertain")) is not bool:
        raise ValueError("판독 불확실성 필드가 필요합니다.")
    validate_diagram(content.get("diagram", []))
    return content


def validate_diagram(objects):
    if not isinstance(objects, list) or len(objects) > 500:
        raise ValueError("도형 객체 형식 오류")
    from math import isfinite
    fields = {"line": ("x1", "y1", "x2", "y2"), "circle": ("cx", "cy", "r"),
              "text": ("x", "y"), "polyline": ()}
    for item in objects:
        if not isinstance(item, dict) or item.get("type") not in fields:
            raise ValueError("지원하지 않는 도형 객체입니다.")
        for key in fields[item["type"]]:
            value = item.get(key)
            if type(value) not in (float, int) or not isfinite(value) or not 0 <= value <= 1000:
                raise ValueError("도형 좌표 범위 오류")
        if item["type"] == "text" and (not isinstance(item.get("label"), str) or len(item["label"]) > 200):
            raise ValueError("도형 라벨 오류")
        if item["type"] == "polyline":
            points = item.get("points")
            if not isinstance(points, list) or not 2 <= len(points) <= 500:
                raise ValueError("곡선 좌표 오류")
            for point in points:
                if not isinstance(point, list) or len(point) != 2 or any(type(v) not in (int, float) or not isfinite(v) or not 0 <= v <= 1000 for v in point):
                    raise ValueError("곡선 좌표 범위 오류")


def compare_readings(first, second):
    issues = []
    for key in ("text", "choices"):
        a = first[key] if key == "text" else "\n".join(first[key])
        b = second[key] if key == "text" else "\n".join(second[key])
        if math_tokens(a) != math_tokens(b):
            issues.append(f"{key}: 숫자·부호 불일치")
        if re.sub(r"\s", "", a) != re.sub(r"\s", "", b):
            issues.append(f"{key}: 독립 전사 불일치")
    return issues


def printable(question, kind="questions"):
    required = ["segmentation", "transcription", "diagram", "comparison"]
    if kind != "questions":
        required.append("answer")
    if kind == "solutions":
        required.append("solution")
    return all(question["stages"].get(k, {}).get("state") == "passed" and
               question["stages"][k].get("version") == question["version"] for k in required)


def invalidate_changes(old, new, stages, version):
    """Carry forward unrelated checks while invalidating dependent results."""
    import copy
    result = copy.deepcopy(stages)
    changed = {key for key in set(old) | set(new) if old.get(key) != new.get(key)}
    invalid = set()
    if changed & {'text', 'choices', 'diagram'}:
        invalid.update({'transcription', 'diagram', 'comparison', 'answer', 'solution', 'classification'})
    if 'answer' in changed:
        invalid.update({'answer', 'solution'})
    if 'solution' in changed:
        invalid.update({'solution', 'classification'})
    if changed & {'course', 'unit', 'level', 'reason'}:
        invalid.add('classification')
    for key in STAGES:
        if key in invalid:
            mark(result, key, 'pending', version, '관련 입력 변경')
        else:
            result[key]['version'] = version
    return result
