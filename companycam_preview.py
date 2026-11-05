"""Short-lived, server-held photo lists for one exact visit-selection dialog."""
from copy import deepcopy
import threading
import time
import uuid
from datetime import datetime


def preview_url(photo):
    """Preview snapshots contain raw API records, not only downloader records."""
    by_type = {
        str(item.get('type') or '').lower(): item.get('uri') or item.get('url') or ''
        for item in (photo.get('uris') or []) if isinstance(item, dict)
    }
    # Do not silently load full-resolution originals for an entire gallery.
    for url in (photo.get('thumbnail_url'), by_type.get('thumbnail'), by_type.get('web')):
        if isinstance(url, str) and url.lower().startswith('https://'):
            return url
    return ''


class PreviewStore:
    def __init__(self, ttl=900, limit=8):
        self.ttl, self.limit = ttl, limit
        self._entries = {}
        self._lock = threading.Lock()

    def put(self, identity, photos):
        token = uuid.uuid4().hex
        with self._lock:
            self._prune()
            while len(self._entries) >= self.limit:
                self._entries.pop(next(iter(self._entries)))
            self._entries[token] = (time.monotonic(), identity, deepcopy(photos))
        return token

    def _prune(self):
        now = time.monotonic()
        for key, value in list(self._entries.items()):
            if now - value[0] >= self.ttl:
                self._entries.pop(key, None)

    def get(self, token, identity, selected):
        with self._lock:
            self._prune()
            value = self._entries.get(token)
            if value is None or value[1] != identity:
                raise ValueError('This photo preview expired or the job/account changed. Close and reopen Pull CompanyCam photos.')
            ids = {str(i) for i in selected}
            available = {str(p.get('id')) for p in value[2]}
            if not ids or not ids <= available:
                raise ValueError('The selected photos do not belong to this preview. Close and reopen Pull CompanyCam photos.')
            return deepcopy([p for p in value[2] if str(p.get('id')) in ids])

    def page(self, token, identity, offset=0, start=None, end=None):
        with self._lock:
            self._prune()
            value = self._entries.get(token)
            if value is None or value[1] != identity:
                raise ValueError('Photo preview expired or account changed. Close and reopen the preview.')
            def timestamp(photo):
                raw = photo.get('captured_at') or photo.get('created_at')
                try:
                    number = float(raw)
                    return number / 1000 if number > 1e11 else number
                except (TypeError, ValueError):
                    try:
                        return datetime.fromisoformat(str(raw).replace('Z', '+00:00')).timestamp()
                    except ValueError:
                        return 0
            photos = sorted(value[2], key=lambda p: (timestamp(p), str(p.get('id'))), reverse=True)
            if start is not None or end is not None:
                photos = [p for p in photos if timestamp(p) > 0
                          and (start is None or timestamp(p) >= float(start))
                          and (end is None or timestamp(p) < float(end))]
            offset = max(0, int(offset))
            rows = [{'id': str(p.get('id')), 'date': timestamp(p),
                     'creator': p.get('creator_name') or '',
                     'thumbnail': preview_url(p),
                     'image': next((u.get('uri') or u.get('url') for kind in ('web', 'original')
                                    for u in (p.get('uris') or []) if isinstance(u, dict)
                                    and str(u.get('type') or '').lower() == kind
                                    and str(u.get('uri') or u.get('url') or '').startswith('https://')),
                                   p.get('original_url') or preview_url(p))}
                    for p in photos[offset:offset + 36]]
            return {'ok': True, 'photos': rows, 'next': offset + len(rows),
                    'total': len(photos),
                    # Selection metadata includes unloaded photos, but not their image URLs.
                    'catalog': [{'id': str(p.get('id')), 'date': timestamp(p),
                                 'creator': p.get('creator_name') or ''} for p in photos] if offset == 0 else None}


previews = PreviewStore()
