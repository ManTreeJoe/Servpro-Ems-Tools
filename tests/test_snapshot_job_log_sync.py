import snapshot_web as sw


class FakeDb:
    def __init__(self):
        self.saved = []

    def find_job_by_name(self, _client):
        return {"canon_key": "hoffman-carol"}

    def list_job_log_entries(self, _canon):
        return [{"entry_id": "entry-1", "work_date": "2026-08-21",
                 "work_type": "Demo", "status": "completed",
                 "technicians": "Marco C", "note": "Keep this detail",
                 "equipment": "2 air movers", "source": "trello",
                 "source_id": "comment-1", "trello_comment_id": "comment-1"}]

    def save_job_log_entry(self, _canon, entry):
        self.saved.append(dict(entry))
        return dict(entry)


def test_snapshot_edit_updates_existing_job_log_and_preserves_detail(monkeypatch):
    fake = FakeDb()
    import ems_db
    monkeypatch.setattr(ems_db, "find_job_by_name", fake.find_job_by_name)
    monkeypatch.setattr(ems_db, "list_job_log_entries", fake.list_job_log_entries)
    monkeypatch.setattr(ems_db, "save_job_log_entry", fake.save_job_log_entry)
    result = sw.sync_snapshot_logs_to_job_log("Hoffman, Carol", [{
        "entry_id": "entry-1", "date": "08-22-26",
        "activity": "Demo continued", "techs": "Marco C, Jose E"}], "Nathan")
    assert result["ok"] is True
    saved = fake.saved[0]
    assert saved["entry_id"] == "entry-1"
    assert saved["work_date"] == "2026-08-22"
    assert saved["work_type"] == "Demo continued"
    assert saved["note"] == "Keep this detail"
    assert saved["equipment"] == "2 air movers"
    assert saved["source"] == "trello"
    assert saved["updated_by"] == "Nathan"


def test_snapshot_new_row_creates_job_log_entry(monkeypatch):
    fake = FakeDb()
    fake.list_job_log_entries = lambda _canon: []
    import ems_db
    monkeypatch.setattr(ems_db, "find_job_by_name", fake.find_job_by_name)
    monkeypatch.setattr(ems_db, "list_job_log_entries", fake.list_job_log_entries)
    monkeypatch.setattr(ems_db, "save_job_log_entry", fake.save_job_log_entry)
    result = sw.sync_snapshot_logs_to_job_log("Hoffman, Carol", [{
        "date": "8/21/26", "activity": "Demo", "techs": "Marco C"}])
    assert result["ok"] is True
    assert fake.saved[0]["source"] == "snapshot"
    assert fake.saved[0]["status"] == "completed"
