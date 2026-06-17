"""Unit tests for ems_db — schema, upsert, links, aliases, export/import."""
from __future__ import annotations

import json
import os
import sys

import pytest

# Make scripts/ importable when pytest runs from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ems_db


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Point ems_db at a per-test SQLite file. Each test starts clean —
    no cross-test contamination of the jobs table."""
    db_file = tmp_path / "test.db"
    ems_db.reset_db_path(str(db_file))
    yield
    # cleanup happens via tmp_path tear-down


# ── canon_key ────────────────────────────────────────────────────────────

def test_canon_key_lowercase_and_collapse_whitespace():
    assert ems_db.canon_key("Doe, John") == "doe, john"
    assert ems_db.canon_key("DOE,  JOHN  ") == "doe, john"


def test_canon_key_strips_carrier_suffix():
    # Persistence rule: drop everything after the first " - "
    assert ems_db.canon_key("Doe, John - State Farm") == "doe, john"


def test_canon_key_blank():
    assert ems_db.canon_key("") == ""
    assert ems_db.canon_key("   ") == ""
    assert ems_db.canon_key(None) == ""


# ── upsert_job ───────────────────────────────────────────────────────────

def test_upsert_job_inserts_new_row():
    key = ems_db.upsert_job(display_name="Doe, John - AAA",
                             claim_number="ABC123", carrier="AAA",
                             status="active")
    assert key == "doe, john"
    job = ems_db.find_job_by_name("Doe, John")
    assert job is not None
    assert job["display_name"] == "Doe, John - AAA"
    assert job["claim_number"] == "ABC123"
    assert job["status"] == "active"


def test_upsert_job_partial_update_preserves_existing_values():
    """Re-upserting with blanks shouldn't nuke fields the first call set."""
    ems_db.upsert_job(display_name="Doe, John", claim_number="ABC123",
                       carrier="AAA", loss_type="WTR")
    ems_db.upsert_job(display_name="Doe, John", status="completed")
    job = ems_db.find_job_by_name("Doe, John")
    assert job["claim_number"] == "ABC123"     # preserved
    assert job["loss_type"] == "WTR"           # preserved
    assert job["status"] == "completed"        # newly set


def test_upsert_job_display_name_overwrites_on_recasing():
    """Casing fixes (e.g. all-caps to title-case) should propagate."""
    ems_db.upsert_job(display_name="DOE, JOHN")
    ems_db.upsert_job(display_name="Doe, John")
    job = ems_db.find_job_by_name("Doe, John")
    assert job["display_name"] == "Doe, John"


def test_upsert_job_blank_name_raises():
    with pytest.raises(ValueError):
        ems_db.upsert_job(display_name="")


# ── aliases ──────────────────────────────────────────────────────────────

def test_alias_lookup_resolves_comma_swap():
    """Two adjacent panels should be able to find one job under
    either 'GUADALUPE PLOUSSARD' or 'Ploussard, Guadalupe'."""
    ems_db.upsert_job(display_name="Ploussard, Guadalupe - AAA")
    ems_db.add_alias("ploussard, guadalupe", "GUADALUPE PLOUSSARD",
                      source="email_subject")
    job = ems_db.find_job_by_name("GUADALUPE PLOUSSARD")
    assert job is not None
    assert job["display_name"] == "Ploussard, Guadalupe - AAA"


def test_alias_self_alias_is_no_op():
    """Adding an alias whose canon == the primary canon should not crash
    and shouldn't show up as a separate entry."""
    ems_db.upsert_job(display_name="Doe, John")
    ems_db.add_alias("doe, john", "DOE, JOHN")     # canonicalizes the same
    assert ems_db.get_aliases("doe, john") == []


def test_alias_idempotent():
    ems_db.upsert_job(display_name="Doe, John")
    ems_db.add_alias("doe, john", "John Doe")
    ems_db.add_alias("doe, john", "John Doe")
    assert ems_db.get_aliases("doe, john") == ["John Doe"]


# ── links ────────────────────────────────────────────────────────────────

