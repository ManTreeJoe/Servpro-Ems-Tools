"""Self-pay jobs need two forms an insurance job doesn't.

The customer is contracting directly, so it's a home-improvement contract
under California law: the contract itself plus the 3-Day Right to Cancel
notice.

The mirror of the commercial flag, and deliberately NOT symmetric —
commercial REMOVES the four insurance forms, self-pay ADDS two. Adding a
requirement must never auto-resolve anything: there is nothing to
forgive, the forms are simply now due.
"""
import os

import pytest

import audit_logic as al


@pytest.mark.parametrize("name", [
    "Home Improvement Contract.pdf",
    "home improvement contract signed.pdf",
    "HIC.pdf",
    "3 Day Right to Cancel.pdf",
    "Three Day Right To Cancel.pdf",
    "Right to Cancel.pdf",
    "RTC.pdf",
])
def test_the_self_pay_forms_are_recognised(name):
    assert al.is_self_pay_form(name) is True


@pytest.mark.parametrize("name", [
    "ATP.pdf", "Customer Info Form.pdf", "Dry Report.pdf", "Scope.pdf",
    "architect drawing.pdf",   # contains "hic" — word boundaries matter
    "",
])
def test_other_files_are_not(name):
    assert al.is_self_pay_form(name) is False


def _ems(tmp_path, files):
    d = tmp_path / "EMS"
    (d / "DOCS").mkdir(parents=True)
    for n in files:
        (d / "DOCS" / n).write_bytes(b"x")
    return str(d)


def test_both_missing(tmp_path):
    got = al.self_pay_missing(_ems(tmp_path, ["ATP.pdf"]))
    assert got == ["Home Improvement Contract", "3 Day Right to Cancel"]


def test_one_present_one_missing(tmp_path):
    got = al.self_pay_missing(_ems(tmp_path, ["Home Improvement Contract.pdf"]))
    assert got == ["3 Day Right to Cancel"]


def test_both_present(tmp_path):
    got = al.self_pay_missing(_ems(tmp_path, ["HIC.pdf", "RTC.pdf"]))
    assert got == []


def test_forms_loose_in_ems_count_too(tmp_path):
    """Some jobs keep them in DOCS, some at the EMS root."""
    d = tmp_path / "EMS"
    d.mkdir()
    (d / "Home Improvement Contract.pdf").write_bytes(b"x")
    (d / "3 Day Right to Cancel.pdf").write_bytes(b"x")
    assert al.self_pay_missing(str(d)) == []


def test_a_missing_folder_is_not_a_finding(tmp_path):
    """Unknown is not the same as incomplete — the same rule the contents
    check follows."""
    assert al.self_pay_missing(str(tmp_path / "nope")) == []
    assert al.self_pay_missing("") == []


# ── the flag ───────────────────────────────────────────────────────────

def test_the_flag_round_trips(tmp_path, monkeypatch):
    import persistence
    monkeypatch.setattr(persistence, "_STATE_PATH",
                        str(tmp_path / "state.json"), raising=False)
    monkeypatch.setattr(persistence, "data_path",
                        lambda *a, **k: str(tmp_path / "state.json"),
                        raising=False)
    store = {}
    monkeypatch.setattr(persistence, "_load", lambda: store)
    monkeypatch.setattr(persistence, "_save", lambda st: None)

    persistence.set_self_pay("Abbott, Darlene", True)
    assert persistence.is_self_pay("Abbott, Darlene") is True
    persistence.set_self_pay("Abbott, Darlene", False)
    assert persistence.is_self_pay("Abbott, Darlene") is False


def test_setting_the_flag_resolves_nothing():
    """Commercial auto-resolves the forms it drops. Self-pay must not —
    it is adding a requirement, and auto-resolving a form that is now due
    would hide it the moment it was asked for."""
    import inspect
    from audit_web import Api
    src = inspect.getsource(Api.set_self_pay)
    assert "set_resolved" not in src


# ── the chip ───────────────────────────────────────────────────────────

def _detail_js():
    import io as _io
    return _io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "web_shared", "audit_detail.js"),
        encoding="utf-8").read()


def test_job_type_is_managed_in_job_workspace_not_duplicate_top_chips():
    src = _detail_js()
    assert "selfpay-chip" not in src
    assert "commercial-chip" not in src
    assert 'data-crm-field="job_type"' in src
    assert "jobTypeLabel" in src
    assert "types.find" in src
# Job type remains one field; stage-specific requirements come from it.
