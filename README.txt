EMS Tools
=========
SERVPRO IE Department admin automation suite.


GETTING STARTED
---------------
1. Keep this entire folder together. Don't move "EMS Tools.exe" out of it
   — it needs the "_internal" folder next to it to run.

2. Double-click "EMS Tools.exe".

3. The first time you run it, a Settings dialog will pop up. The tool
   tries to auto-fill the right folder paths by looking for OneDrive
   folders and an X:\ drive. Confirm or correct them, then click Save.

4. After that, the launcher opens straight to the tool list every time.


WHERE THINGS LIVE
-----------------
Settings, logs, and audit history live in:
    %APPDATA%\EMS Automation\
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
    Close EMS Tools, delete %APPDATA%\EMS Automation, then relaunch.
    The wizard will pop again as if it's a fresh install.


UNINSTALLING
------------
1. Close EMS Tools.
2. Delete this folder.
3. Optionally delete %APPDATA%\EMS Automation to remove your settings
   and history.

There's no installer, no registry entries, no services — just files.


VERSION
-------
See the bottom of the launcher window.
