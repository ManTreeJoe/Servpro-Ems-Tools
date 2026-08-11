"""Card search puts live work above the archive.

THE LOGS - EMS (1,388 cards) and the AR BOARD (1,092) hold more cards
than every other board combined, so in Trello's own relevance order a
finished job or a receivable routinely outranked the job somebody is
working right now.
"""
import pytest

import trello_boards as tb


REAL_BOARDS = [
    "WORK IN PROGRESS", "DISASTER RESPONSE", "ESTIMATING", "COMMERCIAL",
    "CONTENTS", "AR  BOARD", "EMS BILLING DISPUTES",
    "RECON CLOSEOUT/COLLECTIONS", "THE LOGS - EMS",
]


# ── classification ─────────────────────────────────────────────────────
@pytest.mark.parametrize("name", [
    "WORK IN PROGRESS", "DISASTER RESPONSE", "ESTIMATING",
    "COMMERCIAL", "CONTENTS",
])
def test_live_boards_are_active(name):
    assert tb.tier(name) == tb.ACTIVE


@pytest.mark.parametrize("name", [
    "THE LOGS - EMS", "AR  BOARD", "RECON CLOSEOUT/COLLECTIONS",
    "EMS BILLING DISPUTES",
])
def test_finished_and_billing_boards_are_archive(name):
    assert tb.tier(name) == tb.ARCHIVE


def test_double_space_in_ar_board_is_matched():
    """The real board is literally 'AR  BOARD' with two spaces. Matching
    on the raw string missed it and the whole board stayed in tier 1."""
    assert tb.tier("AR  BOARD") == tb.ARCHIVE
    assert tb.tier("ar board") == tb.ARCHIVE
    assert tb.tier("AR BOARD") == tb.ARCHIVE


def test_unknown_board_is_active_not_archive():
    """A board nobody classified is more likely new live work than a new
    archive, and burying it would be silent."""
    assert tb.tier("SOME NEW 2027 BOARD") == tb.ACTIVE
    assert tb.tier("") == tb.ACTIVE
    assert tb.tier(None) == tb.ACTIVE


def test_ar_substring_does_not_catch_unrelated_boards():
    for name in ("ARCHITECTURAL LEADS", "CARPET CARE", "AR"):
        assert tb.tier(name) == tb.ACTIVE, name


# ── ordering ───────────────────────────────────────────────────────────
def test_every_active_board_sorts_before_every_archive_board():
    active = [b for b in REAL_BOARDS if tb.is_active(b)]
    archive = [b for b in REAL_BOARDS if not tb.is_active(b)]
    assert max(tb.sort_key(b) for b in active) < \
           min(tb.sort_key(b) for b in archive)


def test_work_in_progress_leads_the_active_tier():
    others = [b for b in REAL_BOARDS if tb.is_active(b)
              and b != "WORK IN PROGRESS"]
    assert all(tb.sort_key("WORK IN PROGRESS") < tb.sort_key(b)
               for b in others)


def test_sort_is_stable_within_a_board():
    """Trello's relevance order has to survive inside a board — replacing
    it with an alphabetical one would be a different regression."""
    hits = [{"n": i, "board": "THE LOGS - EMS"} for i in range(5)]
    hits.sort(key=lambda h: tb.sort_key(h["board"]))
    assert [h["n"] for h in hits] == [0, 1, 2, 3, 4]


def test_classify_groups_and_orders():
    out = tb.classify(REAL_BOARDS)
    assert [c["name"] for c in out][0] == "WORK IN PROGRESS"
    tiers = [c["tier"] for c in out]
    assert tiers == sorted(tiers, key=lambda t: t == "archive")
    assert len(out) == len(REAL_BOARDS)


def test_classify_dedupes():
    assert len(tb.classify(["CONTENTS", "CONTENTS"])) == 1


# ── the search endpoint ────────────────────────────────────────────────
class _Api(__import__("audit_web").Api):
    def __init__(self):
        pass


@pytest.fixture
def api(monkeypatch):
    hits = [
        {"card_id": "l1", "name": "Smith, David", "board": "THE LOGS - EMS",
         "list_name": "Done"},
        {"card_id": "a1", "name": "Smith, David", "board": "AR  BOARD",
         "list_name": "Billed"},
        {"card_id": "w1", "name": "Smith, David", "board": "WORK IN PROGRESS",
         "list_name": "Mitigation"},
    ]
    import trello_client as tc
    monkeypatch.setattr(tc, "find_cards_by_name",
                        lambda q, **k: list(hits))
    return _Api()


def test_active_card_is_returned_first(api):
    out = api.search_trello("smith")
    assert [h["card_id"] for h in out] == ["w1", "l1", "a1"]
    assert out[0]["tier"] == "active"


def test_archive_hits_are_still_returned(api):
    """Ordering, not hiding — pinning an old job is exactly when you go
    looking for one."""
    assert len(api.search_trello("smith")) == 3


def test_board_filter_restricts_results(api):
    out = api.search_trello("smith", ["WORK IN PROGRESS"])
    assert [h["card_id"] for h in out] == ["w1"]


def test_board_filter_normalises_the_double_space(api):
    assert [h["card_id"] for h in api.search_trello("smith", ["AR BOARD"])] == ["a1"]


def test_empty_filter_means_everything(api):
    assert len(api.search_trello("smith", [])) == 3
    assert len(api.search_trello("smith", None)) == 3


def test_short_query_is_ignored(api):
    assert api.search_trello("s") == []


def test_search_survives_a_trello_failure(monkeypatch):
    import trello_client as tc

    def _boom(q, **k):
        raise RuntimeError("429")
    monkeypatch.setattr(tc, "find_cards_by_name", _boom)
    assert _Api().search_trello("smith") == []


def test_snapshot_proxies_the_search_api():
    """audit_detail.js is one card rendered by audit AND snapshot."""
    import snapshot_web
    for name in ("search_trello", "list_search_boards"):
        assert hasattr(snapshot_web.Api, name), f"snapshot_web missing {name}"
