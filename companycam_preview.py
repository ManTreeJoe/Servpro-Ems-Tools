"""Short-lived, server-held photo lists for one exact visit-selection dialog."""
from copy import deepcopy
import threading
import time
import uuid


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


previews = PreviewStore()
