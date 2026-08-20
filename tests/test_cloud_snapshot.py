"""The shared database's backup.

Since the cloud cutover the live data is in Supabase and `ems_jobs.db` is
only the offline mirror — so `data_backup.py`, which copies that mirror,
was backing up a cache while the real database had no export path at all
(`export_db` is `_unsupported` on this backend).

The trap when filling that gap is reaching for `export_db`'s semantics.
That function is a SHARING format: it filters links down to Trello +
folders and drops `job_events` outright, because a machine-specific
SharePoint cache is meaningless on another franchise's PC. Measured
against live, its list captures 463 jobs and misses roughly 3,577 rows —
every `job_children` row (the unit/claim hierarchy), every lifecycle row,
every stage transition. A backup built on it would restore a database
with no children and no name history, and would look complete doing it.
"""
import io
import json
import os

import pytest

import ems_db_supabase as sb


@pytest.fixture
def fake_rows(monkeypatch):
    """Stand in for the network. Returns the call log."""
    seen = []

    def _rows(table, **params):
        seen.append(table)
        return [{"t": table, "i": 1}, {"t": table, "i": 2}]

    monkeypatch.setattr(sb, "_rows", _rows)
    return seen


def test_every_table_is_captured(tmp_path, fake_rows):
    out = str(tmp_path / "cloud.json")
    res = sb.snapshot(out)
    assert res["ok"] is True and res["errors"] == {}
    assert set(fake_rows) == set(sb._SNAPSHOT_TABLES)
    data = json.load(io.open(out, encoding="utf-8"))
    assert set(data["tables"]) == set(sb._SNAPSHOT_TABLES)
    assert all(n == 2 for n in res["counts"].values())


def test_the_identity_tables_are_in_the_list():
    """The guardrail.

    These four are exactly what `export_db` throws away, and they are the
    ones that make a job what it is. Trimming the list back to the
    sharing format is the mistake this test exists to catch — it would
    not fail anything else, because a snapshot missing them still writes
    a perfectly valid file.
    """
    for table in ("job_children", "job_events", "job_lifecycle",
                  "job_stage_transitions"):
        assert table in sb._SNAPSHOT_TABLES, table


def test_a_failed_table_writes_no_file(tmp_path, monkeypatch):
    """Incomplete must not look complete.

    A short file discovered at restore time is the one moment the gap
    can't be repaired, so nothing is written at all and `ok` is False.
    """
    def _rows(table, **params):
        if table == "job_children":
            raise RuntimeError("boom")
        return [{"t": table}]

    monkeypatch.setattr(sb, "_rows", _rows)
    out = str(tmp_path / "cloud.json")
    res = sb.snapshot(out)

    assert res["ok"] is False
    assert "job_children" in res["errors"]
    assert not os.path.exists(out)
    # ...and no debris either.
    assert os.listdir(str(tmp_path)) == []


def test_the_other_tables_survive_one_failure(tmp_path, monkeypatch):
    """One table failing must not cost the rest.

    Losing app_user_departments to a permission rule should still report
    what the jobs table held, so the operator can see how much is intact.
    """
    def _rows(table, **params):
        if table == "app_user_departments":
            raise RuntimeError("denied")
        return [{"t": table}]

    monkeypatch.setattr(sb, "_rows", _rows)
    res = sb.snapshot("")
    assert res["ok"] is False
    assert res["counts"]["jobs"] == 1
    assert "app_user_departments" not in res["counts"]


def test_no_path_returns_the_payload(fake_rows):
    res = sb.snapshot("")
    assert res["ok"] is True
    assert set(res["data"]["tables"]) == set(sb._SNAPSHOT_TABLES)
    assert res["data"]["taken_at"]
