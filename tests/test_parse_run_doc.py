"""Tests for run_audit_gui.parse_run_doc — the run-doc parser is the
single source of truth for converting the daily run .docx into job rows.
Bugs here ripple through both Run Audit and Daily Photo Folders."""
import os
from datetime import datetime

import pytest
from docx import Document

from run_audit_gui import parse_run_doc


def _build_doc(tmp_path, paragraphs, name="run.docx"):
    """Write a .docx with the given paragraph texts and return its path."""
    p = tmp_path / name
    doc = Document()
    for text in paragraphs:
        doc.add_paragraph(text)
    doc.save(str(p))
    return str(p)


def test_run_date_parsed_from_date_line(tmp_path):
    path = _build_doc(tmp_path, [
        "Date: 4/29/26",
        "Work to be performed",
        "Cesar: 123 Main St (water) Cesar",
    ])
    jobs, run_date = parse_run_doc(path)
    assert run_date == "04-29-2026"
    assert any(j["client"] == "Cesar" for j in jobs)


def test_run_date_falls_back_to_yesterday_when_missing(tmp_path):
    path = _build_doc(tmp_path, [
        "Work to be performed",
        "Joe: 555 Oak Ave (mold) Cesar",
    ])
    jobs, run_date = parse_run_doc(path)
    assert run_date  # non-empty
    # Should match MM-DD-YYYY pattern
    datetime.strptime(run_date, "%m-%d-%Y")


def test_no_colon_falls_back_to_address(tmp_path):
    """The Celia Aldana case — line has no colon between client and address."""
    path = _build_doc(tmp_path, [
        "Date: 4/29/26",
        "Work to be performed",
        "Celia Aldana 39613 Oak Cliff Dr, Temecula CA 92591/Cesar",
    ])
    jobs, _ = parse_run_doc(path)
    assert len(jobs) == 1
    assert jobs[0]["client"] == "Celia Aldana"


def test_multi_claim_lines_stay_distinct(tmp_path):
    """Two run-doc lines for the same property, each tagged with a claim
    parenthetical, must NOT merge into one row — they're separate claims
    (separate Trello cards). The claim text is captured in `claim_hint`
    and stripped from the bare `client` used for folder matching."""
    path = _build_doc(tmp_path, [
        "Date: 6/10/26",
        "Work to be performed",
        "Sayra Mansolino (1s claim): 5671 Northwood Dr. Riverside 92509 "
        "(Mold After) ME",
        "Sayra Mansolino (2nd claim Kitchen): 5671 Northwood Dr. Riverside "
        "92509 (Mold After/Demo Thur 6/11) ME",
    ])
    jobs, _ = parse_run_doc(path)
    mans = [j for j in jobs if j["client"] == "Sayra Mansolino"]
    assert len(mans) == 2                       # not collapsed into one
    hints = {j.get("claim_hint") for j in mans}
    assert hints == {"1s claim", "2nd claim Kitchen"}


def test_duplicate_claim_lines_still_merge(tmp_path):
    """Same claim mentioned twice (e.g. Work + Monitor reminder) still
    collapses — the merge key is the claim NUMBER, not the raw text."""
    path = _build_doc(tmp_path, [
        "Date: 6/10/26",
        "Work to be performed",
        "Sayra Mansolino (1st claim): 5671 Northwood Dr (Mold After) ME",
        "Sayra Mansolino (1s claim): 5671 Northwood Dr (Mold After) ME",
    ])
    jobs, _ = parse_run_doc(path)
    mans = [j for j in jobs if j["client"] == "Sayra Mansolino"]
    assert len(mans) == 1


def test_warehouse_lines_skipped(tmp_path):
    path = _build_doc(tmp_path, [
        "Date: 4/29/26",
        "Work to be performed",
        "Joe: 1 St (mold) Cesar",
        "Warehouse cleanup today",
    ])
    jobs, _ = parse_run_doc(path)
    assert len(jobs) == 1
    assert jobs[0]["client"] == "Joe"


def test_section_switching(tmp_path):
    """Lines under 'Monitor' get section='monitor' so the audit can
    suppress photo expectations for those rows."""
    path = _build_doc(tmp_path, [
        "Date: 4/29/26",
        "Work to be performed",
        "Joe: 1 St (water) Cesar",
        "Monitor",
        "Mary: 2 Ave (mold) Vince",
    ])
    jobs, _ = parse_run_doc(path)
    sections = {j["client"]: j["section"] for j in jobs}
    assert sections["Joe"] == "work"
    assert sections["Mary"] == "monitor"


def test_stop_headers_clear_section(tmp_path):
    """'Upcoming' / 'Pending' / 'On hold' / 'Marketing' headers end the
    current section so jobs listed beneath them don't get included."""
    path = _build_doc(tmp_path, [
        "Date: 4/29/26",
        "Work to be performed",
        "Joe: 1 St (water) Cesar",
        "Upcoming",
        "Mary: 2 Ave (mold) Vince",  # should be dropped
    ])
    jobs, _ = parse_run_doc(path)
    clients = [j["client"] for j in jobs]
    assert "Joe" in clients
    assert "Mary" not in clients


