"""📚 Resources — search the reference material on the share.

The index behind this is `resources_index`; see its docstring for why it
is a rebuilt SQLite index rather than a live walk (49,602 files, 47.6s).

This panel is the reading end: type, get files, open the file or the
folder it lives in. The rebuild runs on a thread with progress, because
47 seconds of frozen window is indistinguishable from a hang.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading

import webview

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import resources_index as ri          # noqa: E402

ASSETS_DIR = os.path.join(_HERE, "resources_web_assets")
INDEX_HTML = os.path.join(ASSETS_DIR, "index.html")


class Api:
    def __init__(self):
        self._window = None
        self._building = False

    def attach(self, w):
        self._window = w

    # ── reading ──────────────────────────────────────────────────────
    def stats(self) -> dict:
        try:
            s = ri.stats()
            s["areas"] = ri.top_folders()
            s["building"] = self._building
            return s
        except Exception as ex:
            return {"ok": False, "error": str(ex), "files": 0, "areas": []}

    def search(self, query: str = "", ext: str = "", top: str = "",
               limit: int = 100) -> dict:
        try:
            rows = ri.search(query, ext=ext, top=top, limit=limit)
            for r in rows:
                r["size_kb"] = round((r.get("size") or 0) / 1024)
            return {"ok": True, "rows": rows, "count": len(rows)}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "rows": []}

    # ── rebuilding ───────────────────────────────────────────────────
    def rebuild(self) -> dict:
        """Kick off a rebuild on a thread and return immediately.

        47 seconds of blocked UI reads as a crash, so the window stays
        live and `rebuild_progress` reports where it is.
        """
        if self._building:
            return {"ok": False, "error": "already rebuilding"}
        self._building = True
        self._progress = {"done": 0, "total": 0, "files": 0}
        self._result = None
        # Resolve the root HERE, not inside the thread. A thread that
        # reads its configuration later reads whatever the configuration
        # has become by then — which is how a test's rebuild outlived the
        # test, lost its redirected paths, and overwrote the live index
        # with one row.
        base = ri.default_root()

        def _run():
            try:
                self._result = ri.rebuild(base, progress_cb=self._on_progress)
            except Exception as ex:
                self._result = {"ok": False, "error": str(ex)}
            finally:
                self._building = False

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        return {"ok": True, "started": True}

    def wait_for_rebuild(self, timeout: float = 300) -> bool:
        """Block until a running rebuild finishes. For tests and shutdown
        — a rebuild that outlives its caller writes wherever the process
        happens to point by then."""
        t = getattr(self, "_thread", None)
        if t is None:
            return True
        t.join(timeout)
        return not t.is_alive()

    def _on_progress(self, d):
        self._progress = d

    def rebuild_progress(self) -> dict:
        return {"ok": True, "building": self._building,
                "progress": getattr(self, "_progress", {}),
                "result": getattr(self, "_result", None)}

    # ── opening ──────────────────────────────────────────────────────
    def open_file(self, path: str) -> dict:
        """Open a file with whatever Windows associates with it.

        The index can outlive the share — a file moved since the last
        rebuild is the normal case, not an error, so say so plainly
        instead of raising.
        """
        if not path:
            return {"ok": False, "error": "no path"}
        if not os.path.exists(path):
            return {"ok": False,
                    "error": "That file has moved or been deleted since the "
                             "last rebuild — try ↻ Rebuild."}
        try:
            os.startfile(path)                       # noqa: S606 (Windows)
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def open_folder(self, path: str) -> dict:
        """Reveal the file in Explorer, selected."""
        if not path:
            return {"ok": False, "error": "no path"}
        target = path if os.path.isdir(path) else os.path.dirname(path)
        if not os.path.isdir(target):
            return {"ok": False, "error": "That folder is gone — try ↻ Rebuild."}
        try:
            if os.path.isfile(path):
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            else:
                os.startfile(target)                 # noqa: S606
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def copy_path(self, path: str) -> dict:
        """The path as text — for pasting into an email or a chat."""
        if not path:
            return {"ok": False, "error": "no path"}
        try:
            import pyperclip
            pyperclip.copy(path)
            return {"ok": True}
        except Exception:
            # No clipboard module: hand it back and let the page copy it.
            return {"ok": False, "text": path, "error": "clipboard unavailable"}


def main(argv=None):
    api = Api()
    win = webview.create_window(
        title="📚 Resources — Linguar Hub",
        url=INDEX_HTML, js_api=api,
        width=1180, height=860, min_size=(760, 520))
    api.attach(win)
    webview.start(debug=False)


if __name__ == "__main__":
    main()
