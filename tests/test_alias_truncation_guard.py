"""An alias that truncates a job's name must not claim its siblings.

`canon_key` drops everything after the first " - ", so the child folder
"Menifee School District - Bell Mountain - 8.14.26" shortens to
"menifee school district". That string was an ALIAS of one specific job —
"Menifee Union School District -Callie Kirkpatrick Elementary" — so Bell
Mountain resolved to Kirkpatrick's job. A different school, a different
loss, silently, and nothing on screen said so.

Seven Menifee jobs answer to those three tokens. The rule is not "never
trust a short alias": it is a useful shortcut while exactly ONE job
answers to it, and becomes a guess the moment a second one does. So the
check is against the job list as it stands, and the answer when it is
ambiguous is None — callers treat that as "not known yet" and ask, which
is what should have happened.
"""
import pytest

from ems_db_common import (alias_probe_token,
                           truncation_alias_is_ambiguous)


CALLIE = "menifee union school district -callie kirkpatrick elementary"
BELL = "menifee union school district (bell mountain ) - 8/14"


def test_a_truncation_with_several_matching_jobs_is_ambiguous():
    assert truncation_alias_is_ambiguous(
        "menifee school district", CALLIE, [CALLIE, BELL]) is True


def test_a_truncation_with_one_matching_job_is_fine():
    """The short form is a real shortcut until a sibling exists."""
    assert truncation_alias_is_ambiguous(
        "menifee school district", CALLIE, [CALLIE]) is False


def test_a_same_token_alias_is_never_suspect():
    """"white margaret" for "White, Margaret" is a spelling, not a
    truncation — it must keep working however many jobs exist."""
    assert truncation_alias_is_ambiguous(
        "white margaret", "white, margaret",
        ["white, margaret", "white, margarethe"]) is False


def test_a_superset_alias_is_not_a_truncation():
    """A LONGER alias narrows; it cannot capture siblings."""
    assert truncation_alias_is_ambiguous(
        "menifee union school district bell mountain 8 14",
        "menifee union school district", [CALLIE, BELL]) is False


def test_empty_inputs_are_not_ambiguous():
    assert truncation_alias_is_ambiguous("", CALLIE, [CALLIE, BELL]) is False
    assert truncation_alias_is_ambiguous("x", "", []) is False


def test_the_probe_token_is_the_longest():
    """Narrowest prefilter — "district" scans far less than "of"."""
    assert alias_probe_token("menifee school district") == "district"
    assert alias_probe_token("") == ""


# ── through the real SQLite backend ──────────────────────────────────
@pytest.fixture
def db():
    import ems_db_sqlite as s
    s.upsert_job(display_name=
                 "Menifee Union School District -Callie Kirkpatrick Elementary")
    s.upsert_job(display_name=
                 "Menifee Union School District (Bell Mountain ) - 8/14")
    s.add_alias(CALLIE, "Menifee School District", source="test", force=True)
    return s


def test_the_ambiguous_alias_returns_no_job(db):
    """The reported failure, end to end."""
    assert db.find_job_by_name(
        "Menifee School District - Bell Mountain - 8.14.26") is None


def test_each_job_still_resolves_by_its_own_name(db):
    assert db.find_job_by_name(
        "Menifee Union School District (Bell Mountain ) - 8/14"
    )["canon_key"] == BELL
    assert db.find_job_by_name(
        "Menifee Union School District -Callie Kirkpatrick Elementary"
    )["canon_key"] == CALLIE


def test_the_alias_still_works_while_it_is_unambiguous(db):
    """With only one Menifee job, the short form should resolve — the
    guard must not punish the common case."""
    import ems_db_sqlite as s
    s.merge_jobs(CALLIE, [BELL])
    assert s.find_job_by_name("Menifee School District")["canon_key"] == CALLIE


def test_an_ordinary_alias_is_untouched(db):
    db.upsert_job(display_name="Greer, Tesal")
    db.add_alias("greer, tesal", "Tesal Greer", source="test", force=True)
    assert db.find_job_by_name("Tesal Greer")["canon_key"] == "greer, tesal"


# ── both backends have to carry it ───────────────────────────────────
def test_the_live_backend_has_the_guard_too():
    """SQLite only answers when the shared database is unreachable, so
    fixing it there alone would have fixed nothing in production."""
    import inspect
    import ems_db_supabase
    src = inspect.getsource(ems_db_supabase.find_job_by_name)
    assert "truncation_alias_is_ambiguous" in src


def test_both_backends_share_one_implementation():
    """Two copies of a matching rule is how one of them keeps the bug."""
    import inspect
    import ems_db_sqlite
    import ems_db_supabase
    for mod in (ems_db_sqlite, ems_db_supabase):
        src = inspect.getsource(mod.find_job_by_name)
        assert "truncation_alias_is_ambiguous" in src
        assert "a_tok" not in src, "no hand-rolled second copy of the rule"
