"""Creating the CompanyCam project AT INTAKE instead of fuzzy-matching
it later.

The network is mocked throughout — nothing here talks to CompanyCam.
What these pin is the request SHAPE (top-level fields, not wrapped in a
"project" key, per docs.companycam.com/reference/createproject) and the
refuse-to-duplicate rules.
"""
import urllib.request

import pytest

import companycam_api as cc
import new_loss_intake as nli


# ── address splitting ──────────────────────────────────────────────────
def test_full_address_splits():
    a = cc.split_address("1234 Elm St, Menifee, CA 92584")
    assert a["street_address_1"] == "1234 Elm St"
    assert a["city"] == "Menifee"
    assert a["state"] == "CA"
    assert a["postal_code"] == "92584"


def test_street_and_city_only():
    a = cc.split_address("1234 Elm St, Menifee")
    assert a["street_address_1"] == "1234 Elm St"
    assert a["city"] == "Menifee"
    assert not a["state"] and not a["postal_code"]


def test_unsplittable_stays_in_street():
    """A wrong city breaks same-name tie-breaking in find_project, so
    anything ambiguous stays put rather than being guessed apart."""
    a = cc.split_address("Behind the Chevron on Newport")
    assert a["street_address_1"] == "Behind the Chevron on Newport"
    assert not a["city"]


def test_suite_number_kept_with_street():
    a = cc.split_address("400 S Main St, Suite 210, Corona, CA 92880")
    assert a["street_address_1"] == "400 S Main St, Suite 210"
    assert a["city"] == "Corona"
    assert a["state"] == "CA"


def test_blank_address():
    assert cc.split_address("")["street_address_1"] == ""
    assert cc.split_address(None)["city"] == ""


# ── request shape ──────────────────────────────────────────────────────
@pytest.fixture
def sent(monkeypatch):
    """Capture the body `create_project` would POST."""
    box = {}

    def _fake(path, *, params=None, method="GET", data=None, **kw):
        box.update(path=path, method=method, data=data)
        return {"id": "111222333", "name": (data or {}).get("name"),
                "address": {"street_address_1": "1234 Elm St",
                            "city": "Menifee", "state": "CA",
                            "postal_code": "92584"},
                "status": "active"}
    monkeypatch.setattr(cc, "_call", _fake)
    return box


def test_body_is_not_wrapped_in_a_project_key(sent):
    """CompanyCam takes the fields at the TOP level. Wrapping them in
    {"project": {...}} silently creates a nameless project."""
    r = cc.create_project("Smith, David", address="1234 Elm St, Menifee, CA 92584")
    assert r["ok"]
    assert sent["method"] == "POST" and sent["path"] == "/projects"
    assert "project" not in sent["data"]
    assert sent["data"]["name"] == "Smith, David"
    assert sent["data"]["address"]["city"] == "Menifee"


def test_blank_address_sends_no_address_block(sent):
    cc.create_project("Smith, David")
    assert "address" not in sent["data"]


def test_contact_omitted_when_there_is_no_name(sent):
    """primary_contact.name is required whenever the block is present —
    sending an email-only contact is a 422."""
    cc.create_project("Smith, David", contact_email="a@b.com")
    assert "primary_contact" not in sent["data"]


def test_contact_included_with_a_name(sent):
    cc.create_project("Smith, David", contact_name="David Smith",
                      contact_phone="951-555-0000")
    pc = sent["data"]["primary_contact"]
    assert pc["name"] == "David Smith"
    assert pc["phone_number"] == "951-555-0000"


def test_explicit_parts_beat_the_one_liner(sent):
    cc.create_project("X", address="1 A St, Menifee, CA 92584", city="Corona")
    assert sent["data"]["address"]["city"] == "Corona"


def test_name_is_required():
    assert cc.create_project("   ")["ok"] is False


# ── write-scope failure is reported, not raised ────────────────────────
def _http_error(code):
    def _raise(*a, **k):
        raise urllib.request.HTTPError("u", code, "no", {}, None)
    return _raise


