"""The timestamped contact note posted to a Trello card.

    11:05 8/12/2026
    Called Insured to collect email.
    LVM

Built in Python so the preview the user approves and the string that
reaches Trello are the same object.
"""

import datetime as dt

import pytest

import call_note


def _at(y, mo, d, h, mi):
    return dt.datetime(y, mo, d, h, mi)


# ── the header line ─────────────────────────────────────────────────

def test_stamp_matches_the_handwritten_format():
    assert call_note.stamp(_at(2026, 8, 12, 11, 5)) == "11:05 8/12/2026"


def test_hour_and_month_are_not_zero_padded():
    # The existing comments on these cards are written this way; a log
    # that changes format halfway through is harder to scan.
    assert call_note.stamp(_at(2026, 8, 2, 9, 7)) == "9:07 8/2/2026"


def test_the_clock_is_24_hour():
    # A 12-hour clock with no am/pm can't tell an afternoon call from a
    # middle-of-the-night one, and these notes are evidence of WHEN
    # someone was contacted.
    assert call_note.stamp(_at(2026, 8, 12, 14, 30)) == "14:30 8/12/2026"
    assert call_note.stamp(_at(2026, 8, 12, 0, 5)) == "0:05 8/12/2026"
    assert call_note.stamp(_at(2026, 8, 12, 12, 0)) == "12:00 8/12/2026"


# ── the note itself ─────────────────────────────────────────────────

def test_the_example_from_the_office():
    r = call_note.build("Called Insured to collect email.\nLVM",
                        time_text="11:05", date_iso="2026-08-12")
    assert r["ok"]
    assert r["text"] == ("11:05 8/12/2026\n"
                         "Called Insured to collect email.\n"
                         "LVM")


def test_the_body_is_kept_as_typed():
    r = call_note.build("Spoke w/ Adj. — approving 2 more days of EQ",
                        time_text="9:00", date_iso="2026-08-12")
    assert r["text"].endswith("Spoke w/ Adj. — approving 2 more days of EQ")


def test_blank_runs_inside_the_body_collapse():
    r = call_note.build("Called.\n\n\n\nLVM",
                        time_text="9:00", date_iso="2026-08-12")
    assert r["text"] == "9:00 8/12/2026\nCalled.\n\nLVM"


def test_an_empty_note_is_refused():
    assert call_note.build("")["ok"] is False
    assert call_note.build("   \n  ")["ok"] is False


# ── logging a call after the fact ───────────────────────────────────

@pytest.mark.parametrize("typed,expect", [
    ("14:30", "14:30"),
    ("2:30 pm", "14:30"),      # typed 12-hour, stored unambiguous
    ("2:30pm", "14:30"),
    ("9:05 am", "9:05"),
    ("09:05", "9:05"),
])
def test_time_can_be_typed_either_way(typed, expect):
    r = call_note.build("x", time_text=typed, date_iso="2026-08-12")
    assert r["ok"], r
    assert r["text"].startswith(expect + " 8/12/2026")


@pytest.mark.parametrize("bad", ["25:00", "9:99", "half past", "9", "9:5x"])
def test_a_bad_time_is_reported_not_guessed(bad):
    r = call_note.build("x", time_text=bad)
    assert r["ok"] is False and "time" in r["error"]


def test_a_bad_date_is_reported_not_guessed():
    r = call_note.build("x", date_iso="12/08/2026")
    assert r["ok"] is False and "date" in r["error"]


def test_time_and_date_default_independently():
    # Only a date given — the time still comes from now, and vice versa.
    r = call_note.build("x", date_iso="2026-08-12")
    assert r["ok"] and r["text"].endswith(" 8/12/2026\nx")
    r2 = call_note.build("x", time_text="11:05")
    assert r2["ok"] and r2["text"].startswith("11:05 ")


def test_no_arguments_at_all_still_builds():
    r = call_note.build("Called, no answer")
    assert r["ok"] and r["text"].endswith("\nCalled, no answer")


# ── the quick phrases ───────────────────────────────────────────────

def test_lvm_is_offered():
    assert "LVM" in call_note.QUICK_PHRASES


def test_phrases_are_unique():
    p = call_note.QUICK_PHRASES
    assert len(p) == len(set(p))
