# MathBank Desktop

수학 문제은행 데스크톱 앱 개발판입니다. **아직 Windows EXE 완성품은 아닙니다.**

- [사용 안내](docs/USER_GUIDE_KO.md)
- [요구별 구현·검증·미완료 상태](docs/IMPLEMENTATION_STATUS.md)
- [Windows 수용 검사](docs/WINDOWS_ACCEPTANCE.md)
- [의존성 라이선스](docs/THIRD_PARTY.md)
- [개발 인계](HANDOFF.md)

Python 3.12 개발 환경에서 `pip install -r requirements.lock` 후 `python -m mathbank`로 실행합니다.
테스트는 `python -m pytest -q`입니다. Windows 빌드용 구성은 `scripts/build_windows.ps1`입니다.
운영 데이터는 `%LOCALAPPDATA%\MathBankDesktop` 또는 `MATHBANK_DATA`에 저장합니다.

기존 CLI는 아래 명령으로 계속 사용할 수 있습니다.

---

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
