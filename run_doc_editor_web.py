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

    def schedule_load(self):
        import schedule_store
        try:
            store = schedule_store.ScheduleStore()
            return {'ok': True, 'context': store.context_id,
                    'department': store.department, 'records': store.load()}
        except Exception as ex:
            return schedule_store.failure(ex)

    def schedule_search(self, query, expected_context):
        import schedule_store
        try:
            store = schedule_store.ScheduleStore(expected_context)
            return {'ok': True, 'jobs': store.search(query)}
        except Exception as ex:
            return schedule_store.failure(ex)

    def schedule_realtime(self, expected_context):
        """Short-lived user credentials, never a service key; RLS owns access."""
        import schedule_store
        try:
            store = schedule_store.ScheduleStore(expected_context)
            return {'ok': True, 'url': store.url, 'key': store.key,
                    'token': store.token, 'department': store.department}
        except Exception as ex:
            return schedule_store.failure(ex)

    def schedule_pick_document(self, date_iso, expected_context):
        """Native selection and immutable read only; never edits the source."""
        import schedule_import
        import schedule_records
        import schedule_store
        try:
            store = schedule_store.ScheduleStore(expected_context)
            day = _dt.date.fromisoformat(schedule_records.day(date_iso))
            if not self._window:
                raise ValueError('Open Schedule in the desktop app to choose a document.')
            import webview
            selected = self._window.create_file_dialog(webview.OPEN_DIALOG,
                allow_multiple=False, file_types=('Word Run document (*.docx)',))
            if not selected:
                return {'ok': True, 'canceled': True}
            path = selected[0] if isinstance(selected, (tuple, list)) else selected
            try:
                result = schedule_import.draft_rows(schedule_import.preview(
                    path, day=day, workspace=store.department))
            except ValueError:
                raise
            except Exception:
                raise ValueError('The document could not be read. Choose a valid, locally available .docx Run file.') from None
            store.check()
            return {'ok': True, 'preview': result}
        except Exception as ex:
            return schedule_store.failure(ex)

    def schedule_save(self, command, expected_context):
        import schedule_store
        try:
            store = schedule_store.ScheduleStore(expected_context)
            saved = store.save(command)
            return {'ok': True, 'saved': saved}
        except Exception as ex:
            return schedule_store.failure(ex)

    def get_crew_roster(self):
        """Use the same editable roster as Snapshot and technician recognition."""
        try:
            import audit_logic
            import persistence
            audit_logic.ensure_roster_seeded()
            roster = persistence.get_user_techs() or {}
            aliases = roster.get('abbrev') or {}
            return {'ok': True, 'entries': [
                {'name': name, 'aliases': [key for key, value in aliases.items() if value == name]}
                for name in sorted(set(roster.get('names') or []), key=str.casefold)]}
        except Exception:
            return {'ok': False, 'entries': [], 'error': 'Technician roster unavailable. You can still enter crew names manually.'}

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
        except PermissionError:
            return {"ok": False, "exists": True, "editable": False, "locked": True,
                    "date_iso": day.isoformat(), "date_label": day.strftime("%A, %B %d, %Y"),
                    "error": "The Run document was found, but Windows denied access. "
                             "Close it in Word and check OneDrive has downloaded it, then reload. "
                             "If this continues, check your folder permissions."}
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

    def preview_schedule_import(self, day_offset: int = 0,
                                expected_date: str = "", expected_workspace: str = "") -> dict:
        """Prepare the selected office Run for review; do not activate/import it."""
        import schedule_import
        try:
            day = self._day(day_offset)
            workspace = config.active_department()
            if ((expected_date and expected_date != day.isoformat()) or
                    (expected_workspace and expected_workspace != workspace)):
                return {"ok": False, "error": "The selected day or workspace changed. Reload the Schedule and try again."}
            path = run_doc._find_run_doc_for_date(day)
            if not path:
                return {"ok": False, "error": "No run document was found for this day."}
            result = schedule_import.preview(path, day=day, workspace=workspace)
            if config.active_department() != workspace:
                return {"ok": False, "error": "The workspace changed while reading the Run. Reopen the preview in the current workspace."}
            return result
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def print_preview(self, day_offset: int = 0) -> dict:
        from office_print import preview_document
        try:
            return preview_document(run_doc._find_run_doc_for_date(self._day(day_offset)))
        except Exception:
            return {'ok': False, 'error': 'The Run document could not be located. Reload the selected day and try again.'}

    def open_word(self, day_offset: int = 0) -> bool:
        try:
            path = run_doc._find_run_doc_for_date(self._day(day_offset))
            if path and os.path.isfile(path):
                os.startfile(path)
                return True
        except Exception:
            pass
        return False