def test_set_link_get_link_roundtrip():
    ems_db.upsert_job(display_name="Doe, John")
    ems_db.set_link("doe, john", "trello_card", "abc123")
    assert ems_db.get_link("doe, john", "trello_card") == "abc123"


def test_set_link_multi_value_per_type():
    """A job can have multiple Trello cards (multi-claim case)."""
    ems_db.upsert_job(display_name="Doe, John")
    ems_db.set_link("doe, john", "trello_card", "card_one")
    ems_db.set_link("doe, john", "trello_card", "card_two")
    links = ems_db.get_links("doe, john", "trello_card")
    assert sorted(l["link_value"] for l in links) == ["card_one", "card_two"]


def test_remove_link_specific_value():
    ems_db.upsert_job(display_name="Doe, John")
    ems_db.set_link("doe, john", "trello_card", "card_one")
    ems_db.set_link("doe, john", "trello_card", "card_two")
    ems_db.remove_link("doe, john", "trello_card", "card_one")
    remaining = [l["link_value"] for l in ems_db.get_links("doe, john", "trello_card")]
    assert remaining == ["card_two"]


def test_remove_link_all_of_type():
    """Blank link_value drops every link of that type."""
    ems_db.upsert_job(display_name="Doe, John")
    ems_db.set_link("doe, john", "trello_card", "card_one")
    ems_db.set_link("doe, john", "trello_card", "card_two")
    ems_db.remove_link("doe, john", "trello_card")
    assert ems_db.get_links("doe, john", "trello_card") == []


def test_get_link_returns_none_when_missing():
    ems_db.upsert_job(display_name="Doe, John")
    assert ems_db.get_link("doe, john", "trello_card") is None


# ── events ───────────────────────────────────────────────────────────────

def test_log_event_persists():
    ems_db.upsert_job(display_name="Doe, John")
    ems_db.log_event("doe, john", "on_run_doc",
                      payload={"date": "2026-05-14"})
    # No public read API yet; verify via the DB directly.
    with ems_db._connect() as c:
        rows = c.execute(
            "SELECT * FROM job_events WHERE canon_key=?",
            ("doe, john",)).fetchall()
    assert len(rows) == 1
    assert rows[0]["event_type"] == "on_run_doc"


# ── status queries ───────────────────────────────────────────────────────

def test_find_jobs_by_status():
    ems_db.upsert_job(display_name="One", status="new_loss")
    ems_db.upsert_job(display_name="Two", status="new_loss")
    ems_db.upsert_job(display_name="Three", status="active")
    nl = ems_db.find_jobs_by_status("new_loss")
    assert {j["display_name"] for j in nl} == {"One", "Two"}


# ── export / import roundtrip ────────────────────────────────────────────

def test_export_import_roundtrip(tmp_path):
    """Export → wipe → import should restore jobs, aliases, and
    allow-listed link types byte-for-byte."""
    ems_db.upsert_job(display_name="Ploussard, Guadalupe - AAA",
                       claim_number="017813029", carrier="AAA",
                       status="active")
    ems_db.add_alias("ploussard, guadalupe", "GUADALUPE PLOUSSARD",
                      source="email_subject")
    ems_db.set_link("ploussard, guadalupe", "trello_card",
                     "69f8efef5e320b8283a5b970")
    ems_db.set_link("ploussard, guadalupe", "od_folder",
                     r"X:\IE_Public\2026 Jobs\Ploussard, Guadalupe 2-19-26")
    # Machine-specific link type — should NOT export
    ems_db.set_link("ploussard, guadalupe", "sp_folder", "/sites/...")

    out_file = tmp_path / "export.json"
    summary = ems_db.export_db(str(out_file))
    assert summary["jobs"] == 1

    payload = json.loads(out_file.read_text(encoding="utf-8"))
    assert payload["schema_version"] == ems_db.SCHEMA_VERSION
    exported_job = payload["jobs"][0]
    assert exported_job["display_name"] == "Ploussard, Guadalupe - AAA"
    link_types = {l["type"] for l in exported_job["links"]}
    assert link_types == {"trello_card", "od_folder"}    # sp_folder excluded

    # Wipe + reimport
    with ems_db._connect() as c:
        c.execute("DELETE FROM jobs")
        c.commit()
    assert ems_db.find_job_by_name("Ploussard, Guadalupe") is None

    res = ems_db.import_db(str(out_file), mode="upsert")
    assert res["jobs_added"] == 1
    assert ems_db.find_job_by_name("GUADALUPE PLOUSSARD") is not None
    assert ems_db.get_link("ploussard, guadalupe", "trello_card") == \
        "69f8efef5e320b8283a5b970"


