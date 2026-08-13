"""💬 The card's comment thread, read next to the audit.

The Trello section already showed five comments, truncated to 400
characters and collapsed inside a <details> — enough to notice a thread
exists, no use for reading it, so following a job's running commentary
still meant opening the card in a browser.

The drawer reads the whole thread. The interesting part is not the
rendering but the staleness: comments are posted from a dozen surfaces
(missing items, the activity composer, hygiene, docusign, docusketch,
the adjuster monitor), and a cached thread that misses the comment you
just sent reads as "it didn't post".
"""
import io
import os

import pytest

import audit_web
import trello_client as tc


_SHARED = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web_shared")


def _action(text, who="Nathan Bupte", date="2026-08-12T17:04:00.000Z", aid="a1"):
    return {"id": aid, "type": "commentCard", "date": date,
            "data": {"text": text}, "memberCreator": {"fullName": who}}


@pytest.fixture
def api(monkeypatch):
    a = audit_web.Api.__new__(audit_web.Api)
    state = {"pin": "card1", "actions": [], "fetches": 0}

    def _get_all(card_id, **kw):
        state["fetches"] += 1
        return list(state["actions"])

    monkeypatch.setattr(audit_web.persistence, "get_trello_card_id",
                        lambda c: state["pin"])
    monkeypatch.setattr(tc, "get_all_comments", _get_all)
    # post_comment must succeed offline, or it never flags the card and
    # the staleness tests below pass for the wrong reason.
    monkeypatch.setattr(tc, "_call", lambda *a, **k: {"id": "act1"})
    tc._COMMENTS_DIRTY.clear()
    return a, state


# ── the thread itself ────────────────────────────────────────────────
def test_returns_the_whole_thread_newest_first(api):
    a, state = api
    state["actions"] = [_action("third", aid="a3"), _action("second", aid="a2"),
                        _action("first", aid="a1")]
    res = a.get_card_comments("Doe, Jane")
    assert res["ok"] is True
    assert [c["text"] for c in res["comments"]] == ["third", "second", "first"]
    assert res["count"] == 3


def test_text_is_not_truncated(api):
    """The 400-char cut in the Trello section is what made it unreadable."""
    a, state = api
    long_text = "x" * 3000
    state["actions"] = [_action(long_text)]
    assert a.get_card_comments("Doe, Jane")["comments"][0]["text"] == long_text


def test_empty_comments_are_skipped(api):
    a, state = api
    state["actions"] = [_action("real"), _action("   "), _action("")]
    assert len(a.get_card_comments("x")["comments"]) == 1


def test_no_pin_is_not_an_error_state(api):
    """A job with no card should say so, not look like a failure."""
    a, state = api
    state["pin"] = ""
    res = a.get_card_comments("Doe, Jane")
    assert res["ok"] is False and res["has_card"] is False


def test_a_trello_failure_is_reported_not_raised(api, monkeypatch):
    a, _ = api
    monkeypatch.setattr(tc, "get_all_comments",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("429")))
    res = a.get_card_comments("Doe, Jane")
    assert res["ok"] is False and "429" in res["error"]


def test_limit_is_respected(api):
    a, state = api
    state["actions"] = [_action(f"c{i}", aid=f"a{i}") for i in range(10)]
    assert len(a.get_card_comments("x", 4)["comments"]) == 4


# ── caching + the staleness that matters ─────────────────────────────
def test_second_read_is_served_from_cache(api):
    a, state = api
    state["actions"] = [_action("hi")]
    a.get_card_comments("x")
    a.get_card_comments("x")
    assert state["fetches"] == 1


def test_posting_a_comment_beats_the_cache(api):
    """The bug this guards: post, reopen, and your comment isn't there."""
    a, state = api
    state["actions"] = [_action("before")]
    a.get_card_comments("x")
    state["actions"] = [_action("after", aid="a2"), _action("before")]
    tc.post_comment("card1", "after")          # flags the card
    res = a.get_card_comments("x")
    assert state["fetches"] == 2, "cache was served despite a fresh post"
    assert res["comments"][0]["text"] == "after"


def test_the_dirty_flag_is_one_shot(api):
    """One post must cost exactly one extra fetch, not permanently
    disable the cache — the drawer re-reads on every job you open."""
    a, state = api
    state["actions"] = [_action("hi")]
    a.get_card_comments("x")                   # warm  -> fetch 1
    tc.post_comment("card1", "x")              # flags the card
    a.get_card_comments("x")                   # flag  -> fetch 2
    a.get_card_comments("x")                   # cached -> still 2
    assert state["fetches"] == 2, "flag should not force every later read"


def test_invalidate_clears_the_thread(api):
    a, state = api
    state["actions"] = [_action("hi")]
    a.get_card_comments("x")
    a.invalidate_comments_cache("x")
    a.get_card_comments("x")
    assert state["fetches"] == 2


