"""audit_jobs must accept a date/datetime OBJECT for run_date, not just a
string. The IUQ enrichment path (iuq_web._enrich_with_audit) calls
audit_jobs(clients, base, run_date=datetime.date.today(), ...). The
per-job note-logging then did strptime(run_date, fmt), which raises
TypeError on a date object (only ValueError was caught); the worker pool
swallowed it, so EVERY job dropped and audit_jobs returned 0 results —
silently breaking IUQ audit enrichment.

Pinning that audit_jobs coerces a date object up-front and returns the
same results it would for the equivalent string.
"""
import datetime as dt

import audit_logic as al


def _setup(tmp_path):
    base = tmp_path / "audit_base"
    yd = base / "2026"
    (yd / "Smith, John" / "EMS").mkdir(parents=True)
    return str(base)


def test_run_date_date_object_returns_results(tmp_path):
    base = _setup(tmp_path)
    rows, err = al.audit_jobs(
        ["John Smith"], base, year=2026,
        run_date=dt.date(2026, 6, 10), use_cache=False)
    assert err is None
    assert len(rows) == 1
    assert rows[0]["found"] is True


def test_run_date_datetime_object_returns_results(tmp_path):
    base = _setup(tmp_path)
    rows, err = al.audit_jobs(
        ["John Smith"], base, year=2026,
        run_date=dt.datetime(2026, 6, 10, 9, 30), use_cache=False)
    assert err is None
    assert len(rows) == 1


def test_date_object_matches_string_result(tmp_path):
    base = _setup(tmp_path)
    r_obj, _ = al.audit_jobs(["John Smith"], base, year=2026,
                             run_date=dt.date(2026, 6, 10), use_cache=False)
    r_str, _ = al.audit_jobs(["John Smith"], base, year=2026,
                             run_date="06-10-2026", use_cache=False)
    assert len(r_obj) == len(r_str) == 1
    assert r_obj[0]["found"] == r_str[0]["found"]
