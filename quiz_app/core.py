"""문항 검증, JSON 저장, 무작위 출제와 채점."""
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Question:
    prompt: str
    choices: list[str]
    answer: int  # 1부터 시작하는 정답 번호
    explanation: str = ""

    def __post_init__(self):
        if not isinstance(self.prompt, str) or not self.prompt.strip():
            raise ValueError("문제 내용은 비워둘 수 없습니다.")
        if (not isinstance(self.choices, list) or len(self.choices) < 2
                or any(not isinstance(c, str) or not c.strip() for c in self.choices)):
            raise ValueError("비어 있지 않은 보기를 2개 이상 입력하세요.")
        if type(self.answer) is not int or not 1 <= self.answer <= len(self.choices):
            raise ValueError("정답 번호가 보기 범위를 벗어났습니다.")
        if not isinstance(self.explanation, str):
            raise ValueError("해설은 문자열이어야 합니다.")

    def is_correct(self, answer: int) -> bool:
        return type(answer) is int and answer == self.answer


def load_questions(path: Path) -> list[Question]:
    if not path.exists():
        return []
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(records, list):
            raise ValueError("최상위 데이터는 배열이어야 합니다.")
        return [Question(**record) for record in records]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"문제 파일 형식 오류: {path}: {exc}") from exc


def save_questions(path: Path, questions: list[Question]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # 완성된 파일로 교체하여 쓰기 도중 원본이 잘리는 것을 방지합니다.
    import os
    import tempfile
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         delete=False) as stream:
            temporary = Path(stream.name)
            json.dump([asdict(q) for q in questions], stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def select_questions(questions: list[Question], count: int) -> list[Question]:
    if not 1 <= count <= len(questions):
        raise ValueError(f"출제 수는 1~{len(questions)} 사이여야 합니다.")
    return random.sample(questions, count)
