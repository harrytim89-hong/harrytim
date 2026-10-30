; Compile with Inno Setup 6 after build_windows.ps1 succeeds.
[Setup]
AppId=MathBankDesktop
AppName=MathBank Desktop
AppVersion=0.2.3
DefaultDirName={localappdata}\Programs\MathBankDesktop
DefaultGroupName=MathBank Desktop
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=MathBankDesktop-Setup
Compression=lzma2
SolidCompression=yes
UninstallDisplayIcon={app}\MathBankDesktop.exe
[Files]
Source: "..\dist\MathBankDesktop\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\MathBank Desktop"; Filename: "{app}\MathBankDesktop.exe"
Name: "{userdesktop}\MathBank Desktop"; Filename: "{app}\MathBankDesktop.exe"
[Run]
Filename: "{app}\MathBankDesktop.exe"; Description: "MathBank Desktop 실행"; Flags: nowait postinstall skipifsilent
; Deliberately no deletion of %LOCALAPPDATA%\MathBankDesktop operating data.
