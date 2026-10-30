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
$SmokeOutput = Join-Path $PWD 'artifacts\windows-exe-smoke'
$SmokeProcess = Start-Process -FilePath (Join-Path $PWD 'dist\MathBankDesktop\MathBankDesktop.exe') -ArgumentList @('--smoke-test', ('"' + $SmokeOutput + '"')) -PassThru
if (-not $SmokeProcess.WaitForExit(90000)) {
    Stop-Process -Id $SmokeProcess.Id -Force
    throw 'Packaged executable smoke test timed out.'
}
if ($SmokeProcess.ExitCode -ne 0) { throw 'Packaged executable smoke test failed.' }
$SmokeResult = Get-Content (Join-Path $SmokeOutput 'result.json') -Raw -Encoding utf8 | ConvertFrom-Json
if (-not $SmokeResult.pdf_saved -or -not $SmokeResult.render_ready) { throw 'Packaged rendering/PDF validation failed.' }
Write-Output ('Packaged EXE smoke result: ' + ($SmokeResult | ConvertTo-Json -Compress))
Copy-Item docs\UPDATE_0_2_3_KO.md dist\MathBankDesktop\UPDATE_0_2_3_KO.md
Copy-Item docs\UPDATE_0_2_2_KO.md dist\MathBankDesktop\UPDATE_0_2_2_KO.md
Copy-Item docs\UPDATE_0_2_1_KO.md dist\MathBankDesktop\UPDATE_0_2_1_KO.md
Copy-Item docs\UPDATE_0_2_KO.md dist\MathBankDesktop\UPDATE_0_2_KO.md
Copy-Item docs\USER_GUIDE_KO.md dist\MathBankDesktop\USER_GUIDE_KO.md
Copy-Item docs\THIRD_PARTY.md dist\MathBankDesktop\THIRD_PARTY.md
Copy-Item requirements.lock dist\MathBankDesktop\requirements.lock
Compress-Archive -Path dist\MathBankDesktop -DestinationPath dist\MathBankDesktop-Windows-x64.zip -Force
Write-Output 'Built dist\MathBankDesktop\MathBankDesktop.exe. Run the Windows acceptance checklist before release.'
