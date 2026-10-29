# Build on Windows x64, Python 3.12. End users do not need Python or Node.
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
if (-not $IsWindows -and $env:OS -ne 'Windows_NT') { throw 'A real Windows build host is required.' }
Set-Location (Split-Path -Parent $PSScriptRoot)
python -m venv .build-venv
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 build prerequisite unavailable.' }
$BuildPython = Join-Path $PWD '.build-venv\Scripts\python.exe'
& $BuildPython -m pip install -r requirements.lock
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $BuildPython -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Tests failed; no package was built.' }
& $BuildPython -m PyInstaller --noconfirm --clean --windowed --onedir --name MathBankDesktop --add-data 'mathbank/assets;mathbank/assets' --collect-all PySide6.QtWebEngineCore --collect-all PySide6.QtWebEngineWidgets launch_mathbank.py
if ($LASTEXITCODE -ne 0) { throw 'Windows packaging failed.' }
& $BuildPython scripts/collect_licenses.py dist/MathBankDesktop/licenses
if ($LASTEXITCODE -ne 0) { throw 'License collection failed.' }
Copy-Item docs\USER_GUIDE_KO.md dist\MathBankDesktop\USER_GUIDE_KO.md
Copy-Item docs\THIRD_PARTY.md dist\MathBankDesktop\THIRD_PARTY.md
Copy-Item requirements.lock dist\MathBankDesktop\requirements.lock
Compress-Archive -Path dist\MathBankDesktop -DestinationPath dist\MathBankDesktop-Windows-x64.zip -Force
Write-Output 'Built dist\MathBankDesktop\MathBankDesktop.exe. Run the Windows acceptance checklist before release.'
