"""Assemble a Windows portable folder from verified offline inputs.

Usage: python scripts/package_portable.py RUNTIME.nupkg WHEELS LAUNCHER.exe DEST
The launcher is a real cross-built PE, not a Windows execution claim.
"""
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
import zipfile


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def unpack(archive, destination, prefix=''):
    with zipfile.ZipFile(archive) as z:
        for member in z.infolist():
            if member.is_dir() or not member.filename.startswith(prefix): continue
            name=member.filename[len(prefix):]
            if '..' in PurePosixPath(name).parts or name.startswith('/') or '\\' in name: raise ValueError('Archive path rejected')
            # Wheel data files follow the wheel installation scheme.
            parts=PurePosixPath(name).parts
            if parts and parts[0].endswith('.data'):
                if len(parts)<3 or parts[1] not in ('purelib','platlib'): continue
                name='/'.join(parts[2:])
            target=destination/name
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(z.read(member))


def main():
    runtime,wheels,launcher,dest=map(Path,sys.argv[1:])
    if dest.exists(): raise ValueError('Destination must be a new directory')
    dest.mkdir(parents=True)
    root=Path(__file__).resolve().parents[1]
    unpack(runtime,dest/'runtime','tools/')
    site=dest/'runtime/Lib/site-packages'
    artifacts={runtime.name:sha(runtime),launcher.name:sha(launcher)}
    for wheel in sorted(wheels.glob('*.whl')):
        if 'manylinux' in wheel.name: raise ValueError('Linux wheel in Windows bundle')
        unpack(wheel,site)
        artifacts[wheel.name]=sha(wheel)
    for name in ('mathbank','quiz_app','tests','docs','scripts'):
        shutil.copytree(root/name,dest/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for name in ('launch_mathbank.py','requirements.lock','requirements.txt','README.md'):
        shutil.copyfile(root/name,dest/name)
    shutil.copyfile(launcher,dest/'MathBankDesktop.exe')
    # Native Qt/Typst/HWPX imports are checked on Windows, never on Linux.
    verify='''@echo off
cd /d "%~dp0"
runtime\\python.exe -m pytest -q
if errorlevel 1 goto error
runtime\\python.exe scripts\\hwpx_acceptance.py --output windows-acceptance
if errorlevel 1 goto error
MathBankDesktop.exe --smoke-test windows-gui-smoke
if errorlevel 1 goto error
echo Windows checks completed. Review windows-acceptance and windows-gui-smoke.
pause
exit /b 0
:error
echo Windows validation failed. Keep the complete diagnostic output.
pause
exit /b 1
'''
    (dest/'VERIFY_WINDOWS.cmd').write_text(verify.replace('\n','\r\n'),encoding='ascii')
    (dest/'README_KO.txt').write_text('''MathBank Desktop 0.3.1 개발판

전체 ZIP을 풀고 MathBankDesktop.exe를 실행하세요. EXE만 분리하지 마세요.
Python/Qt/Typst/폰트는 동봉했습니다. AI 연결은 선택 사항입니다.
문제 HWPX만으로 자료실 가져오기와 문항 저장·분류가 가능합니다.
정답/해설은 07 변형·정답 생성에서 선택/일괄 생성합니다.
지원 계산 정책을 통과한 문항만 별도 승인 없이 사용할 수 있습니다.

이 EXE는 Linux에서 Windows x64용으로 교차 빌드했습니다.
실제 Windows 11 및 한글에서 실행·편집·재저장은 아직 검증하지 않았습니다.
이번 환경의 실제 AI 호출은 권한 오류로 실패했습니다.
지원 범위는 방정식·다항식·복소수 등 제한된 대수 검사 정책이며 전 단원 완성품이 아닙니다.

검사 실행: VERIFY_WINDOWS.cmd
사용 안내: docs/HWPX_0_3_KO.md
실제 HWP 자료 검증: docs/HWPX_0_3_1_KO.md
검증 기록: docs/VALIDATION_0_3_KO.md
포함 파일 해시: BUILD_MANIFEST.json
운영 데이터: %LOCALAPPDATA%/MathBankDesktop
''',encoding='utf-8-sig')
    manifest={'version':'0.3.1','runtime':'CPython 3.12.10 x64 / official Python NuGet package',
              'launcher':'Zig 0.14.1 -> x86_64-windows-gnu PE GUI',
              'windows_execution_verified':False,'input_artifacts_sha256':artifacts,
              'files':{str(p.relative_to(dest)).replace('\\','/'):sha(p) for p in dest.rglob('*') if p.is_file()}}
    (dest/'BUILD_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'destination':str(dest),'files':len(manifest['files']),'windows_execution_verified':False}))


if __name__=='__main__':main()
