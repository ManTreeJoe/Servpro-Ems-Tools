"""Type-ahead ranking.

What matters here is ORDER, not just membership: the search box shows the
top few, so a correct match ranked fourth is a wrong answer. Every case
below came from real name shapes in the live index — surname-first filing,
aliases, typos, and one genuinely bad alias.
"""
import pytest

import job_search


def _index(monkeypatch, jobs, aliases=()):
    """Install a fake job index. No DB, no disk."""
    entries = []
    for name in jobs:
        entries.append({"canon_key": name.lower(), "display_name": name,
                        "last_seen_at": "2026-07-01T00:00:00"})

    class FakeDB:
        @staticmethod
        def iter_jobs():
            return entries

        @staticmethod
        def all_aliases():
            return [{"canon_key": k, "alias": a} for k, a in aliases]

    monkeypatch.setitem(__import__("sys").modules, "ems_db", FakeDB)
    job_search.invalidate_cache()
    yield_names = lambda q, n=8: [r["display_name"]
                                  for r in job_search.suggest(q, limit=n)]
    return yield_names


@pytest.fixture(autouse=True)
def _clear():
    job_search.invalidate_cache()
    yield
    job_search.invalidate_cache()


def test_prefix_beats_substring(monkeypatch):
    find = _index(monkeypatch, ["Smith, Christine", "Rose, Jasmin - Smith Co"])
    assert find("smi")[0] == "Smith, Christine"


def test_word_start_finds_first_name_in_surname_first_filing(monkeypatch):
    """Jobs are filed "Smith, John", so typing a first name must still find
    them. Whole-string matching alone never would."""
    find = _index(monkeypatch, ["Smith, John - AAA", "Alvarez, Maria"])
    assert find("john") == ["Smith, John - AAA"]


def test_multi_word_query_matches_in_either_order(monkeypatch):
    """People type "david smith" and "smith david" interchangeably."""
    find = _index(monkeypatch, ["Smith, David - Mercury", "Smith, Christine"])
    assert find("david smith")[0] == "Smith, David - Mercury"
    assert find("smith david")[0] == "Smith, David - Mercury"


def test_multi_word_requires_every_word(monkeypatch):
    """AND, not OR — otherwise "david smith" returns every Smith."""
    find = _index(monkeypatch, ["Smith, Christine", "Jones, David"])
    assert find("david smith") == []


def test_typo_still_finds_the_job(monkeypatch):
    find = _index(monkeypatch, ["Smith, Christine", "Alvarez, Maria"])
    assert find("smiht")[0] == "Smith, Christine"


def test_exact_match_outranks_a_longer_prefix_match(monkeypatch):
    find = _index(monkeypatch, ["Stater Bros HQ Expired Medicine", "Stater Bros"])
    assert find("stater bros")[0] == "Stater Bros"


def test_alias_finds_a_differently_named_job(monkeypatch):
    """Mary Mendiola is filed under Action Property Management. Typing the
    tenant name has to reach the umbrella client."""
    find = _index(monkeypatch, ["Action Property Management"],
                  aliases=[("action property management", "Mary Mendiola")])
    assert find("mendio") == ["Action Property Management"]


def test_alias_never_outranks_a_real_name_match(monkeypatch):
    """Live data has "David Smith" recorded as an ALIAS of "Bernardo,
    Froilan-AAA" while a real "Smith, David - Mercury" job exists. Merging
    alias words into the job's own word list ranked Bernardo above Smith
    for "smith" — handing back the wrong customer."""
    find = _index(monkeypatch,
                  ["Bernardo, Froilan-AAA", "Smith, David - Mercury"],
                  aliases=[("bernardo, froilan-aaa", "David Smith")])
    assert find("smith")[0] == "Smith, David - Mercury"
    assert find("smiht")[0] == "Smith, David - Mercury"


def test_alias_hit_is_labelled_so_the_user_can_tell(monkeypatch):
    """A row surfacing under a name that isn't its own must say why, or it
    looks like a bug."""
    _index(monkeypatch, ["Action Property Management"],
           aliases=[("action property management", "Mary Mendiola")])
    rows = job_search.suggest("mendio")
    assert rows[0]["why"] == "also known as"


def test_short_query_returns_nothing(monkeypatch):
    find = _index(monkeypatch, ["Smith, Christine"])
    assert find("s") == []


def test_nonsense_returns_nothing(monkeypatch):
    find = _index(monkeypatch, ["Smith, Christine", "Alvarez, Maria"])
    assert find("qqzzxw") == []


def test_limit_is_honoured(monkeypatch):
    find = _index(monkeypatch, [f"Smithers, Person {i}" for i in range(20)])
    assert len(find("smi", 5)) == 5


def test_missing_alias_support_does_not_break_search(monkeypatch):
    """all_aliases is a ranking bonus. A backend without it must still
    return name matches rather than raising into the search box."""
    entries = [{"canon_key": "smith, john", "display_name": "Smith, John",
                "last_seen_at": ""}]

    class NoAliases:
        @staticmethod
        def iter_jobs():
            return entries

        @staticmethod
        def all_aliases():
            raise RuntimeError("backend too old")

    monkeypatch.setitem(__import__("sys").modules, "ems_db", NoAliases)
    job_search.invalidate_cache()
    assert [r["display_name"] for r in job_search.suggest("smi")] == ["Smith, John"]