def test_import_upsert_preserves_local_only_jobs(tmp_path):
    """upsert mode shouldn't drop jobs that aren't in the import file."""
    ems_db.upsert_job(display_name="Local Only", status="active")
    out_file = tmp_path / "export.json"
    ems_db.export_db(str(out_file))            # snapshot with Local Only
    ems_db.upsert_job(display_name="New After Snapshot", status="active")
    ems_db.import_db(str(out_file), mode="upsert")
    assert ems_db.find_job_by_name("Local Only") is not None
    assert ems_db.find_job_by_name("New After Snapshot") is not None


def test_import_replace_wipes_locals(tmp_path):
    """replace mode should drop pre-existing local jobs."""
    ems_db.upsert_job(display_name="In Snapshot", status="active")
    out_file = tmp_path / "export.json"
    ems_db.export_db(str(out_file))
    ems_db.upsert_job(display_name="Will Be Wiped", status="active")
    ems_db.import_db(str(out_file), mode="replace")
    assert ems_db.find_job_by_name("In Snapshot") is not None
    assert ems_db.find_job_by_name("Will Be Wiped") is None


def test_import_invalid_mode_raises(tmp_path):
    out_file = tmp_path / "export.json"
    ems_db.export_db(str(out_file))
    with pytest.raises(ValueError):
        ems_db.import_db(str(out_file), mode="bogus")


# ── Multi-unit detection + grouping ──────────────────────────────────────

def test_detect_property_and_unit_paren_form():
    prop, unit = ems_db.detect_property_and_unit(
        "Avila Apartments (527) 2/19/26")
    assert prop == "Avila Apartments"
    assert unit == "527"


def test_detect_property_and_unit_inline_unit():
    prop, unit = ems_db.detect_property_and_unit(
        "Avila Apartments Unit 1027 - Self Pay 2510-517185WTR")
    assert prop == "Avila Apartments"
    assert unit == "1027"


def test_detect_property_and_unit_dash_unit():
    prop, unit = ems_db.detect_property_and_unit(
        "Avila Apartments- Unit 226")
    assert prop == "Avila Apartments"
    assert unit == "226"


def test_detect_property_and_unit_bare_number():
    """Trailing 3-4 digit number after the property name."""
    prop, unit = ems_db.detect_property_and_unit(
        "Avila Apartments 1413- 05/09/26")
    assert prop == "Avila Apartments"
    assert unit == "1413"


def test_detect_property_and_unit_hash_form():
    prop, unit = ems_db.detect_property_and_unit("Avila Apartments #216")
    assert prop == "Avila Apartments"
    assert unit == "216"


def test_detect_property_and_unit_no_match():
    """A typical single-family job name shouldn't match."""
    prop, unit = ems_db.detect_property_and_unit("Ploussard, Guadalupe - AAA")
    assert prop is None
    assert unit is None


def test_detect_rejects_year_tagged_person_name():
    """'Santiago, Ernie (2025)- State Farm' has '(2025)' as a YEAR
    tag, not a unit number. Must NOT be detected as multi-unit —
    comma in prop signals a person name."""
    prop, unit = ems_db.detect_property_and_unit(
        "Santiago, Ernie (2025)- State Farm - $19,346.35")
    assert prop is None
    assert unit is None


