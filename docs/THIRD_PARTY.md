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
- SymPy 1.14.0 / mpmath 1.3.0: BSD 계열. 허용 구문만 직접 파싱하고 외부 문자열을 sympify/parse_expr/eval로 실행하지 않는다.
- Typst Python 바인딩 0.14.7: Apache-2.0 계열, 포함된 컴파일러·폰트의 실제 고지를 wheel 라이선스와 함께 포함한다. CLI 실행파일 대신 고정된 네이티브 바인딩을 사용한다. PDF는 실제 Typst 컴파일러가 생성한다.
- python-hwpx 6.11.0: Apache-2.0. 원본 프로젝트 https://github.com/airmang/python-hwpx . 입력 분리기는 앱에서 별도로 작성했고 HWPX 출력은 이 라이브러리의 네이티브 개체 생성기를 사용한다.
- defusedxml 0.7.1: PSF 계열. ZIP 내부 XML의 외부 엔터티/DTD 방어에 사용한다.
- Noto Sans CJK Regular: SIL Open Font License 1.1. `mathbank/assets/fonts/NOTO-LICENSE.txt`를 포함한다.
- 오프라인 Windows 런타임: 공식 Python NuGet 3.12.10, PSF 라이선스 및 포함된 제3자 고지를 런타임 폴더에 유지한다. Python 자체를 변형하지 않는다.
- Zig 0.14.1: MIT. 빌드 도구이며 최종 앱에 Zig 컴파일러를 포함하지 않는다. 네이티브 런처는 Windows 시스템 DLL을 사용한다.

배포 전에 `scripts/collect_licenses.py`로 설치 패키지의 실제 라이선스 파일을 수집한다.
이 목록은 라이선스 원문을 대체하지 않는다. PyMuPDF의 AGPL/상용 선택은 완성품 배포 전 해결할 항목이다.

공식 구현 참고: https://github.com/openai/codex (README와 CLI 0.163.0 --help를 실제 확인),
https://github.com/openai/codex/blob/main/codex-rs/core/config.schema.json (도구 비활성 설정 확인).
