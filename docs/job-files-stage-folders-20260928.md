# Files: actual folder navigation

Local DEV implementation, not published/restarted.

- Main folders from the saved job root appear as shortcuts using their actual names (including Pics and Docs when present). No fabricated folders, renaming, moving or recursive scan.
- Pics displays its real stage subfolders as tiles: Initial, Demo, etc. Selecting a stage lists that folder's files with visible/local photo thumbnails and existing image preview/navigation.
- Docs lists actual documents. PDFs use the existing inline preview; other supported documents can be opened in their associated app.
- Open folder opens the current verified directory in Windows. The new backend bridge uses the existing saved folder lookup and path-containment validation; missing/outside-root locations are rejected.
- Keeps lazy activation, directory-at-a-time cached listing, explicit Refresh files, stale-result guards and two concurrent visible-thumbnail requests. Existing OneDrive online-only and 16 MB inline-preview limits remain. Trello attachments still open externally; this change concerns the local saved job folder.

UI-design and anti-ui-slop polish guidance informed the folder tiles, consistent controls and narrow wrapping. Verified rendered stage-folder view and narrow overflow, using fixture files rather than customer changes.

Tests: job_file_stages.cjs and job_files.cjs passed. Eight backend checks passed across test_job_folder_open.py, test_job_file_browser.py and test_job_file_index.py.

DEV check: open a linked job → Files → Pics → a stage → photo preview; Open folder should open that exact stage. Select Docs → PDF → preview/open. Confirm actual OneDrive files are downloaded before trying inline previews. No automatic app restart performed.