def test_techs_resolved_from_abbreviations(tmp_path):
    """'FB' → 'Fernando' via ABBREV map; bare names stay title-cased."""
    path = _build_doc(tmp_path, [
        "Date: 4/29/26",
        "Work to be performed",
        "Joe: 1 St (water) FB Cesar",
    ])
    jobs, _ = parse_run_doc(path)
    assert "Fernando" in jobs[0]["techs"]
    assert "Cesar" in jobs[0]["techs"]


def test_unit_extracted(tmp_path):
    path = _build_doc(tmp_path, [
        "Date: 4/29/26",
        "Work to be performed",
        "Anibal: Keystone Apt #168 (water) Cesar",
    ])
    jobs, _ = parse_run_doc(path)
    assert jobs[0]["unit"] == "168"


def test_unit_keyword_with_word_boundary_only(tmp_path):
    """`Suite` inside `Suites` (and `Apt` inside `Apartment`,
    `Unit` inside `Unitarian`) must NOT be matched as the unit
    keyword. Reported in the wild as 'Everhome Suites' parsing
    with unit='s' — the trailing 's' got captured as the unit
    number, which silently broke SP matching for that job."""
    path = _build_doc(tmp_path, [
        "Date: 5/04/26",
        "Work to be performed",
        "Everhome Suites: 27165 Madison Ave Temecula 92590/951-816-1473",
    ])
    jobs, _ = parse_run_doc(path)
    assert len(jobs) == 1
    assert jobs[0]["client"] == "Everhome Suites"
    assert jobs[0]["unit"] is None, (
        f"unit should not be extracted from 'Suites': {jobs[0]['unit']!r}")


def test_unit_still_extracted_with_keyword_and_space(tmp_path):
    """Sanity: word-boundary fix doesn't break legit unit detection."""
    cases = [
        ("Smith: Property Unit 168 / 951-555-0001", "168"),
        ("Smith: Property Suite 5 / 951-555-0002", "5"),
        ("Smith: Property Apt 3B / 951-555-0003", "3B"),
        ("Smith: Property Apt. 4 / 951-555-0004", "4"),
        ("Smith: Property #168 / 951-555-0005", "168"),
    ]
    for line, expected in cases:
        path = _build_doc(tmp_path, [
            "Date: 5/04/26",
            "Work to be performed",
            line,
        ], name=f"unit_{expected}.docx")
        jobs, _ = parse_run_doc(path)
        assert len(jobs) == 1, f"line {line!r} should produce one job"
        assert jobs[0]["unit"] == expected, (
            f"line {line!r} expected unit={expected!r}, "
            f"got {jobs[0]['unit']!r}")


def test_unit_hash_does_not_match_long_claim_numbers(tmp_path):
    """Bare `#` followed by 6+ digits is a claim number, not a unit.
    Without the length cap, a line like `Smith: 1 St claim #1682405
    (water) Cesar` would parse with unit='1682405' and SP matching
    would silently fall back to a name-only search."""
    path = _build_doc(tmp_path, [
        "Date: 5/04/26",
        "Work to be performed",
        "Smith: 1 St claim #1682405 (water) Cesar",
    ])
    jobs, _ = parse_run_doc(path)
    assert len(jobs) == 1
    assert jobs[0]["unit"] is None, (
        f"#1682405 must not be parsed as a unit (got "
        f"{jobs[0]['unit']!r}); long values are claim numbers")


def test_unit_hash_requires_word_boundary(tmp_path):
    """`#` glued to a preceding word character (`abc#123`) is never a
    unit number — it's almost always a hex/anchor/path artifact. Only
    `#` after whitespace (or at start of the address) should match."""
    path = _build_doc(tmp_path, [
        "Date: 5/04/26",
        "Work to be performed",
        "Smith: 1 St color#123 (water) Cesar",
    ])
    jobs, _ = parse_run_doc(path)
    assert len(jobs) == 1
    assert jobs[0]["unit"] is None, (
        f"`color#123` must not match as unit (got "
        f"{jobs[0]['unit']!r})")


def test_new_loss_flag(tmp_path):
    path = _build_doc(tmp_path, [
        "Date: 4/29/26",
        "Work to be performed",
        "Joe: 1 St (NEW LOSS) Cesar",
    ])
    jobs, _ = parse_run_doc(path)
    assert jobs[0]["new_loss"] is True


def test_raw_field_includes_full_line(tmp_path):
    """daily_photos_gui passes job['raw'] to detect_activity, so the
    parser must preserve the original line text."""
    path = _build_doc(tmp_path, [
        "Date: 4/29/26",
        "Work to be performed",
        "Joe: 1 St (Demo) Cesar",
    ])
    jobs, _ = parse_run_doc(path)
    assert "Demo" in jobs[0]["raw"]


