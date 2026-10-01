# OneLoss 1.8.26

- Select multiple Job Log activities with a floating pill picker and assign crew per activity.
- Subcontractor filters and inline editing; compact PDF output with subs first, no full comments or redundant completed labels.
- Snapshots read saved Job Logs directly; smaller pending queue and recent-export list.
- Automatic file checks without routine success text; unified loading feedback avoids duplicate indicators.
- Notification board tabs, inline unread counter, opening marks read, and improved read-all handling.
- Optional Windows notifications for the personal OneLoss inbox: mentions or job comments, with test button and exact-comment navigation. Off by default; enable under Notifications → Windows notifications. Requires the app running/minimized; Trello-only comments are not included.
- CompanyCam repinning, saved reaction handling, card-drop recovery and editable profile starters.

Existing experimental saved views remain DEV-gated. No historical import, customer-data migration, provider deployment, or schema change is performed by this installer.

## Verification

- Full Python suite: 3,986 passed; two existing UTC deprecation warnings.
- Fifteen targeted browser suites passed; custom activity creation/crew assignment also verified.
- Packaged app served the shell successfully; all four shell stylesheets loaded and sidebar measured 230px. Bundled key asset hashes match source; new Python modules and WinRT binaries are present.
- Dependency consistency check passed.
- Installer: `Linguar-Hub-Setup-1.8.26.exe`, 39,305,420 bytes.
- SHA-256: `1dab2dd269f3386aedd57fafae5893e9e96a0a3e240ab2b519afb572ed31eff0`.

The diagnosis workflow identified eight stale assertions for intentionally replaced UI/report behavior; updated expectations passed in the full rerun. No runtime behavior was weakened to satisfy those tests.

Native Windows accepted a generic test toast; a real incoming teammate mention/click is still a manual verification item. The packaged startup check is not a complete native visual acceptance test. No production database/schema or provider deployment was performed.
