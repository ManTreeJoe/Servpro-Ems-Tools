"""Read-only, directory-at-a-time job files. Never crawl or hydrate placeholders."""
import base64
import os
import io
from pathlib import Path

PHOTOS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
DOCUMENTS = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.txt', '.csv', '.rtf'}
MAX_PREVIEW = 16 * 1024 * 1024


def _target(root, relative=''):
    if not root:
        raise ValueError('Choose a job folder first using the Folder menu.')
    base = Path(root).resolve()
    target = (base / relative).resolve()
    if not target.is_relative_to(base):
        raise ValueError('That file is outside the pinned job folder.')
    return base, target


def _offline(stat):
    # OFFLINE, RECALL_ON_OPEN and RECALL_ON_DATA_ACCESS (OneDrive).
    return bool(getattr(stat, 'st_file_attributes', 0) & (0x1000 | 0x40000 | 0x400000))


def open_folder(root, relative=''):
    """Open only a verified directory within the saved job root."""
    try:
        _, folder = _target(root, relative)
        if not folder.is_dir():
            raise ValueError('This folder is unavailable. Check OneDrive or refresh the listing.')
        os.startfile(str(folder))
        return {'ok': True}
    except (OSError, ValueError) as error:
        return {'ok': False, 'error': str(error)}


def list_folder(root, relative=''):
    try:
        base, folder = _target(root, relative)
        rows = []
        with os.scandir(folder) as entries:
            for entry in entries:
                # Do not expose links/junctions escaping the job root.
                _, target = _target(base, os.path.relpath(entry.path, base))
                stat = entry.stat(follow_symlinks=False)
                directory = entry.is_dir(follow_symlinks=False)
                ext = target.suffix.lower()
                rows.append({'name': entry.name, 'relative': str(target.relative_to(base)),
                             'directory': directory, 'size': stat.st_size,
                             'offline': _offline(stat),
                             'kind': 'folder' if directory else 'photo' if ext in PHOTOS else 'document' if ext in DOCUMENTS else 'file'})
                if len(rows) >= 2000:
                    break
        rows.sort(key=lambda row: (not row['directory'], row['name'].casefold()))
        return {'ok': True, 'files': rows, 'relative': str(folder.relative_to(base)),
                'truncated': len(rows) >= 2000}
    except (OSError, ValueError) as error:
        return {'ok': False, 'error': str(error)}


def preview(root, relative, thumbnail=False):
    try:
        _, file = _target(root, relative)
        stat = file.stat()
        if _offline(stat):
            raise ValueError('This file is online-only. Download it in OneDrive, then retry.')
        ext = file.suffix.lower()
        if ext not in PHOTOS | {'.pdf'}:
            return {'ok': True, 'external': True}
        if stat.st_size > MAX_PREVIEW:
            raise ValueError('This file is too large for an inline preview. Open it in its app.')
        with file.open('rb') as stream:
            content = stream.read(MAX_PREVIEW + 1)
        if len(content) > MAX_PREVIEW:
            raise ValueError('This file is too large for an inline preview.')
        if thumbnail and ext in PHOTOS:
            from PIL import Image, ImageOps
            with Image.open(io.BytesIO(content)) as image:
                image.thumbnail((160, 120))
                image = ImageOps.exif_transpose(image).convert('RGB')
                output = io.BytesIO()
                image.save(output, format='JPEG', quality=75)
                content = output.getvalue()
                ext = '.jpg'
        mime = 'application/pdf' if ext == '.pdf' else 'image/' + {'.jpg': 'jpeg', '.jpeg': 'jpeg'}.get(ext, ext[1:])
        return {'ok': True, 'mime': mime, 'content': base64.b64encode(content).decode('ascii')}
    except (OSError, ValueError, ImportError) as error:
        return {'ok': False, 'error': str(error)}