def test_read_only_token_reports_scope_false(monkeypatch):
    monkeypatch.setattr(cc, "_call", _http_error(403))
    r = cc.create_project("Smith, David")
    assert r["ok"] is False
    assert r["scope"] is False
    assert "read-only" in r["error"]


def test_other_http_errors_are_surfaced(monkeypatch):
    monkeypatch.setattr(cc, "_call", _http_error(422))
    r = cc.create_project("Smith, David")
    assert r["ok"] is False
    assert r["code"] == 422
    assert "scope" not in r


def test_missing_id_in_response_is_an_error(monkeypatch):
    monkeypatch.setattr(cc, "_call", lambda *a, **k: {"name": "X"})
    assert cc.create_project("X")["ok"] is False


# ── intake wiring: never create without being told to ──────────────────
@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(cc, "is_configured", lambda: True)
    monkeypatch.setattr(nli, "_pin_companycam", lambda *a, **k: True)
    # Start from "this job isn't in the graph yet". Without this the
    # result depends on what earlier tests left in the session DB — the
    # already-pinned short-circuit below is tested on purpose instead.
    import ems_db
    monkeypatch.setattr(ems_db, "find_job_by_name", lambda *a, **k: None)


def test_dry_run_creates_nothing(configured, monkeypatch):
    monkeypatch.setattr(cc, "find_project",
                        lambda *a, **k: {"ok": True, "match": None,
                                         "candidates": []})
    monkeypatch.setattr(cc, "create_project", lambda *a, **k: pytest.fail(
        "created a real project without confirm_create"))
    r = nli.create_companycam_project(
        {"insured_name": "David Smith", "address": "1 A St, Menifee, CA 92584"})
    assert r["ok"] and r["created"] is False and r["would_create"] is True
    assert r["name"] == "David Smith"
    assert r["address"]["city"] == "Menifee"


def test_existing_project_is_pinned_not_duplicated(configured, monkeypatch):
    monkeypatch.setattr(cc, "find_project", lambda *a, **k: {
        "ok": True, "match": {"id": "999", "name": "David Smith"}})
    monkeypatch.setattr(cc, "create_project", lambda *a, **k: pytest.fail(
        "duplicated an existing CompanyCam project"))
    r = nli.create_companycam_project({"insured_name": "David Smith"},
                                      confirm_create=True)
    assert r["ok"] and r["created"] is False
    assert r["project"]["id"] == "999"
    assert r["pinned"] is True


def test_confirmed_create_pins_the_new_id(configured, monkeypatch):
    monkeypatch.setattr(cc, "find_project",
                        lambda *a, **k: {"ok": True, "match": None})
    monkeypatch.setattr(cc, "create_project", lambda *a, **k: {
        "ok": True, "project": {"id": "111222333", "name": "David Smith"}})
    r = nli.create_companycam_project(
        {"insured_name": "David Smith"}, confirm_create=True)
    assert r["created"] is True
    assert r["project"]["id"] == "111222333"
    assert r["pinned"] is True


def test_already_pinned_job_short_circuits(monkeypatch):
    """If the job already carries a companycam_project link we must not
    even reach the name search — that link is ground truth, and a name
    search is exactly the guessing this whole change removes."""
    import ems_db
    monkeypatch.setattr(cc, "is_configured", lambda: True)
    monkeypatch.setattr(ems_db, "find_job_by_name",
                        lambda *a, **k: {"canon_key": "smith, david"})
    monkeypatch.setattr(ems_db, "get_link", lambda *a, **k: "108614048")
    monkeypatch.setattr(cc, "find_project", lambda *a, **k: pytest.fail(
        "searched by name despite an existing pin"))
    r = nli.create_companycam_project({"insured_name": "David Smith"},
                                      confirm_create=True)
    assert r["ok"] and r["created"] is False and r["pinned"] is True
    assert r["project"]["id"] == "108614048"


def test_no_insured_name_is_an_error(configured):
    assert nli.create_companycam_project({})["ok"] is False


def test_unconfigured_token_is_reported(monkeypatch):
    monkeypatch.setattr(cc, "is_configured", lambda: False)
    r = nli.create_companycam_project({"insured_name": "X"},
                                      confirm_create=True)
    assert r["ok"] is False and "token" in r["error"]
