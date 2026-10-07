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
        self._schedule_import_preview = None

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

    def schedule_history(self, start, end, expected_context):
        import schedule_store
        import run_history_store
        try:
            store = schedule_store.ScheduleStore(expected_context)
            return {'ok': True, 'documents': run_history_store.documents(store, start, end)}
        except Exception as ex:
            return schedule_store.failure(ex)

    def schedule_history_rows(self, document_id, expected_context):
        import schedule_store
        import run_history_store
        try:
            store = schedule_store.ScheduleStore(expected_context)
            return {'ok': True, 'rows': run_history_store.rows(store, document_id)}
        except Exception as ex:
            return schedule_store.failure(ex)

    def schedule_history_link(self, row_id, job_id, revision, expected_context):
        import schedule_store
        import run_history_store
        try:
            store = schedule_store.ScheduleStore(expected_context)
            return {'ok': True, 'revision': run_history_store.link(store, row_id, job_id, revision)}
        except Exception as ex:
            result = schedule_store.failure(ex)
            if result.get('conflict'):
                result['error'] = 'This history link changed elsewhere. Close this Run and reopen it before correcting the link.'
            return result

    def schedule_search(self, query, expected_context):
        import schedule_store
        try:
            store = schedule_store.ScheduleStore(expected_context)
            return {'ok': True, 'jobs': store.search(query)}
        except Exception as ex:
            return schedule_store.failure(ex)

    def schedule_confirmation_preview(self, day, expected_context):
        import schedule_store
        import schedule_confirmation
        try:
            store = schedule_store.ScheduleStore(expected_context)
            return {'ok': True, 'review': schedule_confirmation.preview(store, day)}
        except Exception as ex:
            return schedule_store.failure(ex)

    def schedule_confirm_day(self, command, expected_context):
        import schedule_store
        import schedule_confirmation
        try:
            store = schedule_store.ScheduleStore(expected_context)
            result = schedule_confirmation.confirm(store, command)
        except Exception as ex:
            result = schedule_store.failure(ex)
            if result.get('conflict'):
                result['error'] = 'The day or a card changed during review. Reload the review before confirming; no partial moves were saved.'
            return result
        # Confirmation is already durable. Worker startup failure must not turn
        # success into an ambiguous save error; pending placements retry later.
        try:
            import card_placements
            card_placements.start_sync(force=True)
        except Exception:
            pass
        return {'ok': True, 'result': result}

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
            import schedule_bulk_import
            entries, skipped = schedule_bulk_import.commands(result, store.jobs())
            self._schedule_import_preview = {'context': store.context_id,
                'key':result['import_key'], 'entries':entries}
            result.update(bulk_entries=entries, skipped=skipped)
            return {'ok': True, 'preview': result}
        except Exception as ex:
            return schedule_store.failure(ex)

    def schedule_import_all(self, import_key, expected_context):
        import schedule_store
        try:
            store=schedule_store.ScheduleStore(expected_context)
            preview=self._schedule_import_preview
            if not preview or preview['context']!=store.context_id or preview['key']!=import_key:
                raise ValueError('Choose the document again in the current office before importing.')
            return {'ok':True, 'result':store.import_entries(preview['entries'])}
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
        """Scheduling-only people plus local tech additions; never login users."""
        try:
            import audit_logic
            import persistence
            audit_logic.ensure_roster_seeded()
            roster = persistence.get_user_techs() or {}
            import scheduling_roster
            return {'ok': True, 'entries': scheduling_roster.entries(
                config.active_department(), roster)}
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
