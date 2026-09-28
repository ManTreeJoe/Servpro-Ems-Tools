# OneLoss 1.8.24

- Simplified Files page: Photos/Documents, stage albums, visible-album counts/covers, breadcrumbs, PDF/photo previews and exact Open folder.
- Floating Trello reaction picker: search, categories, recent emojis and reaction counts. Uses the connected Trello account. Reactions load on demand; no per-message polling.
- Refined EMS/Contents/Recon tabs; comments follow the selected division while posting targets remain independent.
- Compact Job Log toolbar, circular loading spinner, and corrected rich-comment placeholder for lists and restored text.
- Create Snapshot directly from Job Log. Report edits no longer auto-write into Job Log, and PDF generation no longer writes log entries. Exact selected card/division is retained for generation and history; opening Snapshot no longer auto-pins a card.

No database migration, folder relocation, or automatic Trello comment import is included. Photo covers require locally available files. Picker has 78 bundled choices, not the full Trello catalogue.

Validation: full baseline Python suite 3,917 passed; Snapshot isolation tests added afterward and checked separately. Browser suites cover the changed surfaces and regression paths. Live customer reaction/PDF posting was not exercised; those external writes remain user-driven.

Final checks: 17 focused Snapshot Python tests passed, along with the exact-card Snapshot browser test and Jobs regression suites. Files navigation passed repeated reruns after one combined-run timeout. Bundled asset hashes and required Python modules verified. Packaged app started with an isolated empty profile and served the home and corrected Snapshot assets successfully (HTTP 200); this is a startup smoke check, not a live customer workflow test.

Installer: `Linguar-Hub-Setup-1.8.24.exe`, 38,782,125 bytes. SHA-256: `31393728cc542686e1f5311dce1c875da2d23a1a8df9ea202594ab7d294eb912`.
