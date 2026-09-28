# Simplified Files gallery — DEV

Supersedes the earlier file-manager layout. Photos/Documents replace Source and duplicate filters; clickable breadcrumbs replace Up. Refresh is a small labeled icon and check timestamps live in its tooltip. Open folder remains available. Trello attachments remain a secondary link rather than the main source selector.

When exactly one immediate Pics/Photos/Pictures (or Docs/Documents) folder is present, the selected library opens it automatically. Numeric prefixes are tolerated. Ambiguous and other folder structures remain selectable; no name-based job matching or recursive folder search is added. Existing stage names are preserved.

Photos displays folder albums and a thumbnail grid. Visible albums load immediate-child photo counts and one available local cover photo, using the same two-worker queue as thumbnails. Counts exclude photos in deeper subfolders; subfolder counts are shown separately. Unavailable/offline covers retain a folder icon, and failed album reads do not invent a zero count. Documents uses a list with existing PDF preview. Existing path containment, cached listing, stale request guards, inline preview size limits and OneDrive download requirements remain.

UI-design and anti-ui-slop polish guidance used to reduce controls and check layout. job_file_stages.cjs and job_files.cjs passed for navigation, exact folder opening, previews, errors, attachments, retained workspace state and narrow layout. Screenshot visually checked. No files renamed, moved or changed. DEV restart requested by user; no release publishing.
