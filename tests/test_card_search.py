"""Finding the right card to pin.

Two real complaints:

  Partial words found nothing. Trello's /search is whole-word and its
  wildcard is unreliable — "garcia*" works but "garci*", "smit*" and
  "mongu*" all return zero — so you had to type the name exactly right.

  The right card wasn't first. Trello searches descriptions and comments
  too, so "david smith" legitimately returns a card that merely mentions
  those words. Trello ranked it below the real Smith card; sorting purely
  by board tier threw that ranking away and floated the wrong card to the
  top because its board happened to be active.
"""
import pytest

import card_search as cs


# ── prefix matching (the "it needs to be exact" complaint) ─────────────
@pytest.mark.parametrize("query,name", [
    ("garci",   "Garcia, Daniel - Mercury"),
    ("smit",    "Smith, David - Mercury"),
    ("mongu",   "Mongue, Gary - AAA"),
    ("kavur",   "Kavuri, Srinivasa - Unit 215"),
    ("washbur", "Washburn, Brenda - Mercury"),
    ("neel",    "Neely, Maria - AAA"),
])
def test_partial_word_matches(query, name):
    assert cs.match_score(query, name) > 0, f"{query!r} should find {name!r}"


def test_word_order_does_not_matter():
    """The office writes it both ways."""
    a = cs.match_score("david smith", "Smith, David - Mercury")
    b = cs.match_score("smith david", "Smith, David - Mercury")
    assert a > 0 and b > 0


def test_punctuation_and_case_ignored():
    assert cs.match_score("SMITH, DAVID", "smith david") > 0
    assert cs.match_score("garcia-vargas", "Garcia Vargas, Antonio") > 0


# ── every token must be answered (the noise complaint) ─────────────────
def test_a_card_matching_only_one_token_is_not_a_match():
    """"david smith" must not match every card containing "smith"."""
    assert cs.match_score("david smith", "Smith, Christine- AAA") == 0


def test_card_matching_no_token_is_not_a_match():
    """This is the exact card that used to outrank Smith, David: it
    matched on its DESCRIPTION, not its name."""
    assert cs.match_score(
        "david smith", "Whaley, John -Allstate-WILDFIRE - PAID") == 0


def test_empty_inputs_score_zero():
    assert cs.match_score("", "Smith, David") == 0
    assert cs.match_score("smith", "") == 0
    assert cs.match_score(None, None) == 0


# ── ranking ────────────────────────────────────────────────────────────
def test_exact_token_beats_a_prefix():
    exact = cs.match_score("smith", "Smith, David")
    prefix = cs.match_score("smit", "Smith, David")
    assert exact > prefix


def test_closer_prefix_scores_higher():
    """"bever" answers "Bevers" better than it answers "Beverly"."""
    assert (cs.match_score("bever", "Bevers, Paul - AAA") >
            cs.match_score("bever", "Kendrick, Beverly & David"))


def test_name_starting_with_the_query_wins():
    assert (cs.match_score("smith", "Smith, David - Mercury") >
            cs.match_score("smith", "Davis-Smith, Felicia"))


# ── merge ──────────────────────────────────────────────────────────────
def test_merge_dedupes_on_card_id_and_prefers_remote():
    """Remote carries the short URL and the live board."""
    local = [{"card_id": "c1", "name": "Smith, David", "board": "",
              "_score": 1.0, "_source": "local"}]
    remote = [{"card_id": "c1", "name": "Smith, David",
               "board": "THE LOGS - EMS", "url": "http://x"}]
    out = cs.merge(local, remote, "smith david")
    assert len(out) == 1
    assert out[0]["board"] == "THE LOGS - EMS"
    assert out[0]["url"] == "http://x"


def test_merge_drops_hits_whose_name_does_not_match():
    remote = [{"card_id": "c9", "name": "Whaley, John -Allstate-WILDFIRE"}]
    assert cs.merge([], remote, "david smith") == []


def test_merge_keeps_local_only_hits():
    """Local is what makes partial words work; a hit Trello could not
    return must survive the merge."""
    local = [{"card_id": "c2", "name": "Mongue, Gary - AAA", "board": "",
              "_score": 1.1, "_source": "local"}]
    out = cs.merge(local, [], "mongu")
    assert [h["card_id"] for h in out] == ["c2"]


def test_merge_skips_rows_with_no_card_id():
    assert cs.merge([], [{"name": "Smith, David"}], "smith") == []


def test_merge_scores_unscored_remote_hits():
    out = cs.merge([], [{"card_id": "c3", "name": "Smith, David"}],
                   "smith david")
    assert out and out[0]["_score"] > 0


# ── the endpoint wires it together ─────────────────────────────────────
def test_search_ranks_by_score_within_tier(monkeypatch):
    """The regression: a weak match on an ACTIVE board must not outrank a
    strong match on an archive board within the same tier ordering."""
    import audit_web
    import card_search
    import trello_client as tc

    remote = [
        {"card_id": "w", "name": "Whaley, John -Allstate-WILDFIRE",
         "board": "DISASTER RESPONSE"},
        {"card_id": "s", "name": "Smith, David - Mercury",
         "board": "THE LOGS - EMS"},
    ]
    monkeypatch.setattr(tc, "find_cards_by_name", lambda q, **k: list(remote))
    monkeypatch.setattr(card_search, "search_local", lambda q, limit=60: [])

    class _Api(audit_web.Api):
        def __init__(self):
            pass
    out = _Api().search_trello("david smith")
    # Whaley matches no token of the NAME, so it is gone entirely.
    assert [h["card_id"] for h in out] == ["s"]


def test_search_asks_trello_without_list_names(monkeypatch):
    """Resolving lane names is one request PER BOARD and took 11.5s. The
    picker shows the board, so it must opt out."""
    import audit_web
    import card_search
    import trello_client as tc

    seen = {}

    def _fake(q, **kw):
        seen.update(kw)
        return []
    monkeypatch.setattr(tc, "find_cards_by_name", _fake)
    monkeypatch.setattr(card_search, "search_local", lambda q, limit=60: [])

    class _Api(audit_web.Api):
        def __init__(self):
            pass
    _Api().search_trello("smith")
    assert seen.get("with_lists") is False


def test_search_still_works_when_trello_is_down(monkeypatch):
    """Local answers on its own — that is the point of mirroring."""
    import audit_web
    import card_search
    import trello_client as tc

    def _boom(q, **k):
        raise RuntimeError("429 rate limited")
    monkeypatch.setattr(tc, "find_cards_by_name", _boom)
    monkeypatch.setattr(card_search, "search_local", lambda q, limit=60: [
        {"card_id": "c1", "name": "Mongue, Gary - AAA", "board": "",
         "_score": 1.2, "_source": "local"}])

    class _Api(audit_web.Api):
        def __init__(self):
            pass
    out = _Api().search_trello("mongu")
    assert [h["card_id"] for h in out] == ["c1"]