def test_numbered_list_prefix_stripped(tmp_path):
    """Run docs sometimes use numbered lists ('1. Joe: ...'). The prefix
    shouldn't end up in the client name."""
    path = _build_doc(tmp_path, [
        "Date: 4/29/26",
        "Work to be performed",
        "1. Joe: 1 St (water) Cesar",
    ])
    jobs, _ = parse_run_doc(path)
    assert jobs[0]["client"] == "Joe"


# ── Duplicate merging ───────────────────────────────────────────────────────
# Run docs sometimes list the same job twice (AM/PM crews, or repeated
# under Work + Monitor). The audit shouldn't surface duplicate rows.

def test_duplicate_lines_merged_to_one_job(tmp_path):
    path = _build_doc(tmp_path, [
        "Date: 4/29/26",
        "Work to be performed",
        "Joe Smith: 1 St (Demo) Cesar",
        "Joe Smith: 1 St (Demo) Vince",
    ])
    jobs, _ = parse_run_doc(path)
    assert len(jobs) == 1
    # techs from both lines unioned, in first-seen order
    assert jobs[0]["techs"] == ["Cesar", "Vince"]


def test_duplicate_merge_unions_techs_no_dup(tmp_path):
    """If a tech appears on both lines, union shouldn't duplicate them."""
    path = _build_doc(tmp_path, [
        "Date: 4/29/26",
        "Work to be performed",
        "Joe: 1 St (Demo) Cesar Vince",
        "Joe: 1 St (Demo) Cesar",
    ])
    jobs, _ = parse_run_doc(path)
    assert len(jobs) == 1
    assert jobs[0]["techs"] == ["Cesar", "Vince"]


def test_duplicate_merge_prefers_work_over_monitor(tmp_path):
    """Same client in Work AND Monitor → audit as a Work job (so photo
    expectations fire correctly)."""
    path = _build_doc(tmp_path, [
        "Date: 4/29/26",
        "Work to be performed",
        "Joe: 1 St (Demo) Cesar",
        "Monitor",
        "Joe: 1 St (mon) Vince",
    ])
    jobs, _ = parse_run_doc(path)
    assert len(jobs) == 1
    assert jobs[0]["section"] == "work"


def test_duplicate_merge_concatenates_raw_lines(tmp_path):
    """The merged job's `raw` field should contain BOTH source lines so
    activity detection sees keywords from each."""
    path = _build_doc(tmp_path, [
        "Date: 4/29/26",
        "Work to be performed",
        "Joe: 1 St (Demo) Cesar",
        "Joe: 1 St (Mold Prep) Vince",
    ])
    jobs, _ = parse_run_doc(path)
    assert len(jobs) == 1
    raw = jobs[0]["raw"]
    assert "Demo" in raw
    assert "Mold Prep" in raw


def test_duplicate_merge_new_loss_any_wins(tmp_path):
    """If ANY line tags new-loss, the merged job carries the flag."""
    path = _build_doc(tmp_path, [
        "Date: 4/29/26",
        "Work to be performed",
        "Joe: 1 St (Demo) Cesar",
        "Joe: 1 St (NEW LOSS) Vince",
    ])
    jobs, _ = parse_run_doc(path)
    assert len(jobs) == 1
    assert jobs[0]["new_loss"] is True


def test_duplicate_merge_treats_unit_as_part_of_key(tmp_path):
    """Same client at different units = legitimately separate jobs.
    Don't merge them — each unit is its own visit."""
    path = _build_doc(tmp_path, [
        "Date: 4/29/26",
        "Work to be performed",
        "Anibal: Keystone Apt #168 (Demo) Cesar",
        "Anibal: Keystone Apt #220 (Demo) Vince",
    ])
    jobs, _ = parse_run_doc(path)
    assert len(jobs) == 2
    units = sorted(j["unit"] for j in jobs)
    assert units == ["168", "220"]


def test_duplicate_merge_normalizes_whitespace_and_case(tmp_path):
    """'Joe Smith' and 'joe  smith' (extra space, different case) refer
    to the same client and should merge."""
    path = _build_doc(tmp_path, [
        "Date: 4/29/26",
        "Work to be performed",
        "Joe Smith: 1 St (Demo) Cesar",
        "joe  smith: 1 St (Demo) Vince",
    ])
    jobs, _ = parse_run_doc(path)
    assert len(jobs) == 1


def test_distinct_clients_not_merged(tmp_path):
    """Sanity: two genuinely different clients stay separate."""
    path = _build_doc(tmp_path, [
        "Date: 4/29/26",
        "Work to be performed",
        "Joe: 1 St (Demo) Cesar",
        "Mary: 2 Ave (Demo) Vince",
    ])
    jobs, _ = parse_run_doc(path)
    assert len(jobs) == 2
