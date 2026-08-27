; Inno Setup script for Linguar Hub (Main + Trial channels)
; Main:   ISCC.exe /DMyAppVersion=1.2.0 /DSourceDir="..\dist\Linguar Hub" Linguar_Hub.iss
; Trial:  ISCC.exe /DTrial /DMyAppVersion=1.2.0 /DSourceDir="..\dist\Linguar Hub Trial" Linguar_Hub.iss
; Per-user installer (no admin prompt) that upgrades in place. The Trial
; channel is a SEPARATE app (own name / AppId / folder) so it installs
; side-by-side with Main; both share the same user data + config.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

#ifdef Trial
  #define MyAppName "Linguar Hub Trial"
  #define MyAppExe  "Linguar Hub Trial.exe"
  #define AppGuid   "9C6B4E2A-7F3D-4B1E-9A2C-3D5F7A1B9C03"
  #define OutBase   "Linguar-Hub-Trial-Setup"
  #define DirLeaf   "Linguar Hub Trial"
  #define SetupIcon "linguar_hub_trial.ico"
#else
  #define MyAppName "Linguar Hub"
  #define MyAppExe  "Linguar Hub.exe"
  #define AppGuid   "9C6B4E2A-7F3D-4B1E-9A2C-3D5F7A1B9C02"
  #define OutBase   "Linguar-Hub-Setup"
  #define DirLeaf   "Linguar Hub"
  #define SetupIcon "linguar_hub.ico"
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
SetupIconFile={#SetupIcon}
; Close a running copy automatically, then reopen it after install.
CloseApplications=yes
RestartApplications=yes
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[InstallDelete]
; The AppId is deliberately unchanged, so this UPGRADES an existing EMS Tools
; install in place. That also means the old exe and its shortcuts survive the
; copy and the user is left with two apps, one of them dead. Remove them.
Type: files; Name: "{app}\EMS Tools.exe"
Type: files; Name: "{app}\EMS Tools Trial.exe"
Type: files; Name: "{group}\EMS Tools.lnk"
Type: files; Name: "{group}\EMS Tools Trial.lnk"
Type: files; Name: "{group}\Uninstall EMS Tools.lnk"
Type: files; Name: "{group}\Uninstall EMS Tools Trial.lnk"
Type: files; Name: "{autodesktop}\EMS Tools.lnk"
Type: files; Name: "{autodesktop}\EMS Tools Trial.lnk"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
