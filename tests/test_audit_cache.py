"""Audit re-run cache: OK results survive a re-run, flagged ones never
do. The cache is keyed by run_date + client + unit, scoped to the
folder's mtime signature.

These pin the behavior so a future refactor can't quietly turn caching
off for the user's "I just want to re-check the missing ones" flow."""
import os

import pytest

import audit_logic
import persistence


@pytest.fixture
def state_path(tmp_path, monkeypatch):
    """Redirect persistence to a tmp state.json so tests don't touch the
    user's real file."""
    p = tmp_path / "state.json"
    monkeypatch.setattr(persistence, "_STATE_PATH", str(p))
    monkeypatch.setattr(persistence, "_CACHE", None)
    monkeypatch.setattr(persistence, "_CACHE_MTIME", None)
    return p


@pytest.fixture
def ok_job_layout(tmp_path):
    """A fully-passing job layout: every required form/photo present."""
    base = tmp_path / "IE_Public"
    year = base / "2026 EMS Files"
    client = year / "Smith John"
    ems = client / "EMS"
    docs = ems / "DOCS"
    pics = ems / "PICS"
    initial = pics / "Initial"
    for d in (base, year, client, ems, docs, pics, initial):
        d.mkdir(parents=True, exist_ok=True)
    (initial / "img.jpg").write_bytes(b"x")
    # Drop every required form so check_forms passes.
    for fname, _pat in audit_logic.REQUIRED_FORMS:
        (ems / f"{fname}.pdf").write_bytes(b"x")
    # Initial photo report — satisfied by anything matching the regex.
    (docs / "initial photo report.pdf").write_bytes(b"x")
    # Docusketch with .esx
    docu = docs / "Docusketch"
    docu.mkdir()
    (docu / "scan.esx").write_bytes(b"x")
    return {"base": str(base), "client": "Smith John"}


@pytest.fixture
def flagged_job_layout(tmp_path):
    """Layout that audit will flag — missing PICS/Initial photo."""
    base = tmp_path / "IE_Public"
    year = base / "2026 EMS Files"
    client = year / "Jones Mary"
    ems = client / "EMS"
    pics = ems / "PICS"
    for d in (base, year, client, ems, pics):
        d.mkdir(parents=True, exist_ok=True)
    return {"base": str(base), "client": "Jones Mary"}


def test_ok_result_writes_to_cache(state_path, ok_job_layout):
    """A passing audit gets persisted under (run_date, client, unit)."""
    results, err = audit_logic.audit_jobs(
        [{"client": ok_job_layout["client"]}],
        ok_job_layout["base"],
        year=2026,
        run_date="04-30-2026",
    )
    assert err is None
    assert results and results[0]["found"]
    entry = persistence.get_audit_cache_entry(
        "04-30-2026", ok_job_layout["client"], None)
    assert entry is not None
    assert entry["path"].endswith("Smith John")
    assert entry["sig"] is not None
    # Result payload preserves form/photo issue lists for the cache hit
    # path to replay them.
    assert entry["result"]["found"] is True
    assert entry["result"]["form_issues"] == []
    assert entry["result"]["photo_issues"] == []


def test_flagged_result_skips_cache(state_path, flagged_job_layout):
    """Flagged jobs must always re-check on re-run, so we never persist
    them. The cache stays empty for that key."""
    results, err = audit_logic.audit_jobs(
        [{"client": flagged_job_layout["client"]}],
        flagged_job_layout["base"],
        year=2026,
        run_date="04-30-2026",
    )
    assert err is None
    assert results and results[0]["flagged"]
    entry = persistence.get_audit_cache_entry(
        "04-30-2026", flagged_job_layout["client"], None)
    assert entry is None


def test_cache_hit_skips_real_check(state_path, ok_job_layout, monkeypatch):
    """Second run with unchanged folder reuses the cached result instead
    of calling check_forms/check_photos again."""
    audit_logic.audit_jobs(
        [{"client": ok_job_layout["client"]}],
        ok_job_layout["base"],
        year=2026,
        run_date="04-30-2026",
    )
    calls = {"check_forms": 0, "check_photos": 0}

    real_forms = audit_logic.check_forms
    real_photos = audit_logic.check_photos

    def spy_forms(*a, **kw):
        calls["check_forms"] += 1
        return real_forms(*a, **kw)

    def spy_photos(*a, **kw):
        calls["check_photos"] += 1
        return real_photos(*a, **kw)

    monkeypatch.setattr(audit_logic, "check_forms", spy_forms)
    monkeypatch.setattr(audit_logic, "check_photos", spy_photos)

    results, err = audit_logic.audit_jobs(
        [{"client": ok_job_layout["client"]}],
        ok_job_layout["base"],
        year=2026,
        run_date="04-30-2026",
    )
    assert err is None
    assert results[0].get("from_cache") is True
    assert calls["check_forms"] == 0
    assert calls["check_photos"] == 0


def test_folder_change_invalidates_cache(state_path, ok_job_layout, monkeypatch):
    """When a file appears under the job folder, the mtime sig changes
    and the cached result is rejected — fresh check runs."""
    audit_logic.audit_jobs(
        [{"client": ok_job_layout["client"]}],
        ok_job_layout["base"],
        year=2026,
        run_date="04-30-2026",
    )
    # Add a new file directly under EMS so the depth=2 walk sees it.
    new_file = os.path.join(
        ok_job_layout["base"], "2026 EMS Files", "Smith John",
        "EMS", "extra_form.pdf")
    with open(new_file, "wb") as f:
        f.write(b"y")
    os.utime(new_file, (1900000000, 1900000000))

    calls = {"check_forms": 0}
    real_forms = audit_logic.check_forms

    def spy_forms(*a, **kw):
        calls["check_forms"] += 1
        return real_forms(*a, **kw)

    monkeypatch.setattr(audit_logic, "check_forms", spy_forms)
    results, err = audit_logic.audit_jobs(
        [{"client": ok_job_layout["client"]}],
        ok_job_layout["base"],
        year=2026,
        run_date="04-30-2026",
    )
    assert err is None
    # Cache miss → real check_forms ran exactly once.
    assert calls["check_forms"] == 1
    assert results[0].get("from_cache") is not True


