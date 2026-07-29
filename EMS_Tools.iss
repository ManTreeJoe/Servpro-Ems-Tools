; Inno Setup script for EMS Tools
; Build:  ISCC.exe /DMyAppVersion=1.1.1 /DSourceDir="%LOCALAPPDATA%\EMSTools\EMS Tools" EMS_Tools.iss
; Produces a per-user installer (no admin prompt) that upgrades in place.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\EMS Tools"
#endif

#define MyAppName "EMS Tools"
#define MyAppExe  "EMS Tools.exe"
#define MyAppPublisher "SERVPRO of Woodcrest/El Cerrito/Lake Mathews"

[Setup]
; Stable AppId so a newer setup UPGRADES the existing install instead of duplicating it.
AppId={{9C6B4E2A-7F3D-4B1E-9A2C-3D5F7A1B9C02}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Per-user install — no UAC / admin prompt.
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\EMS Tools
DefaultGroupName=EMS Tools
DisableProgramGroupPage=yes
DisableDirPage=yes
UninstallDisplayIcon={app}\{#MyAppExe}
UninstallDisplayName={#MyAppName} {#MyAppVersion}
OutputBaseFilename=EMS-Tools-Setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Close a running copy automatically, then reopen it after install.
CloseApplications=yes
RestartApplications=yes
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\EMS Tools"; Filename: "{app}\{#MyAppExe}"
Name: "{group}\Uninstall EMS Tools"; Filename: "{uninstallexe}"
Name: "{autodesktop}\EMS Tools"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Launch EMS Tools"; Flags: nowait postinstall skipifsilent
