; Inno Setup script for EMS Tools (Main + Trial channels)
; Main:   ISCC.exe /DMyAppVersion=1.1.1 /DSourceDir="%LOCALAPPDATA%\EMSTools\EMS Tools" EMS_Tools.iss
; Trial:  ISCC.exe /DTrial /DMyAppVersion=1.1.1 /DSourceDir="%LOCALAPPDATA%\EMSTools\EMS Tools Trial" EMS_Tools.iss
; Per-user installer (no admin prompt) that upgrades in place. The Trial
; channel is a SEPARATE app (own name / AppId / folder) so it installs
; side-by-side with Main; both share the same user data + config.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

#ifdef Trial
  #define MyAppName "EMS Tools Trial"
  #define MyAppExe  "EMS Tools Trial.exe"
  #define AppGuid   "9C6B4E2A-7F3D-4B1E-9A2C-3D5F7A1B9C03"
  #define OutBase   "EMS-Tools-Trial-Setup"
  #define DirLeaf   "EMS Tools Trial"
#else
  #define MyAppName "EMS Tools"
  #define MyAppExe  "EMS Tools.exe"
  #define AppGuid   "9C6B4E2A-7F3D-4B1E-9A2C-3D5F7A1B9C02"
  #define OutBase   "EMS-Tools-Setup"
  #define DirLeaf   "EMS Tools"
#endif

#ifndef SourceDir
  #define SourceDir "..\dist\" + DirLeaf
#endif

#define MyAppPublisher "SERVPRO of Woodcrest/El Cerrito/Lake Mathews"

[Setup]
; Stable per-channel AppId so a newer setup UPGRADES that channel in place
; (and Main vs Trial never overwrite each other).
AppId={{{#AppGuid}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Per-user install — no UAC / admin prompt.
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#DirLeaf}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
UninstallDisplayIcon={app}\{#MyAppExe}
UninstallDisplayName={#MyAppName} {#MyAppVersion}
OutputBaseFilename={#OutBase}-{#MyAppVersion}
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
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
