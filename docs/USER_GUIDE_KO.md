# MathBank Desktop 0.2.1 사용 안내

현재 개발판입니다. Windows EXE 포함 배포 폴더가 GitHub Actions에서 생성되고 자동 실행 검사를 통과했습니다.
[Windows 빌드 목록](https://github.com/harrytim89-hong/harrytim/actions/workflows/windows-build.yml)에서
가장 최근 성공 실행의 Artifacts → `MathBankDesktop-Windows-x64`를 내려받으세요.
GitHub 로그인이 필요합니다. 최신 배포 ZIP을 전체 압축 해제한 뒤 `MathBankDesktop.exe`를 실행합니다.
`_internal` 폴더를 삭제하거나 EXE만 따로 옮기지 마세요. 일반 사용자 PC에는 Python·Node 설치가 필요하지 않습니다.
설치 마법사(Inno Setup)와 실제 Windows 10/11 사용자 PC 검사는 아직 미완료입니다.

## 기본 흐름

1. **PDF 자료실 → PDF 등록**에서 자료와 교재 과정을 입력합니다.
2. **AI · 백업 설정**에서 공식 Codex CLI의 ChatGPT 로그인 상태를 진단합니다.
   연결 사용을 켠 경우에만 AI 요청이 실행됩니다. 별도 유료 API 자동 전환은 없습니다.
3. 자료를 선택하고 **자동 처리 시작**을 누릅니다. 페이지별 분리 후 문항별 전사·독립 대조·답/풀이 검사를 예약합니다.
4. 작업 큐에서 진행·예외·사유를 확인합니다. 인증·한도·네트워크 오류는 일시정지됩니다.
   연결을 해결한 뒤 재개할 수 있습니다. 교사 승인 버튼은 없습니다.
5. 보관함에서 Ctrl/Shift로 문항들을 선택한 후 시험지 화면에서 생성합니다.
   예외가 있으면 완료 문항만 사용 / 예외 표시 초안 / 재처리 중 선택합니다.
6. 문제지·빠른답·상세 해설은 별도로 미리보기·PDF 저장·프린터 출력합니다.
   PDF 저장은 수식과 글꼴 렌더링이 완료된 뒤 가능합니다.
7. 학생을 등록하고 시험지를 선택한 후 학생 화면에서 과제를 배정합니다.
   채점에서 미채점과 미응답을 구분하고, 분석·강점·총평을 입력해 성적표를 저장합니다.

## 편집과 오프라인 기능

- PDF 자료실의 영역 직접 추가에서 드래그로 문항 영역을 만들 수 있습니다.
- 문제 보관함에서 원본·편집을 열면 본문, 보기, 정답, 풀이와 도형 JSON을 편집할 수 있습니다.
- 수식은 `$x^2$`, 분수는 `$\frac{1}{2}$`처럼 입력합니다. 미리보기에서 오류를 확인하세요.
- 지원 도형은 line/circle/text/polyline입니다. 현재 JSON 좌표 편집이며 시각적 도형 편집기는 미완료입니다.
- AI 연결이 없어도 자료 등록·수동 편집·기존 출력·학생·채점·백업을 사용할 수 있습니다.
  검사 미완료 문항은 예외 표시 초안으로 출력할 수 있습니다.
- 문항을 선택한 뒤 요청 패키지 ZIP을 내보내면 원본 크롭과 요청 형식이 포함됩니다.
  결과 JSON 가져오기는 ID/원본 해시/버전을 검사하고 독립 검사 대기로 저장합니다.
- DOCX는 편집 가능한 Word 수식 객체를 포함합니다. 도형이 있으면 현재 내보내기를 중단하고 이유를 알려줍니다.
  한글에서의 호환성은 아직 검증되지 않았습니다.

## 운영 데이터·백업

기본 위치는 Windows `%LOCALAPPDATA%\MathBankDesktop`입니다.
`MATHBANK_DATA`로 다른 운영 데이터 폴더를 지정할 수 있습니다.
설치 파일 위치와 운영 데이터는 분리됩니다. 원본 PDF는 `sources`, 기록은 SQLite에 저장됩니다.

진행 작업을 마친 뒤 설정의 백업 ZIP 저장을 사용하세요. 원본과 DB·파일 해시를 함께 보관합니다.
복원은 새 폴더에만 수행하며 현재 운영 폴더를 덮어쓰지 않습니다.
복원된 폴더로 전환하려면 앱을 종료하고 `MATHBANK_DATA`를 복원 경로로 설정합니다.
백업에는 학생 기록이 들어 있으므로 안전한 개인 보관 위치를 사용하세요.

## 개발 실행 및 Windows 빌드 담당자 안내

일반 사용자는 최종 배포 폴더의 MathBankDesktop.exe를 실행하는 구조입니다.
아래 명령은 **개발·빌드 담당자용**이며 최종 사용자 설치 절차를 대신하지 않습니다.

```text
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.lock
.venv\Scripts\python -m mathbank
```

Windows x64 + Python 3.12 빌드 환경에서 `scripts/build_windows.ps1`을 실행합니다.
성공 시 `dist/MathBankDesktop/MathBankDesktop.exe`와 배포 ZIP이 생성됩니다.
전체 폴더가 필요하며 EXE 한 파일만 옮기면 안 됩니다.
설치 파일은 Inno Setup 6에서 `scripts/installer.iss`를 컴파일합니다.
PyInstaller 빌드와 EXE 실행 검사는 Windows CI에서 통과했습니다. Inno Setup 컴파일·설치는 아직 미검증입니다.

Codex CLI는 앱에 인증 정보를 넣어 배포하지 않습니다. 공식 배포 및 ChatGPT 로그인은
https://developers.openai.com/codex/cli 와 https://github.com/openai/codex 를 따릅니다.
구독 사용 한도와 이미지 입력 지원은 설치된 CLI와 계정에 따라 확인해야 합니다.

## 0.2.0 변경

모델/추론 강도 지정, 최근 모델 표시·고정, 최대 2개 동시 처리, 독립 재판독 경량화,
완료 페이지 재사용, 자료/문항/시험지/학생/배정 휴지통 및 복원 기능을 추가했습니다.
자세한 설정과 업데이트 절차는 UPDATE_0_2_KO.md를 참고하세요.

0.2.1에서 자동 큐 가동, 작업 중 보관함 자동/수동 새로고침, 외부 CLI DLL 경로 보완을 추가했습니다. UPDATE_0_2_1_KO.md를 참고하세요.
