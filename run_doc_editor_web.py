"""Pywebview API for the in-app daily Run Doc Editor."""
from __future__ import annotations

import datetime as _dt
import os

import config
import run_doc
import run_doc_editor as editor


class Api:
    def __init__(self):
        self._window = None

    def attach(self, window):
        self._window = window

    @staticmethod
    def _day(offset=0):
        return _dt.date.today() + _dt.timedelta(days=int(offset or 0))

    def load_day(self, day_offset: int = 0) -> dict:
        day = self._day(day_offset)
        try:
            path = run_doc._find_run_doc_for_date(day)
            base = {
                "ok": True,
                "date_iso": day.isoformat(),
                "date_label": day.strftime("%A, %B %-d, %Y")
                if os.name != "nt" else day.strftime("%A, %B %#d, %Y"),
                "day_offset": int(day_offset or 0),
                "department": config.active_department(),
            }
            if not path:
                return {**base, "exists": False, "editable": False,
                        "error": "No run document was found for this day."}
            if not path.lower().endswith(".docx"):
                return {**base, "exists": True, "editable": False,
                        "path": path, "filename": os.path.basename(path),
                        "error": "This department still uses an Outlook run "
                                 "message. Word editing is available for .docx "
                                 "run documents."}
            model = editor.read_document(path)
            return {**base, **model, "exists": True, "editable": True}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def save_day(self, day_offset: int, version: str, sections: dict) -> dict:
        day = self._day(day_offset)
        try:
            path = run_doc._find_run_doc_for_date(day)
            if not path:
                return {"ok": False, "error": "The run document no longer exists."}
            result = editor.save_document(path, version, sections)
            return {"ok": True, **result}
        except editor.RunDocConflict as ex:
            return {"ok": False, "conflict": True, "error": str(ex)}
        except PermissionError:
            return {"ok": False, "locked": True,
                    "error": "Word or OneDrive is holding the document open. "
                             "Close the file in Word, then save again."}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def open_word(self, day_offset: int = 0) -> bool:
        try:
            path = run_doc._find_run_doc_for_date(self._day(day_offset))
            if path and os.path.isfile(path):
                os.startfile(path)
                return True
        except Exception:
            pass
        return False
