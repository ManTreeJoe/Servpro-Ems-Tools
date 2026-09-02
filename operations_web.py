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
        # Keep native pywebview objects private. Public attributes on a JS API
        # are recursively exposed; publishing the Window makes the bridge walk
        # WinForms AccessibilityObject forever during startup.
        self._window = None

    def attach(self, window):
        self._window = window

    def bootstrap(self, force=False):
        return self.hub.bootstrap(bool(force))

    def appearance_preferences(self):
        from web_appearance import preferences
        return preferences()

    def client_account(self, name):
        return self.hub.client_account(name)

    def connections(self):
        return self.hub.connections()

    def account_sign_in(self, email, password):
        return self.hub.account_sign_in(email, password)

    def account_sign_out(self):
        return self.hub.account_sign_out()

    def begin_connection(self, provider):
        return self.hub.begin_connection(provider)

    def job_context(self, client, card_id="", division="EMS"):
        return self.hub.job_context(client, card_id, division)

    def job_action(self, action, job):
        return self.hub.job_action(action, job)

    def save_job_update(self, client, entry):
        return self.hub.save_job_update(client, entry)

    def field_note_templates(self, division="EMS"):
        return self.hub.field_note_templates(division)

    def save_field_note(self, client, note_type, values, division="EMS",
                        source_id=""):
        return self.hub.save_field_note(
            client, note_type, values, division, source_id)

    def import_job_log(self, client, card_id=""):
        return self.hub.import_job_log(client, card_id)

    def set_job_requirement(self, client, requirement_key, state, note="",
                            details=None, card_id="", division="EMS"):
        return self.hub.set_job_requirement(
            client, requirement_key, state, note, details, card_id, division)

    def copy_text(self, text):
        from web_helpers import set_clipboard_text
        return {"ok": bool(set_clipboard_text(str(text or "")))}

    def launch_tool(self, tool):
        from operations_tools import launch_desktop
        return launch_desktop(tool)

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
