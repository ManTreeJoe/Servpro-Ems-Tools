"""Standalone desktop shell for the experimental Operations Hub."""
from __future__ import annotations

import os
import sys
import webview

from operations_hub import OperationsHub


HERE = os.path.dirname(os.path.abspath(__file__))
INDEX_HTML = os.path.join(HERE, "operations_web_assets", "index.html")


class Api:
    def __init__(self, hub=None):
        self.hub = hub or OperationsHub()
        self.window = None

    def attach(self, window):
        self.window = window

    def bootstrap(self, force=False):
        return self.hub.bootstrap(bool(force))

    def client_account(self, name):
        return self.hub.client_account(name)

    def open_url(self, url):
        value = str(url or "").strip()
        if not value.lower().startswith(("https://", "http://")):
            return False
        import dept_browser
        dept_browser.open_url(value)
        return True

    def open_folder(self, path):
        value = str(path or "").strip()
        if not value or not os.path.isdir(value):
            return {"ok": False, "error": "That folder is not available on this PC."}
        os.startfile(value)
        return {"ok": True}


def main(argv=None):
    api = Api()
    window = webview.create_window(
        "Operations Hub — Linguar Hub Trial", INDEX_HTML, js_api=api,
        width=1480, height=900, min_size=(760, 560),
    )
    api.attach(window)
    webview.start(debug="--debug" in (argv or sys.argv[1:]), http_server=True)


if __name__ == "__main__":
    main()
