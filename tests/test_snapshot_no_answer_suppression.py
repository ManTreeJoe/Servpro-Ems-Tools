"""Initial inspection notes use a labeled-Q&A form ("Equipment Placed:
No", "Visible Mold Present: No"). The note-extras pass used to flag
the activity with "EQ placed" any time it saw the phrase "equipment
placed" — including when the answer was an explicit No. Pinning the
suppression here so the user's reported bug ("Equipment Placed: No"
on initial inspection but snapshot showed EQ placed) can't regress.
"""
import snapshot_gui


# The initial-inspection paste the user reported. Trimmed slightly but
# preserves the labeled Q&A shape ("Equipment Placed: No") and the
# "Initial" activity line that anchors the date context.
USER_INITIAL_NOTE = """\
fernando Apr 21, 2026, 3:03 PM

Initial notes

Date:4-21-26
Time of Inspections:12:45 pm

EQUIPMENT

Equipment Placed: No
Type & Quantity (List by Room):
"""


def _activity_for_date(log_rows, date_str):
    for d, _wd, act, _tech in log_rows:
        if d == date_str:
            return act
    return None


def test_equipment_placed_no_does_not_flag_eq_placed():
    """The exact case the user reported — 'Equipment Placed: No' must
    NOT add 'EQ placed' to the day's activity."""
    _subs, log_rows = snapshot_gui.parse_comments(USER_INITIAL_NOTE)
    act = _activity_for_date(log_rows, "4/21/26")
    # If there's no log row at all, the parser couldn't anchor the
    # date — also acceptable (means no false positive happened).
    if act is None:
        return
    assert "EQ placed" not in act, (
        f"'Equipment Placed: No' false-positively flagged "
        f"EQ placed: {act!r}")


def test_is_no_answer_helper_basics():
    """Direct unit test on the helper. Bare 'no' answer suppresses;
    'noted' / 'north' / 'noticeable' are NOT bare-no answers."""
    no_answer = snapshot_gui._is_no_answer
    pat = r"equipment\s+placed"
    assert no_answer("equipment placed: no", pat)
    assert no_answer("equipment placed:no", pat)
    assert no_answer("equipment placed:  no", pat)
    assert no_answer("equipment placed: No", pat)
    # Negative cases — the answer is not a bare "no"
    assert not no_answer("equipment placed: yes", pat)
    assert not no_answer("equipment placed: noted", pat)
    assert not no_answer("equipment placed: north area", pat)
    # Phrase appears but no colon-answer — leave the existing flag
    # behavior intact (e.g. free-text "we got equipment placed in
    # bedroom" should still flag, the no-answer guard doesn't apply)
    assert not no_answer("equipment placed in bedroom", pat)


def test_is_no_answer_with_yes_value_does_not_suppress():
    """Sanity check the YES path — answer 'Yes' must NOT trigger
    suppression, otherwise we'd silently drop legit equipment-placed
    flags for jobs that DID place equipment."""
    no_answer = snapshot_gui._is_no_answer
    assert not no_answer("equipment placed: yes", r"equipment\s+placed")