def test_unit_separates_cache_keys(state_path, tmp_path):
    """Two jobs at the same property but different units must NOT share
    a cache slot — the unit field is part of the key."""
    base = tmp_path / "IE_Public"
    year = base / "2026 EMS Files"
    prop = year / "Keystone Highland Village (Unit 168)"
    ems = prop / "EMS"
    pics = ems / "PICS"
    initial = pics / "Initial"
    docs = ems / "DOCS"
    for d in (base, year, prop, ems, docs, pics, initial):
        d.mkdir(parents=True, exist_ok=True)
    (initial / "img.jpg").write_bytes(b"x")
    for fname, _pat in audit_logic.REQUIRED_FORMS:
        (ems / f"{fname}.pdf").write_bytes(b"x")
    (docs / "initial photo report.pdf").write_bytes(b"x")
    docu = docs / "Docusketch"
    docu.mkdir()
    (docu / "scan.esx").write_bytes(b"x")

    audit_logic.audit_jobs(
        [{"client": "Keystone Highland Village", "unit": "168"}],
        str(base), year=2026, run_date="04-30-2026")
    e168 = persistence.get_audit_cache_entry(
        "04-30-2026", "Keystone Highland Village", "168")
    e182 = persistence.get_audit_cache_entry(
        "04-30-2026", "Keystone Highland Village", "182")
    assert e168 is not None
    assert e182 is None  # different unit → different key, no collision


def test_no_run_date_disables_cache(state_path, ok_job_layout):
    """Callers that don't pass run_date (e.g. daily_photos_gui) get the
    old uncached behavior — nothing is written, nothing is read."""
    audit_logic.audit_jobs(
        [{"client": ok_job_layout["client"]}],
        ok_job_layout["base"],
        year=2026,
    )
    state = persistence._load()
    assert state.get("audit_cache", {}) == {}


def test_dispute_note_flags_otherwise_ok_job(state_path, ok_job_layout):
    """A run-doc line that mentions 'dispute' must flag the job and add
    a 'Address audit dispute' note even when forms+photos check clean."""
    results, err = audit_logic.audit_jobs(
        [{"client": ok_job_layout["client"],
          "raw": "Smith John: 123 Main / Audit Dispute - awaiting carrier"}],
        ok_job_layout["base"],
        year=2026,
    )
    assert err is None
    r = results[0]
    assert r["flagged"] is True
    assert r.get("note_issues")
    assert any("dispute" in s.lower() for s in r["note_issues"])
    # form/photo checks still clean — the flag came from the note
    assert r["form_issues"] == []
    assert r["photo_issues"] == []


def test_rejection_note_flags_job(state_path, ok_job_layout):
    """Same shape as dispute — 'rejection'/'rejected'/'denied' wording
    surfaces an 'Address audit rejection' callout."""
    results, _ = audit_logic.audit_jobs(
        [{"client": ok_job_layout["client"],
          "raw": "Smith John: 123 Main / audit rejected by carrier"}],
        ok_job_layout["base"],
        year=2026,
    )
    r = results[0]
    assert r["flagged"] is True
    assert any("rejection" in s.lower() for s in (r.get("note_issues") or []))


def test_dispute_note_blocks_caching(state_path, ok_job_layout, monkeypatch):
    """A dispute-only flag must keep the job out of the cache so the
    re-run still picks up the dispute (and re-runs check_forms etc. in
    case it cleared)."""
    audit_logic.audit_jobs(
        [{"client": ok_job_layout["client"],
          "raw": "Smith John: 123 Main / Audit Dispute"}],
        ok_job_layout["base"],
        year=2026,
        run_date="04-30-2026",
    )
    entry = persistence.get_audit_cache_entry(
        "04-30-2026", ok_job_layout["client"], None)
    assert entry is None  # flagged → not cached


def test_detect_dispute_notes_unit():
    """Pure function: returns the right callouts for the recognized
    keywords and nothing for unrelated text."""
    assert audit_logic.detect_dispute_notes("just a normal job line") == []
    out = audit_logic.detect_dispute_notes("Audit DISPUTE pending")
    assert len(out) == 1 and "dispute" in out[0].lower()
    out = audit_logic.detect_dispute_notes("xact rejection received")
    assert len(out) == 1 and "rejection" in out[0].lower()
    # Both in same line — both surface, in stable order.
    out = audit_logic.detect_dispute_notes("dispute and rejection both noted")
    assert len(out) == 2


def test_use_cache_false_bypasses(state_path, ok_job_layout, monkeypatch):
    """Callers can opt out per-run with use_cache=False even when
    run_date is set — used by future 'force re-audit' UI."""
    audit_logic.audit_jobs(
        [{"client": ok_job_layout["client"]}],
        ok_job_layout["base"],
        year=2026,
        run_date="04-30-2026",
    )
    calls = {"check_forms": 0}
    real_forms = audit_logic.check_forms

    def spy_forms(*a, **kw):
        calls["check_forms"] += 1
        return real_forms(*a, **kw)

    monkeypatch.setattr(audit_logic, "check_forms", spy_forms)
    audit_logic.audit_jobs(
        [{"client": ok_job_layout["client"]}],
        ok_job_layout["base"],
        year=2026,
        run_date="04-30-2026",
        use_cache=False,
    )
    assert calls["check_forms"] == 1