def test_detect_rejects_year_tagged_uppercase_name():
    prop, unit = ems_db.detect_property_and_unit(
        "HANKIEWICZ, MARKUS (2024) - State Farm - $3,767.77")
    assert prop is None
    assert unit is None


def test_detect_rejects_paren_year_even_without_comma():
    """Even without a comma, '(2025)' / '(2030)' are year-shaped
    enough on the paren-form path that we should bail to avoid
    false-positives on commercial cards tagged with the loss year."""
    prop, unit = ems_db.detect_property_and_unit(
        "Acme Corp (2025) - Mercury")
    assert prop is None
    assert unit is None


def test_detect_allows_explicit_unit_2025():
    """If the form is unambiguous ('Apt 2025'), unit 2025 IS valid
    — only the paren-only / bare-number paths reject year-shaped
    numbers."""
    prop, unit = ems_db.detect_property_and_unit("Some Property Apt 2025")
    assert prop == "Some Property"
    assert unit == "2025"


def test_upsert_job_auto_sets_parent_canon():
    """Inserting a multi-unit job should auto-fill parent_canon + unit_number."""
    ems_db.upsert_job(display_name="Avila Apartments 1416")
    job = ems_db.find_job_by_name("Avila Apartments 1416")
    assert job["parent_canon"] == "avila apartments"
    assert job["unit_number"] == "1416"


def test_upsert_job_no_parent_for_single_family():
    ems_db.upsert_job(display_name="Doe, John - State Farm")
    job = ems_db.find_job_by_name("Doe, John")
    assert job["parent_canon"] is None
    assert job["unit_number"] is None


def test_find_units_of_aggregates_siblings():
    """Sibling units of the same property should be queryable as one set
    regardless of whether an umbrella row exists."""
    ems_db.upsert_job(display_name="Avila Apartments 527")
    ems_db.upsert_job(display_name="Avila Apartments 1416")
    ems_db.upsert_job(display_name="Avila Apartments 2216")
    units = ems_db.find_units_of("avila apartments")
    assert len(units) == 3
    # Sorted by numeric unit_number
    assert [u["unit_number"] for u in units] == ["527", "1416", "2216"]


def test_find_property_of_returns_umbrella_when_present():
    ems_db.upsert_job(display_name="Avila Apartments")     # umbrella row
    ems_db.upsert_job(display_name="Avila Apartments 1416")
    parent = ems_db.find_property_of("avila apartments 1416")
    assert parent is not None
    assert parent["canon_key"] == "avila apartments"


def test_find_property_of_returns_none_when_umbrella_missing():
    """Sibling-only grouping: the umbrella row is optional."""
    ems_db.upsert_job(display_name="Avila Apartments 1416")
    parent = ems_db.find_property_of("avila apartments 1416")
    assert parent is None     # parent_canon set but no umbrella row


def test_group_by_property_rolls_up_siblings():
    ems_db.upsert_job(display_name="Avila Apartments 527")
    ems_db.upsert_job(display_name="Avila Apartments 1416")
    ems_db.upsert_job(display_name="Doe, John")
    grouped = ems_db.group_by_property([
        "avila apartments 527",
        "avila apartments 1416",
        "doe, john",
    ])
    assert sorted(grouped["avila apartments"]) == [
        "avila apartments 1416", "avila apartments 527"]
    # Single-family job groups under its own canon_key
    assert grouped["doe, john"] == ["doe, john"]


def test_upsert_partial_update_preserves_parent_canon():
    """A re-upsert with a non-multi-unit name shouldn't blow away a
    previously-detected parent. (Edge case: someone renames a card to
    drop the unit number temporarily.)"""
    ems_db.upsert_job(display_name="Avila Apartments 1416")
    # Re-upsert with the same display name — partial update preserves
    # parent_canon even though detect would re-set it anyway.
    ems_db.upsert_job(display_name="Avila Apartments 1416", status="active")
    job = ems_db.find_job_by_name("Avila Apartments 1416")
    assert job["parent_canon"] == "avila apartments"
    assert job["unit_number"] == "1416"
