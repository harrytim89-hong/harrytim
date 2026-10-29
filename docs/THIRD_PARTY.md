# 의존성과 라이선스

고정 버전은 requirements.lock, 직접 의존성은 requirements.txt에 기록한다.
새로 작성한 앱 소스의 배포 라이선스는 저장소 소유자가 정해야 하며, 여기서 임의로 오픈소스 공개하지 않는다.

- PySide6 / Qt: LGPLv3/GPLv3 또는 상용 조건. 실제 포함 모듈과 Qt WebEngine의 Chromium 고지를 배포 시 함께 확인해야 한다.
- PyMuPDF / MuPDF: AGPLv3 또는 상용 라이선스. 비공개 배포를 하려면 해당 조건에 맞는 라이선스 선택 또는 다른 PDF 엔진으로 교체가 필요하다.
- python-docx: MIT.
- latex2mathml: MIT.
- mathml2omml: LGPL (배포 패키지의 LICENSE 원문 기준).
- KaTeX 0.16.22: MIT, `mathbank/assets/katex/LICENSE` 포함. KaTeX 폰트는 배포물의 폰트 라이선스도 확인한다.
- PyInstaller: GPL + 배포 예외. 빌드 의존성, pytest는 테스트 의존성.
- Codex CLI: Apache-2.0. 이 앱은 CLI 인증 파일/토큰을 포함하지 않는다. ChatGPT 서비스 이용은 별도 계정·약관·사용 한도를 따른다.

배포 전에 `scripts/collect_licenses.py`로 설치 패키지의 실제 라이선스 파일을 수집한다.
이 목록은 라이선스 원문을 대체하지 않는다. PyMuPDF의 AGPL/상용 선택은 완성품 배포 전 해결할 항목이다.

공식 구현 참고: https://github.com/openai/codex (README와 CLI 0.163.0 --help를 실제 확인),
https://github.com/openai/codex/blob/main/codex-rs/core/config.schema.json (도구 비활성 설정 확인).
