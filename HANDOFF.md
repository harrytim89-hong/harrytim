# MathBank Desktop 개발 인계

요청 원문: docs/REQUIREMENTS_KO.txt. 최신 요구 우선. 필수 교사 승인 상태를 추가하지 않는다.
**현재는 개발판이며 Windows 완성품이 아니다. 전체 상태는 docs/IMPLEMENTATION_STATUS.md 참고.**

## 구조

- 기존 quiz_app은 그대로 유지.
- mathbank/store.py: SQLite v1, 원본 해시, 문항·이력·작업·스냅샷, 새 폴더 복원.
- validation.py: 독립 검사 필드, 숫자/부호 대조, 입력·도형 검증, 관련 결과 무효화.
- provider.py: 명시적 Codex 구독 호출, 임시 폴더, 비대화형·시간 초과·취소. 유료 API 없음.
- pipeline.py: 페이지/문항 큐, 독립 판독·영상 검토, 3 DPI 재시도. DB 락 밖에서 호출.
- arithmetic.py: AST 허용 연산만으로 숫자 등식 검산. 문자열 eval 금지.
- output.py: 불변 시험 스냅샷, escaped HTML/구조화 SVG, OMML DOCX, 성적표.
- desktop.py: 6개 화면, Qt 미리보기/PDF/프린터, 선택 편집·학생·과제·채점·백업.
- exchange.py: 원본 패키지 내보내기/ID·해시·버전 검증 가져오기. 가져오기는 통과를 부여하지 않음.

## 검증 재현

현재 가상환경 `/workspace/mathbank-venv` (저장소 밖).
`/workspace/mathbank-venv/bin/python -m pytest -q`: 31 통과.
`QT_QPA_PLATFORM=offscreen ... scripts/render_smoke.py` 및 `scripts/render_documents.py`:
Linux Qt WebEngine 자식 프로세스 실행 권한이 필요. 샌드박스 비활성화 옵션은 넣지 않았다.
출력은 artifacts/ (git 제외). 실제 시험지/중·고등 성적표 PDF·DOCX·PNG가 있다.
`live_ai_smoke.py`는 실제 구독 호출을 한다. 무심코 자동 CI에 넣지 않는다.
실제 AI 호출은 로그인 확인 후 접근 거부/시간 초과로 실패했고 작업은 paused로 남았다.

## 배포

Windows 빌드 스크립트와 push/workflow_dispatch CI를 실행했다.
사용자 승인 후 소스 커밋·main push 완료. 9f149e9 빌드 #4에서 EXE 생성과 자동 실행 검사 통과.
Inno 설치 파일 및 환경 게시 없음. 배포 폴더 다운로드는 Actions Artifacts를 사용한다.
사용자는 Windows PC에서 검증 가능하다고 답했다. 원격 Windows 실행 도구는 연결되어 있지 않다.
사용자는 소스 업로드·Windows 빌드 실행을 명시적으로 승인했다. 동일 작업의 승인 재요청은 불필요하다.
원본 운영 데이터나 Codex 인증 파일을 CI/배포에 넣지 않는다.

## 우선 수정/확장

구현 상태표의 미완료 항목을 완료해야 한다. 특히 실제 AI 연결, 복잡한 분리·도형,
캐시/스키마 강제 출력, Windows 프로세스 격리, 콘텐츠 길이에 따른 조판,
DOCX 벡터, 기존 데이터 마이그레이션, 자동 백업/업데이트 롤백.
수동 편집은 관련 상태만 무효화하지만 파이프라인은 아직 보수적으로 전체 원본 판독을 반복한다.
Qt offscreen에서 GPU 경고는 있으나 PDF 저장은 성공했다. WebEngine profile/page 객체 수명을 수정하고 재실행하여 종료 경고가 사라진 것을 확인했다.
추후 실제 자료를 얻어 모의 AI 테스트와 실제 정확도 검증을 엄격히 구분할 것.

## Windows 검증 후 수정

SQLite connection context manager는 close를 하지 않으므로 backup/restore의 임시 DB 조회에
`contextlib.closing`을 사용했다. Windows WinError 32를 해결했고 Windows 31개 테스트가 통과했다.
`mathbank/smoke.py` + `launch_mathbank.py --smoke-test PATH`는 배포 EXE의 창·수식·PDF 검사 진입점이다.
CI 성공 시에만 배포 폴더를 업로드한다. 일반 실행에는 smoke 옵션을 사용하지 않는다.
GitHub API는 이 클라우드에서 Forbidden이지만 git push와 공개 Actions HTML 조회는 가능했다.
워크플로우의 진단 주석으로 실패 로그를 확인할 수 있다. 임의 인증 추출은 하지 않는다.

## 0.2.0 추가

독립 재판독을 원문 전용 READ_PROMPT로 변경(최초 생성/최종 대조 유지).
원자적 claim_job + 문항 우선 큐, 최대 2 workers. CLI 로그인 확인 5분 재사용.
모델/effort/workers 설정 저장, 실제 CLI 헤더 모델 기록 및 최근 모델 고정 UI.
trash 테이블은 스키마 v1의 additive 테이블이며 soft delete만 지원. 과거 record snapshots 유지.
삭제 UI는 idle 상태에서만 실행. 완료 페이지 재등록 시 불필요한 AI 호출 생략.
새 테스트 포함 Linux 40개 통과. 실제 사용자 교재 속도/정확도는 비교 검증 필요.
