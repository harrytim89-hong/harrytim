$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path $PSScriptRoot -Parent
Set-Location $ProjectRoot
python -m pip install -r requirements.lock
if ($LASTEXITCODE -ne 0) { throw 'Dependency install failed' }
python scripts/create_icon.py
python -m PyInstaller --noconfirm --clean --windowed --onedir --name MathBankStudio --icon studio/ui/assets/studio.ico --add-data "studio/ui;studio/ui" --collect-all hwpx --collect-all typst --collect-submodules sympy launch_studio.py
if ($LASTEXITCODE -ne 0) { throw 'Windows build failed' }
Copy-Item docs/사용설명.md dist/MathBankStudio/시작하기.md
Copy-Item docs/SUPPORT.md dist/MathBankStudio/지원범위.md
python scripts/collect_licenses.py dist/MathBankStudio/licenses
if ($LASTEXITCODE -ne 0) { throw 'License collection failed' }
Write-Output 'Built dist/MathBankStudio/MathBankStudio.exe'
