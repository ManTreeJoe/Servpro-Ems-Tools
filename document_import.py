"""Copy-only document import planning. No DB calls, hydration, or source writes.

The approved plan is a snapshot, not a command to rescan and import new files.
Each selected file is checked again before upload; changed files need a new plan.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path, PurePosixPath
import stat
import unicodedata
from uuid import UUID

MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_PLAN_BYTES = 250 * 1024 * 1024
MAX_ENTRIES = 10000
MIME_TYPES = {
    '.pdf': 'application/pdf', '.doc': 'application/msword',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.xls': 'application/vnd.ms-excel',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.txt': 'text/plain', '.csv': 'text/csv', '.rtf': 'application/rtf',
}
_OFFLINE = 0x1000 | 0x40000 | 0x400000
_REPARSE = 0x400


@dataclass(frozen=True)
class Document:
    relative_path: str
    byte_size: int
    modified_ns: int
    sha256: str
    content_type: str

    @property
    def modified_at(self):
        return datetime.fromtimestamp(self.modified_ns / 1e9, timezone.utc).isoformat()


@dataclass(frozen=True)
class ImportPlan:
    job_id: str
    root: Path
    documents: tuple[Document, ...]
    skipped: tuple[tuple[str, str], ...]


def clean_relative(value):
    """Strict portable paths, without silently renaming the user's files."""
    if not isinstance(value, str) or not value or len(value) > 1000:
        raise ValueError('Invalid document path.')
    if '\\' in value or ':' in value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('Invalid document path.')
    if any(p in ('', '.', '..') or p != p.strip() for p in value.split('/')):
        raise ValueError('Invalid document path.')
    if PurePosixPath(value).suffix.lower() not in MIME_TYPES:
        raise ValueError('Only document files are included in this pilot.')
    return value


def _check_stat(info):
    flags = getattr(info, 'st_file_attributes', 0)
    if flags & _OFFLINE:
        raise ValueError('Online-only: download in OneDrive before importing.')
    if stat.S_ISLNK(info.st_mode) or flags & _REPARSE:
        # A hydrated OneDrive reparse point may be safe, but fail closed for the
        # first pilot rather than accidentally following a junction/symlink.
        raise ValueError('Linked/reparse file or folder: not included in the pilot.')


def _safe_file(root, relative):
    clean_relative(relative)
    _check_stat(root.lstat())
    target = root
    for part in relative.split('/'):
        target = target / part
        _check_stat(target.lstat())
    if not target.resolve().is_relative_to(root.resolve()) or not target.is_file():
        raise ValueError('Document is outside the selected job folder or unavailable.')
    return target


def _read(root, relative):
    target = _safe_file(root, relative)
    before = target.stat()
    if not 0 < before.st_size <= MAX_FILE_BYTES:
        raise ValueError('Document must be nonempty and at most 50 MB.')
    with target.open('rb') as stream:
        opened = os.fstat(stream.fileno())
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError('Document changed while opening. Preview again.')
        data = stream.read(MAX_FILE_BYTES + 1)
        after = os.fstat(stream.fileno())
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or len(data) != before.st_size:
        raise ValueError('Document changed while reading. Preview again.')
    # Also reject path replacement/junction changes during the read.
    final = _safe_file(root, relative).stat()
    if (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns) != (
            before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns):
        raise ValueError('Document changed while reading. Preview again.')
    return data, before


def plan_import(job_id, root):
    job_id = str(UUID(str(job_id)))  # No title matching or accidental new jobs.
    if not root:
        raise ValueError('Choose the job folder first.')
    base = Path(os.path.abspath(root))
    _check_stat(base.lstat())
    if not base.is_dir():
        raise ValueError('Job folder is unavailable.')
    documents, skipped, seen = [], [], set()
    pending, count, total = [base], 0, 0
    while pending:
        folder = pending.pop()
        _check_stat(folder.lstat())
        with os.scandir(folder) as entries:
            for entry in entries:
                count += 1
                if count > MAX_ENTRIES:
                    raise ValueError('Folder is too large for a pilot preview. Choose a smaller folder.')
                relative = Path(entry.path).relative_to(base).as_posix()
                try:
                    info = entry.stat(follow_symlinks=False)
                    _check_stat(info)
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(Path(entry.path))
                        continue
                    clean_relative(relative)
                    key = unicodedata.normalize('NFC', relative).lower()
                    if key in seen:
                        raise ValueError('Duplicate portable document path. Rename before importing.')
                    seen.add(key)
                    if total + info.st_size > MAX_PLAN_BYTES:
                        raise ValueError('Pilot preview exceeds 250 MB; choose a smaller folder.')
                    data, info = _read(base, relative)
                    total += len(data)
                    documents.append(Document(relative, len(data), info.st_mtime_ns,
                                              hashlib.sha256(data).hexdigest(), MIME_TYPES[Path(relative).suffix.lower()]))
                except (OSError, ValueError) as error:
                    skipped.append((relative, str(error)))
    return ImportPlan(job_id, base, tuple(sorted(documents, key=lambda d: d.relative_path.lower())), tuple(skipped))


def read_approved_document(plan, document):
    if document not in plan.documents:
        raise ValueError('Document was not included in this preview.')
    data, info = _read(plan.root, document.relative_path)
    if (len(data), info.st_mtime_ns, hashlib.sha256(data).hexdigest()) != (
            document.byte_size, document.modified_ns, document.sha256):
        raise ValueError('Document changed after preview. Preview again before importing.')
    return data


def import_plan(plan, store, progress=None):
    """Explicitly execute one reviewed plan. Errors stop, preserving prior copies.

    store is a permission-enforcing adapter with check_job/prepare/upload/read/
    confirm methods. Retry the plan after a failure: server preparation resumes
    pending versions and skips verified unchanged versions.
    """
    store.check_job(plan.job_id)
    imported = unchanged = 0
    for index, document in enumerate(plan.documents):
        data = read_approved_document(plan, document)
        prepared = store.prepare(plan.job_id, document)
        version = prepared['version']
        if prepared['action'] == 'unchanged':
            unchanged += 1
        elif prepared['action'] == 'upload':
            store.upload(version, data)
            copied = store.read(version)
            if len(copied) != document.byte_size or hashlib.sha256(copied).hexdigest() != document.sha256:
                raise ValueError('Cloud read-back verification failed. The original file is unchanged.')
            store.confirm(version['version_id'])
            imported += 1
        else:
            raise ValueError('Unknown document import response.')
        if progress:
            progress(index + 1, len(plan.documents), document.relative_path)
    return {'imported': imported, 'unchanged': unchanged, 'skipped': len(plan.skipped)}
