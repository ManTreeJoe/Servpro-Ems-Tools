# OneLoss 1.8.27

- Shared pinned comments, a separate pinned filter, and linked replies that also remain in the regular feed.
- Trello replies include the verified original author's username and original @mentions, without the technical footer. Duplicate mentions and the posting user's own mention are omitted.
- Saved comments appear before background refresh; drafts and existing job information stay visible during loading.
- Job Info editor hydration, explicit cleared fields, and multiline Scope of Work fixes.
- Cleaner job workspace actions, close button at the overall top-right, and direct Open job from Daily Run.
- Native replies notify saved OneLoss thread participants and subscribed job members. Placement changes and supported confirmed desktop card edits also notify members, respecting access, mute and self-notification exclusions.
- Preserves the public Main/Trial update-feed configuration from Main.

## Boundaries

This release preserves the existing thread view. The requested floating thread
pop-out is next, not included. The experimental calendar remains DEV-gated;
Reconstruction and L OPS changes remain deferred.

Notification coverage is not yet every provider event: direct-Trello activity
ingestion, verified Trello-to-OneLoss user matching, and exact-card rather than
current job-wide membership remain follow-up work. Native reply edit/delete and
automatic recovery of uncertain unmarked Trello deliveries are not included.
The reply is retained in OneLoss; uncertain delivery must not be blindly retried.

The shared comment schema and parent-verification endpoint were deployed during
the approved DEV work. This installer consumes those services; it does not run
migrations or rewrite historical comments.

## Verification

- Full Python suite: 4,154 passed, no skips; two existing UTC deprecation warnings.
- 28 targeted browser suites passed, including replies/pins, draft recovery,
  notifications, Daily Run opening, Job Logs and packaged shell startup.
- The diagnosis checks identified stale assertions for approved UI changes and
  missing activity-picker dependencies in browser fixtures. Updated those tests;
  no application behavior was changed to make the release tests pass.
- Packaged Main opened with the OneLoss window title. All four shell stylesheets
  loaded; sidebar measured 230px. Critical bundled asset hashes match source;
  comment/thread/notification/backend modules are present in the Python archive.
- Dependency consistency and packaged configuration safety checks passed. No
  personal provider token or backend service-role key is shipped.
- Installer: `Linguar-Hub-Setup-1.8.27.exe`, 39,371,816 bytes.
- SHA-256: `e75bf276e426bc49da5317db29ac04c6d54ae4e85a6646865d9d2fdd1c1ea667`.

The installer is not code-signed. A real two-user reply/notification acceptance
check remains recommended; automated tests are not a substitute for that check.
