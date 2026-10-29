"""실행: python3 -m quiz_app [--data PATH] {list,add,quiz}"""
import argparse
from pathlib import Path

from .core import Question, load_questions, save_questions, select_questions

DEFAULT_DATA = Path(__file__).resolve().parent.parent / "data" / "questions.json"


def read_number(prompt: str, minimum: int, maximum: int) -> int:
    while True:
        try:
            value = int(input(prompt))
            if minimum <= value <= maximum:
                return value
        except ValueError:
            pass
        print(f"{minimum}~{maximum} 사이의 숫자를 입력하세요.")


def read_text(prompt: str) -> str:
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("내용을 입력하세요.")


def main() -> int:
    parser = argparse.ArgumentParser(description="객관식 문제 등록 및 무작위 출제")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA, help="문제 은행 JSON 경로")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="문제 목록")
    commands.add_parser("add", help="대화형 문제 등록")
    quiz = commands.add_parser("quiz", help="무작위 퀴즈 시작")
    quiz.add_argument("--count", type=int, default=3, help="출제 수 (기본: 3)")
    args = parser.parse_args()
    try:
        questions = load_questions(args.data)
        if args.command == "list":
            for i, question in enumerate(questions, 1):
                print(f"{i}. {question.prompt}")
            print(f"총 {len(questions)}문항")
        elif args.command == "add":
            prompt = read_text("문제: ")
            count = read_number("보기 개수 (2~10): ", 2, 10)
            choices = [read_text(f"보기 {i}: ") for i in range(1, count + 1)]
            answer = read_number("정답 번호: ", 1, count)
            explanation = input("해설 (생략 가능): ").strip()
            questions.append(Question(prompt, choices, answer, explanation))
            save_questions(args.data, questions)
            print("문제가 저장되었습니다.")
        else:
            if not questions:
                raise ValueError("문제 은행이 비어 있습니다. add로 문제를 등록하세요.")
            selected = select_questions(questions, args.count)
            score = 0
            for i, question in enumerate(selected, 1):
                print(f"\n[{i}/{len(selected)}] {question.prompt}")
                for number, choice in enumerate(question.choices, 1):
                    print(f"  {number}. {choice}")
                answer = read_number("답: ", 1, len(question.choices))
                correct = question.is_correct(answer)
                score += correct
                print("정답입니다!" if correct else f"오답입니다. 정답: {question.answer}")
                if question.explanation:
                    print(f"해설: {question.explanation}")
            print(f"\n결과: {score}/{len(selected)} ({score / len(selected):.0%})")
    except (OSError, ValueError) as exc:
        print(f"오류: {exc}")
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\n입력이 취소되었습니다.")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
