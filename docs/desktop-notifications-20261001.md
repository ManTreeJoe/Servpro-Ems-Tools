# Windows desktop alerts

Notifications → Windows notifications offers Off (default), Mentions only, and
Mentions and my job comments, plus a test button. Preferences are local to the PC,
scoped to the signed-in OneLoss user and active department in desktop_notifications.db.
No comments, tokens, or notification bodies are persisted by this feature.

The main shell owns one daemon poller; child tools/popouts do not start another.
It runs every 30 seconds even when minimized, and stops with the app. There is no
tray process, startup task, or closed-app delivery. Windows notification permissions
and Do not disturb control whether banners appear.

Delivery reads the existing authorized personal inbox RPC. It does NOT poll the
connected Trello account feed or ingest comments made only in Trello. Existing
server logic excludes the actor and restricts recipients to mentions/job members;
the client also filters read and muted entries. No database schema or permissions
changed. The first successful read is silent on startup, account/department changes,
and mode changes. Entries older than five minutes are suppressed to avoid resume
storms. At most three alerts are shown per poll; all entries remain in the inbox.

Clicking rechecks the signed-in identity and current inbox access, resolves the
exact card/comment using the existing navigation boundary, and focuses the app.
Successful navigation dispatch marks the personal notification read; missing or
unresolvable jobs open the inbox instead without marking read. Already-closed
applications are not relaunched by a toast.

Windows-Toasts 1.3.1 and WinRT 3.2.1 are pinned; the PyInstaller spec includes their
submodules. Native delivery registers an application identity under the current
user's Software/Classes/AppUserModelId/OneLoss.Desktop.<channel> registry key.
No machine-wide changes or admin privileges are required.

Verification: Python eligibility/preferences/navigation tests; browser control
save/test/failure/overflow checks; native Windows API accepted a generic test toast;
live personal inbox read succeeded (empty). A real incoming mention → Windows click
round trip still needs another user's new comment to verify end to end.
