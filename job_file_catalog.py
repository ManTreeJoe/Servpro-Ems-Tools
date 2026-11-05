"""Read-only catalog proposal. No byte reads, hydration, uploads or DB writes.

Relative paths are proposals, not durable provider identities. Rename detection
and shared registration deliberately wait for a verified storage source.
"""
import os
import stat
import time
from collections import Counter
from pathlib import Path

from job_file_browser import PHOTOS, DOCUMENTS, _offline


def preview(root, job_id, *, max_entries=2000, max_seconds=5):
    if not root or not job_id:
        return {'ok': False, 'error': 'A verified saved job and pinned folder are required.'}
    base = Path(root).absolute()
    files, issues, pending = [], [], [base]
    visited, deadline = 0, time.monotonic() + max_seconds
    try:
        root_stat = base.lstat()
        if (not stat.S_ISDIR(root_stat.st_mode) or base.is_symlink()
                or getattr(root_stat, 'st_file_attributes', 0) & 0x400):
            raise ValueError('The pinned root is a link or placeholder directory. Use a verified local folder for this preview.')
    except (OSError, ValueError):
        return {'ok': False, 'error': 'The pinned folder is unavailable or is a linked/placeholder directory. No files were changed.'}
    limited = False
    while pending and not limited:
        folder = pending.pop()
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    if visited >= max_entries or time.monotonic() >= deadline:
                        limited = True
                        break
                    visited += 1
                    relative = Path(entry.path).relative_to(base).as_posix()
                    try:
                        info = entry.stat(follow_symlinks=False)
                        if entry.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
                            issues.append({'relative': relative, 'reason': 'Link or placeholder skipped; not followed.'})
                            continue
                        if stat.S_ISDIR(info.st_mode):
                            if _offline(info):
                                issues.append({'relative': relative, 'reason': 'Online-only folder; not downloaded.'})
                            else:
                                pending.append(Path(entry.path))
                            continue
                        if not stat.S_ISREG(info.st_mode):
                            continue
                        extension = Path(entry.name).suffix.lower()
                        category = 'Photos' if extension in PHOTOS else 'Documents' if extension in DOCUMENTS else 'Other'
                        files.append({'name': entry.name, 'relative': relative,
                                      'category': category, 'size': info.st_size,
                                      'modified_ns': info.st_mtime_ns,
                                      'availability': 'Online-only' if _offline(info) else 'Local metadata'})
                    except OSError:
                        issues.append({'relative': relative, 'reason': 'Metadata unavailable; not treated as deleted.'})
        except OSError:
            issues.append({'relative': folder.relative_to(base).as_posix(),
                           'reason': 'Folder unavailable; not treated as empty.'})
    files.sort(key=lambda row: row['relative'].casefold())
    counts = dict(Counter(row['category'] for row in files))
    return {'ok': True, 'job_id': str(job_id), 'files': files, 'issues': issues,
            'counts': counts, 'limited': limited, 'complete': not limited and not issues,
            'mode': 'preview', 'registered': False,
            'note': 'Mapping preview only. Nothing uploaded, moved, deleted or registered in the shared database.'}
