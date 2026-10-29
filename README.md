# 문제 출제 프로그램

Python 3.10 이상에서 실행하는 한국어 객관식 퀴즈 CLI입니다.
외부 패키지 설치 없이 파이썬 표준 라이브러리만 사용합니다.
등록된 문제 은행에서 무작위로 출제하며, AI로 새 문항을 생성하지는 않습니다.

## 구조

```text
harrytim/
├── quiz_app/
│   ├── __init__.py
│   ├── __main__.py     # 명령줄 UI와 입력 처리
│   └── core.py         # 문항 모델, 저장, 출제, 채점
├── data/
│   └── questions.json  # 예제 문제 3개와 등록된 문제
├── tests/
│   └── test_quiz.py
├── .gitignore
└── README.md
```

## 실행

저장소 루트에서 실행하세요.

```bash
python3 -m quiz_app list
python3 -m quiz_app quiz --count 3
python3 -m quiz_app add
python3 -m unittest discover -s tests -v
```

`add`에서 문제, 보기, 정답 번호(1부터 시작), 해설을 입력하면 JSON에 저장합니다.
퀴즈는 중복 선택 없이 출제하며 각 답의 정오 여부와 최종 점수를 표시합니다.
출제 수는 저장된 문항 수 이하여야 합니다. Ctrl+C로 입력을 취소할 수 있습니다.

별도 문제 은행을 사용하려면 전역 옵션을 명령 앞에 지정하세요.

```bash
python3 -m quiz_app --data data/my_questions.json add
python3 -m quiz_app --data data/my_questions.json quiz --count 1
```

문제 은행에는 `prompt`(문제), `choices`(보기 배열), `answer`(정답 번호),
`explanation`(해설, 생략 가능)을 가진 객체를 배열로 저장합니다.
개인용 단일 프로세스 사용을 기본으로 하며 동시 편집은 지원하지 않습니다.