def test_invalidate_with_no_client_clears_everything(api):
    a, state = api
    state["actions"] = [_action("hi")]
    a.get_card_comments("x")
    assert a.invalidate_comments_cache()["cleared"] >= 1


# ── consume_comment_dirty ────────────────────────────────────────────
def test_dirty_flag_semantics():
    tc._COMMENTS_DIRTY.clear()
    assert tc.consume_comment_dirty("c1") is False
    tc._COMMENTS_DIRTY.add("c1")
    assert tc.consume_comment_dirty("c1") is True
    assert tc.consume_comment_dirty("c1") is False
    assert tc.consume_comment_dirty("") is False


def test_post_comment_flags_the_card(monkeypatch):
    tc._COMMENTS_DIRTY.clear()
    monkeypatch.setattr(tc, "_call", lambda *a, **k: {"id": "act1"})
    tc.post_comment("cardX", "hello")
    assert tc.consume_comment_dirty("cardX") is True


def test_a_failed_post_does_not_flag(monkeypatch):
    """Nothing changed on the card, so nothing is stale."""
    tc._COMMENTS_DIRTY.clear()

    def _boom(*a, **k):
        raise RuntimeError("nope")

    monkeypatch.setattr(tc, "_call", _boom)
    tc.post_comment("cardY", "hello")
    assert tc.consume_comment_dirty("cardY") is False


# ── avatar initials ──────────────────────────────────────────────────
@pytest.mark.parametrize("name,want", [
    ("Nathan Bupte", "NB"),
    ("Mary Anne Smith", "MS"),
    ("Fernando", "FE"),
    ("", "?"),
    ("   ", "?"),
    (None, "?"),
])
def test_member_initials(name, want):
    assert audit_web._member_initials(name) == want


def test_member_initials_is_not_the_tech_rule():
    """`audit_logic.initials_for_name` now answers a franchise question —
    which of the seven leads is this, and how is their photo folder
    named. A Trello member is often office staff who is not a tech at
    all, so the two must not be wired together."""
    import inspect
    fn = audit_web._member_initials
    src = inspect.getsource(fn).replace(fn.__doc__ or "", "")   # code, not prose
    assert "initials_for_name" not in src
    assert "tech_folder_label" not in src


# ── parity: the shared detail is used by Audit AND Snapshot ──────────
def test_snapshot_exposes_the_same_methods():
    """web_shared/audit_detail.js renders in both panels, so a method it
    calls must exist on both APIs or the drawer is dead in Snapshot."""
    import snapshot_web
    for name in ("get_card_comments", "invalidate_comments_cache"):
        assert hasattr(snapshot_web.Api, name), f"snapshot_web.Api lacks {name}"


# ── the drawer's own source ──────────────────────────────────────────
@pytest.fixture(scope="module")
def detail_js():
    return io.open(os.path.join(_SHARED, "audit_detail.js"),
                   encoding="utf-8").read()


def test_comment_text_is_escaped_before_it_is_linkified(detail_js):
    """Comments are arbitrary text off the internet. Linkifying first
    would let a pasted <script> through on the way to innerHTML."""
    body = detail_js[detail_js.index("function _linkify"):]
    body = body[:body.index("\n  }")]
    assert body.index("esc(ctx") < body.index("replace("), (
        "escape first, then linkify")


def test_the_open_drawer_follows_the_selection(detail_js):
    """A drawer that kept showing the previous job's thread would be
    worse than the browser tab it replaces."""
    assert "syncCommentsDrawer(r, ctx)" in detail_js


def test_a_late_reply_cannot_overwrite_the_current_job(detail_js):
    """Click through three jobs quickly and the slowest response must not
    win — it would show one job's comments under another's name."""
    assert "el._token" in detail_js


def test_the_drawer_is_exported(detail_js):
    for fn in ("openCommentsDrawer", "closeCommentsDrawer",
               "toggleCommentsDrawer", "syncCommentsDrawer"):
        assert f"\n    {fn},\n" in detail_js, f"{fn} missing from AuditDetail"


def test_every_loader_got_the_cache_bust():
    """Editing web_shared without bumping ?v= in EVERY index.html that
    loads it means the change never reaches the screen."""
    import re
    root = os.path.dirname(_SHARED)
    vs = set()
    for panel in os.listdir(root):
        idx = os.path.join(root, panel, "index.html")
        if not (panel.endswith("_assets") and os.path.isfile(idx)):
            continue
        html = io.open(idx, encoding="utf-8", errors="ignore").read()
        vs.update(re.findall(r"audit_detail\.js\?v=([A-Za-z0-9]+)", html))
    assert len(vs) <= 1, f"audit_detail.js loaded at mixed versions: {vs}"
