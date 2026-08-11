"""
Shared in-memory cache + background prefetch.

Today every tool that needs the daily run doc re-parses the same .docx
independently — Run Audit and Daily Photos both call parse_run_doc().
The hub caches that parse keyed by path + mtime so the second consumer is
instant. It also runs a background prefetch on launcher startup so the
first consumer is also fast.

parse_run_doc() is a pure function of the .docx bytes, so this hub serves
it from an in-memory cache. audit_jobs() results live in a separate
persistence-backed cache (see persistence.get_audit_cache_entry) keyed by
folder mtime — re-runs reuse OK results when the folder hasn't changed.
"""
import os
import threading
from typing import Tuple, List, Dict, Any

import config


class _MtimeCache:
    """Thread-safe key→value cache that invalidates on file mtime change."""

    def __init__(self):
        self._lock = threading.Lock()
        self._data = {}  # key → (value, watch_path, watch_mtime)

    def get(self, key):
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            value, watch_path, cached_mtime = entry
            if watch_path:
                try:
                    if os.path.getmtime(watch_path) != cached_mtime:
                        del self._data[key]
                        return None
                except OSError:
                    return None
            return value

    def set(self, key, value, watch_path=None):
        mtime = 0.0
        if watch_path:
            try:
                mtime = os.path.getmtime(watch_path)
            except OSError:
                pass
        with self._lock:
            self._data[key] = (value, watch_path, mtime)

    def clear(self, key=None):
        with self._lock:
            if key is None:
                self._data.clear()
            else:
                self._data.pop(key, None)


class StateHub:
    """Singleton-ish state cache used by panels and prefetch."""

    def __init__(self):
        self._cache = _MtimeCache()
        self._prefetch_started = False

    # ── Run-doc parsing (cache by path+mtime) ───────────────────────────────
    def parse_run_doc(self, path: str) -> Tuple[List[Dict[str, Any]], str]:
        if not path or not os.path.isfile(path):
            return [], ""
        norm = os.path.normpath(path)
        key = ("parse_run_doc", norm)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        from run_doc import parse_run_doc as _parse
        result = _parse(norm)
        self._cache.set(key, result, watch_path=norm)
        return result

    def invalidate_run_doc(self, path: str = None):
        """Force re-parse on next access. Path=None clears all run-doc caches."""
        if path:
            self._cache.clear(("parse_run_doc", os.path.normpath(path)))
        else:
            # Clear any cache key starting with parse_run_doc
            with self._cache._lock:
                for k in list(self._cache._data.keys()):
                    if isinstance(k, tuple) and k[:1] == ("parse_run_doc",):
                        del self._cache._data[k]

    # ── Background prefetch ─────────────────────────────────────────────────
    def start_prefetch(self):
        """Kick off the prefetch worker once. Safe to call repeatedly."""
        if self._prefetch_started:
            return
        self._prefetch_started = True
        threading.Thread(target=self._prefetch_worker, daemon=True).start()

    def _prefetch_worker(self):
        """Warm the cache for the most recent run doc."""
        try:
            cfg = config.load()
        except Exception:
            return
        runs_dir = cfg.get("runs_dir", "")
        if not runs_dir or not os.path.isdir(runs_dir):
            return
        try:
            files = [
                (os.path.getmtime(os.path.join(runs_dir, f)),
                 os.path.join(runs_dir, f))
                for f in os.listdir(runs_dir)
                if f.lower().endswith(".docx") and not f.startswith("~$")
            ]
        except OSError:
            return
        if not files:
            return
        files.sort(reverse=True)
        latest = files[0][1]
        try:
            self.parse_run_doc(latest)
        except Exception as ex:
            try:
                import ems_log
                ems_log.warn("state_hub",
                    f"prefetch parse failed for {latest!r}: {ex}")
            except Exception:
                pass


hub = StateHub()
