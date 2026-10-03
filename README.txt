L OPS platform / agent reference
See docs/l-ops-platform.md for shared web/mobile/iPad build notes and cross-repository coordination.
Full guide: https://github.com/ManTreeJoe/l-ops-crm/blob/main/docs/agent-guide/README.md

Linguar Hub
=========
SERVPRO IE Department admin automation suite.


INSTALLING AND UPDATING
-----------------------
1. Run the Main or Trial Setup .exe once. It installs for your Windows user
   without an admin prompt. Trial installs alongside Main.

2. Open the app from its Start menu or desktop shortcut. Both Main and Trial
   show an "Update available" banner on launch when a newer build is live.

3. Follow the banner to download and run the newer Setup .exe. For Trial,
   test builds arrive the same way; no separate application zip/unzip needed.


GETTING STARTED (FOLDER DOWNLOAD)
---------------
1. Keep this entire folder together. Don't move "Linguar Hub.exe" out of it
   — it needs the "_internal" folder next to it to run.

2. Double-click "Linguar Hub.exe".

3. The first time you run it, a Settings dialog will pop up. The tool
   tries to auto-fill the right folder paths by looking for OneDrive
   folders and an X:\ drive. Confirm or correct them, then click Save.

4. After that, the launcher opens straight to the tool list every time.


WHERE THINGS LIVE
-----------------
Settings, logs, and audit history live in:
    %APPDATA%\Linguar Hub\
    (i.e. C:\Users\<you>\AppData\Roaming\EMS Automation)

You can open this folder anytime via Settings → "Open data folder".

Files inside it:
    config.json              your folder paths
    state.json               resolved checkboxes, contact emails, window sizes
    audit_backlog.json       audit history (90-day rolling)
    EMS_Audit_Log.md         human-readable audit log (newest on top)
    EMS_Audit_Backlog.md     human-readable backlog by week
    ems.log                  error log — check this if anything misbehaves


CHANGING SETTINGS LATER
-----------------------
Click the gear icon (⚙) in the top-left of the launcher window.
You can also click "Auto-detect" inside Settings to re-scan for OneDrive
folders if you've added new ones since first install.


TROUBLESHOOTING
---------------
"Nothing happens when I click a tool"
    Open the data folder (Settings → Open data folder) and look at
    ems.log. The crash handler writes every uncaught error there.

"Folders show 'not found on this PC' in Settings"
    The X: drive isn't mapped, or your OneDrive is at a different path
    than expected. Click Browse next to the field and pick the right one.

"I want to start fresh"
    Close Linguar Hub, delete %APPDATA%\Linguar Hub, then relaunch.
    The wizard will pop again as if it's a fresh install.


UNINSTALLING
------------
1. Close Linguar Hub.
2. For a Setup installation, uninstall Linguar Hub (or Linguar Hub Trial)
   from Windows Settings → Apps. For a folder download, delete this folder.
3. Optionally delete %APPDATA%\Linguar Hub to remove your settings
   and history.



VERSION
-------
See the bottom of the launcher window.
