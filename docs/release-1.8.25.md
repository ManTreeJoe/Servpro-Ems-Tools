# OneLoss 1.8.25

- Personal notifications, job membership, read/unread, filters and mute controls.
- Compact Trello notification previews, full-message reader and verified exact-card/comment navigation.
- Right-click tools and job cards to open independent windows; repeated requests focus the existing pop-out.
- Shared comment formatting, mentions and reactions across Jobs, Daily Run, Snapshot and Quick Import.
- EMS WIP/Estimating copy workflow with server-side reservation guards.
- Selected CompanyCam stages add existing catalog tags, including Initial Inspection and Demo. No custom tag entry; catalog validation occurs before import.
- Notification scrolling, bounded job popups and single-initialization startup fixes.

The CompanyCam gateway read-only tag-list permission is deployed. The personal notification and EMS-copy schema prerequisites were deployed before this release. No historical EMS Logs import or board color redesign is included. Existing comments, tags and user drafts are preserved; external posts remain user-driven.

## Release verification

- Full Python suite: 3,952 passed; two existing UTC deprecation warnings, no failures. Snapshot comment/image proxies now forward explicit card identifiers; the shared asset-version assertion matches the deployed asset URL.
- Ten targeted browser suites passed (inbox navigation, notification scrolling, popup height, personal notifications, shared comments, mentions, comment display, EMS copies, startup, CompanyCam preview).
- Packaged executable serves the direct shell with HTTP 200 and no meta redirect. New Python modules are present in the executable archive; selected shared UI assets match source hashes. Desktop visual automation was unavailable, so this is a startup/asset smoke check, not a full packaged visual test.
- Installer: `Linguar-Hub-Setup-1.8.25.exe` (38,818,368 bytes).
- SHA-256: `ae82303b5d4e927f766b844842449d20d3e216c9c6a35786cd68eebdd1b22c5b`.
