"""Bounded local folder evidence; no cloud requests or account inference."""
import os


def docusketch_folder(path):
    if not path:
        return {'status': 'unlinked'}
    pending = [(path, 0)]
    checked = 0
    failed = False
    while pending and checked < 300:
        directory, depth = pending.pop()
        checked += 1
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    if entry.name.casefold() == 'docusketch':
                        return {'status': 'found', 'path': entry.path}
                    if depth < 2:
                        pending.append((entry.path, depth + 1))
        except OSError:
            failed = True
    return {'status': 'unknown' if failed or pending else 'not_found'}
