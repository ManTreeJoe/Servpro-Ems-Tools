"""A hand-moved tracked-snapshot row has to STAY where it was put.

Sheet routing is recomputed on every sync, so a row the user moved by
hand was silently moved back the next time the audit ran — the change
looked like it took, then quietly undid itself. `move_existing_row` now
pins the choice in the job DB and `_route_for` honours it.
"""
import datetime as dt

import pytest

import ems_db_sqlite
import snapshots_excel as sx


@pytest.fixture(autouse=True)
def _clean_db(tmp_path):
    """Each test gets its own job DB so pins don't leak between them."""
    ems_db_sqlite.reset_db_path(str(tmp_path / "jobs.db"))
    yield


# ── the pin store ───────────────────────────────────────────────────

def test_a_pin_round_trips():
    assert sx.get_sheet_pin("Pinny, Pat") == ""
    assert sx.set_sheet_pin("Pinny, Pat", sx._SHEET_INCOMPLETE) is True
    assert sx.get_sheet_pin("Pinny, Pat") == sx._SHEET_INCOMPLETE


def test_a_pin_is_single_valued():
    sx.set_sheet_pin("Pinny, Pat", sx._SHEET_INCOMPLETE)
    sx.set_sheet_pin("Pinny, Pat", sx._SHEET_COMPLETED)
    assert sx.get_sheet_pin("Pinny, Pat") == sx._SHEET_COMPLETED


def test_a_blank_sheet_clears_the_pin():
    sx.set_sheet_pin("Pinny, Pat", sx._SHEET_COMPLETED)
    sx.set_sheet_pin("Pinny, Pat", "")
    assert sx.get_sheet_pin("Pinny, Pat") == ""


def test_the_pin_follows_the_name_the_way_the_job_db_does():
    # Same job, different spelling of the same canonical key.
    sx.set_sheet_pin("Pinny, Pat - Mercury", sx._SHEET_ATTENTION)
    assert sx.get_sheet_pin("Pinny, Pat") == sx._SHEET_ATTENTION


def test_an_unknown_sheet_is_never_returned():
    # A renamed/removed sheet must not strand the row somewhere invalid.
    # job_links is FK'd to jobs, so the job has to exist to carry a link.
    key = ems_db_sqlite.upsert_job(display_name="Ghost, Gary")
    ems_db_sqlite.set_link(key, sx._SHEET_PIN_LINK, "Some Old Sheet")
    assert sx.get_sheet_pin("Ghost, Gary") == ""


def test_a_job_the_index_has_never_seen_can_still_be_pinned():
    # The FK means the pin write fails outright for an unknown job —
    # which silently reverted the hand-move. set_sheet_pin registers the
    # job and retries.
    assert ems_db_sqlite.get_job(ems_db_sqlite.canon_key("Brandnew, Bo")) is None
    assert sx.set_sheet_pin("Brandnew, Bo", sx._SHEET_INCOMPLETE) is True
    assert sx.get_sheet_pin("Brandnew, Bo") == sx._SHEET_INCOMPLETE


def test_a_dead_db_reads_as_no_pin(monkeypatch):
    # The workbook write must never be blocked by the DB being down.
    def boom(*_a, **_k):
        raise RuntimeError("db down")
    monkeypatch.setattr(ems_db_sqlite, "get_link", boom)
    assert sx.get_sheet_pin("Anyone, At All") == ""


# ── routing precedence ──────────────────────────────────────────────

def test_the_pin_beats_the_automatic_rules():
    # No claim# would normally demote this to Incomplete.
    r = {"client": "X", "_sheet_pin": sx._SHEET_COMPLETED}
    assert sx._route_for(r) == sx._SHEET_COMPLETED


def test_the_pin_beats_a_cancelled_comment():
    r = {"client": "X", "_existing_comment": "Cancelled by insured",
         "_sheet_pin": sx._SHEET_COMPLETED}
    assert sx._route_for(r) == sx._SHEET_COMPLETED


def test_the_pin_beats_the_new_loss_flag():
    r = {"client": "X", "new_loss": True, "_sheet_pin": sx._SHEET_INCOMPLETE}
    assert sx._route_for(r) == sx._SHEET_INCOMPLETE


def test_an_explicit_override_still_wins_over_the_pin():
    # Generating the PDF is a deliberate act describing a NEWER state.
    r = {"client": "X", "_route_override": "completed",
         "_sheet_pin": sx._SHEET_INCOMPLETE}
    assert sx._route_for(r) == sx._SHEET_COMPLETED


def test_no_pin_leaves_the_old_rules_exactly_as_they_were():
    assert sx._route_for({"client": "X", "new_loss": True}) == sx._SHEET_NEW
    assert sx._route_for({"client": "X", "_claim": "123"}) == sx._SHEET_COMPLETED
    assert sx._route_for({"client": "X"}) == sx._SHEET_INCOMPLETE


def test_a_garbage_pin_falls_through_to_the_rules():
    r = {"client": "X", "_claim": "123", "_sheet_pin": "Nonsense"}
    assert sx._route_for(r) == sx._SHEET_COMPLETED


# ── end to end: the actual complaint ────────────────────────────────

def _seed(tmp_path, monkeypatch, sheet, name):
    yr = dt.date.today().year
    path = str(tmp_path / f"{yr}.xlsx")
    monkeypatch.setattr(sx, "workbook_path", lambda y=None: path)
    wb = sx.openpyxl.Workbook()
    wb.remove(wb.active)
    for base in sx._ALL_SHEETS:
        ws = wb.create_sheet(sx._sheet_name(base, yr))
        sx._write_header(ws)
    ws = wb[sx._sheet_name(sheet, yr)]
    ws.cell(row=2, column=sx._COL_INDEX["Name"], value=name)
    wb.save(path)
    return yr, path


def test_a_hand_move_survives_the_next_sync(tmp_path, monkeypatch):
    name = "Sticky, Sue"
    yr, path = _seed(tmp_path, monkeypatch, sx._SHEET_COMPLETED, name)

    assert sx.move_existing_row(name, sx._SHEET_INCOMPLETE, year=yr) is True
    assert sx.get_sheet_pin(name) == sx._SHEET_INCOMPLETE

    # The next sync recomputes the route. Without the pin this row would
    # go straight back to Completed.
    r = {"client": name, "_claim": "123",
         "_sheet_pin": sx.get_sheet_pin(name)}
    assert sx._route_for(r) == sx._SHEET_INCOMPLETE


def test_a_failed_move_leaves_no_pin(tmp_path, monkeypatch):
    name = "Locked, Lou"
    yr, path = _seed(tmp_path, monkeypatch, sx._SHEET_COMPLETED, name)
    # Excel has the workbook open.
    monkeypatch.setattr(sx, "_is_locked", lambda p: True)

    assert sx.move_existing_row(name, sx._SHEET_INCOMPLETE, year=yr) is False
    assert sx.get_sheet_pin(name) == ""


def test_moving_a_row_that_does_not_exist_leaves_no_pin(tmp_path, monkeypatch):
    yr, path = _seed(tmp_path, monkeypatch, sx._SHEET_COMPLETED, "Someone Else")
    assert sx.move_existing_row("Absent, Amy", sx._SHEET_NEW, year=yr) is False
    assert sx.get_sheet_pin("Absent, Amy") == ""
