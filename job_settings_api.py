"""The ⚙ Job info API, shared by every panel that renders the job card.

`web_shared/audit_detail.js` is ONE detail card used by both Audit and
Snapshot, so any button it draws must work in both. Defining these methods
on audit_web alone would put a ⚙ Job info button in Snapshot that fails
the moment it's pressed.

A mixin rather than a copy in each file: the same three methods pasted
twice is the setup where one gets a fix and the other doesn't.
"""


class JobSettingsApi:
    """Mix into a panel's `Api` class. pywebview exposes inherited methods
    exactly like defined ones."""

    def job_settings_schema(self) -> dict:
        """Field list plus which are shown up front."""
        try:
            import job_settings
            return {"ok": True, "fields": job_settings.schema()}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def job_settings_load(self, client: str, child_name: str = "") -> dict:
        """Values for a job (or one of its units/claims), merged per field
        with the Trello card. Pulls the card once — about half a second."""
        try:
            import ems_db
            import job_settings
            key = ems_db.canon_key(client or "")
            if not key:
                return {"ok": False, "error": "no job name"}
            return job_settings.load(key, child_name or "")
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def job_settings_save(self, client: str, values: dict,
                          child_name: str = "", card_desc: str = "") -> dict:
        """Save, and push only the fields that differ from the card.

        `card_desc` is the description the edit was based on, handed back
        from load(). Reusing it avoids a second fetch and keeps the diff
        honest — re-fetching here would diff against a card that may have
        moved while the user was typing.
        """
        try:
            import ems_db
            import job_settings
            key = ems_db.canon_key(client or "")
            if not key:
                return {"ok": False, "error": "no job name"}
            res = job_settings.save(key, values or {}, child_name or "",
                                    card_desc or "")
            try:
                import job_search
                job_search.invalidate_cache()   # a display name may have moved
            except Exception:
                pass
            return res
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
