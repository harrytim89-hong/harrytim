# 수학비서 · MathBank Studio

![한 문제씩 분리된 문항 DB 화면 · 자체 작성 검증용 자료](docs/images/studio.png)

Windows 개인 수학 문제은행을 **빈 프로젝트에서 새로 구현한 독립 프로그램**입니다. 이전 프로그램의 모듈·화면·DB·빌드 산출물을 사용하지 않습니다.

문제 HWPX/HWP → 구조화 문항 → 별도 정답·해설 생성과 검증 → 숫자·사고변형 → 학생별 시험 → PDF/HWPX → 채점·오답 과제·성적표를 로컬 SQLite 자료실에서 연결합니다.

**현재 소스: 1.4.0** — 동일·유사 검색, 문항 비교·교체, 학교 범위 필터, 교사 코멘트, 문항 은행 UI를 추가했습니다. 이 소스의 Windows 실행파일은 Windows CI 검사를 거쳐 생성합니다. 기존 공개 배포본 다운로드는 [Releases](https://github.com/harrytim89-hong/harrytim/releases)에서 `MathBankStudio-1.3.0-Windows-x64.zip`을 받으세요. 압축 전체를 풀고 `MathBankStudio.exe`를 실행합니다. 실행하면 **문항 DB**가 열립니다. **자료 가져오기**를 누르면 문제 하나당 카드 하나로 표시하며, 각 문항을 독립적으로 열기·파일 저장·시험에 담기 할 수 있습니다. 단원과 난이도로 거를 수 있고 여러 문항을 선택해 문항별 HWPX/PDF 파일을 ZIP으로 저장할 수 있습니다. Windows는 소프트웨어 렌더링을 기본 사용하며 상단 **화면 복구** 메뉴는 웹 화면과 독립적으로 작동합니다. Python·한글 설치 없이 일반 PDF 출력과 채점이 동작합니다.

- [한국어 사용 설명](docs/사용설명.md)
- [지원 범위와 검증 한계](docs/SUPPORT.md)
- [새 구현 검증 기록](docs/VALIDATION.md)

개발 실행(Python 3.12):

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.lock
.venv\Scripts\python launch_studio.py
```

Windows 빌드: `./scripts/build_windows.ps1`. 자동 검사: `python -m pytest -q`. 패키지 전체 검사: `MathBankStudio.exe --self-test`.

앱의 새 자료실은 `%LOCALAPPDATA%\MathBankStudio`입니다. `--workspace "다른폴더"`로 분리할 수 있습니다. 원본 시험·정답·학생 DB는 이 저장소와 배포 파일에 포함하지 않습니다. AI 연결은 선택 사항이며 Codex CLI 또는 로컬 Ollama를 명시적으로 선택합니다.
