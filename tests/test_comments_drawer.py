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
    state = {"pin": "card1", "actions": [], "fetches": 0, "attachments": []}

    def _get_all(card_id, **kw):
        state["fetches"] += 1
        return list(state["actions"])

    monkeypatch.setattr(audit_web.persistence, "get_trello_card_id",
                        lambda c: state["pin"])
    monkeypatch.setattr(tc, "get_all_comments", _get_all)
    # The thread now merges attachments in, so these must be stubbed or
    # the suite reaches for the network.
    monkeypatch.setattr(tc, "card_attachments",
                        lambda cid, **kw: list(state["attachments"]))
    monkeypatch.setattr(tc, "_attachment_uploaders", lambda cid: {})
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


# ── attachments in the thread ────────────────────────────────────────
def _att(aid="at1", name="photo.jpg", mime="image/jpeg",
         date="2026-08-12T18:00:00.000Z", previews=None, upload=True):
    return {"id": aid, "name": name, "fileName": name, "mimeType": mime,
            "date": date, "isUpload": upload, "bytes": 343888,
            "url": f"https://trello.com/1/cards/c/attachments/{aid}/download/{name}",
            "previews": previews if previews is not None else [
                {"url": "https://trello.com/p/70",   "width": 70,   "height": 50,
                 "bytes": 698},
                {"url": "https://trello.com/p/250",  "width": 250,  "height": 150,
                 "bytes": 4728},
                {"url": "https://trello.com/p/1200", "width": 1200, "height": 338,
                 "bytes": 39410},
            ]}


def test_attachments_join_the_thread(api):
    """On the sampled boards 18 of 44 cards carry image attachments (183
    images) and NO comment body contained an image link — photos live as
    attachments, so a text-only drawer would show none of them."""
    a, state = api
    state["actions"] = [_action("look at this")]
    state["attachments"] = [_att()]
    res = a.get_card_comments("x")
    kinds = [e["kind"] for e in res["comments"]]
    assert "attachment" in kinds and "comment" in kinds
    assert res["attachments"] == 1


def test_the_thread_is_one_chronological_list(api):
    """Interleaved, not comments-then-files — that is how the card reads."""
    a, state = api
    state["actions"] = [
        _action("newest", date="2026-08-12T20:00:00.000Z", aid="c2"),
        _action("oldest", date="2026-08-12T10:00:00.000Z", aid="c1")]
    state["attachments"] = [_att(date="2026-08-12T15:00:00.000Z")]
    got = [e.get("text") or e.get("name")
           for e in a.get_card_comments("x")["comments"]]
    assert got == ["newest", "photo.jpg", "oldest"]


def test_a_non_image_attachment_is_listed_but_not_shown(api):
    """A PDF belongs in the thread; it just has no thumbnail."""
    a, state = api
    state["attachments"] = [_att(name="scope.pdf", mime="application/pdf",
                                  previews=[])]
    e = a.get_card_comments("x")["comments"][0]
    assert e["kind"] == "attachment" and e["is_image"] is False
    assert e["has_thumb"] is False


def test_no_image_bytes_ride_along_in_the_thread(api):
    """183 attachments inlined would make opening a job cost a camera
    roll — the drawer asks for thumbnails one at a time instead."""
    a, state = api
    state["attachments"] = [_att()]
    blob = repr(a.get_card_comments("x"))
    assert "data:image" not in blob and "base64" not in blob


def test_a_broken_attachment_payload_cannot_kill_the_thread(api,
                                                            monkeypatch):
    """Comments are the point; a bad attachments response must not take
    them down with it."""
    a, state = api
    state["actions"] = [_action("still here")]
    monkeypatch.setattr(tc, "card_attachments", lambda cid, **kw: {"id": "oops"})
    res = a.get_card_comments("x")
    assert res["ok"] is True
    assert [c["text"] for c in res["comments"]] == ["still here"]


# ── comment_image ────────────────────────────────────────────────────
@pytest.fixture
def img_api(api, monkeypatch):
    a, state = api
    state["attachments"] = [_att()]
    seen = []

    def _fetch(url, **kw):
        seen.append(url)
        return b"\x89PNG-bytes"

    monkeypatch.setattr(tc, "fetch_attachment_bytes", _fetch)
    return a, state, seen


def test_thumbnail_uses_a_small_preview(img_api):
    """~5KB instead of ~340KB. This is the difference between a drawer
    that opens instantly and one that downloads the original."""
    a, _, seen = img_api
    res = a.comment_image("x", "at1", False)
    assert res["ok"] is True
    assert res["data_uri"].startswith("data:image/")
    assert seen == ["https://trello.com/p/250"]


def test_enlarging_uses_a_big_preview(img_api):
    a, _, seen = img_api
    a.comment_image("x", "at1", True)
    assert seen == ["https://trello.com/p/1200"]


def test_an_attachment_with_no_previews_falls_back_to_the_original(img_api,
                                                                   monkeypatch):
    """Older uploads have no generated previews."""
    a, state, seen = img_api
    state["attachments"] = [_att(previews=[])]
    a.comment_image("x", "at1", False)
    assert seen and "download" in seen[0]


def test_the_same_image_is_only_downloaded_once(img_api):
    a, _, seen = img_api
    a.comment_image("x", "at1", False)
    a.comment_image("x", "at1", False)
    assert len(seen) == 1


def test_a_failed_download_is_reported_not_cached(img_api, monkeypatch):
    a, _, _ = img_api
    monkeypatch.setattr(tc, "fetch_attachment_bytes", lambda *a, **k: None)
    assert a.comment_image("x", "at1", False)["ok"] is False


def test_an_unknown_attachment_is_refused(img_api):
    """Never fetch an id that isn't on this card."""
    a, _, seen = img_api
    assert a.comment_image("x", "not-on-this-card", False)["ok"] is False
    assert seen == []


def test_image_cache_is_bounded(img_api):
    """A long session on a photo-heavy board must not grow forever."""
    a, state, _ = img_api
    state["attachments"] = [_att(aid=f"a{i}") for i in range(80)]
    for i in range(80):
        a.comment_image("x", f"a{i}", False)
    assert len(a._cmt_img_cache) <= 61


# ── search + compose, in the drawer's source ─────────────────────────
def test_search_filters_without_refetching(detail_js):
    """Typing must not hit Trello per keystroke."""
    body = detail_js[detail_js.index("function renderEntries"):]
    body = body[:body.index("\n  }")]
    assert "pywebview.api" not in body


def test_search_matches_attachment_names_too(detail_js):
    body = detail_js[detail_js.index("function renderEntries"):]
    body = body[:body.index("\n  }")]
    assert "e.name" in body, "searching should find a file by name"


def test_the_search_term_is_escaped_before_it_is_highlighted(detail_js):
    """The query goes into a RegExp AND into HTML — both are injection
    routes if it is used raw."""
    body = detail_js[detail_js.index("function _hilite"):]
    body = body[:body.index("\n  }")]
    assert "esc(ctx, q)" in body
    assert "\\\\$&" in body, "regex metacharacters in the query must be escaped"


def test_the_canonical_phrases_have_exactly_one_home(detail_js):
    """These strings are what the office greps for, so the same event
    must not exist under two wordings.

    The drawer used to carry its own copy on the IPR / Upload quick-post
    buttons. Those are gone: ticking the checklist item posts the phrase
    now, so post_canned is the single place it is written and the JS must
    not reintroduce a second spelling.
    """
    import inspect
    src = inspect.getsource(audit_web.Api.post_canned)
    for phrase in ("Initial Photo Report Created and Uploaded to OD.",
                   "Initial Upload submitted To WC."):
        assert phrase in src, f"post_canned lost {phrase!r}"
        assert phrase not in detail_js, (
            f"{phrase!r} is back in the JS - the tick posts it now, and a "
            "second copy is how one event acquires two wordings")


def test_the_ticked_items_map_to_those_phrases():
    """The mapping that replaced the buttons."""
    vals = set(audit_web.Api._TICK_POSTS.values())
    assert ("canned", "ipr") in vals
    assert ("canned", "upload") in vals


def test_posting_rereads_the_thread(detail_js):
    """What Trello stored — mention expansion, its own timestamp — is the
    truth worth showing, not an optimistic local echo."""
    body = detail_js[detail_js.index("    async function post("):]
    body = body[:body.index("\n    }")]
    assert "post_comment" in body and "loadCommentsInto" in body


def test_thumbnails_are_lazy(detail_js):
    """A card can carry 180+ attachments."""
    assert "IntersectionObserver" in detail_js


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


# ── reading the thread at a glance ───────────────────────────────────
def test_the_author_is_not_muted_with_the_timestamp(detail_js):
    """"Hard to distinguish between users." The name and the time were
    one muted run, so nothing in the row said who spoke."""
    assert ".cmt-name{" in detail_js and "font-weight:700" in detail_js
    assert '<span class="cmt-name">' in detail_js
    assert '<span class="cmt-when">' in detail_js


def test_each_message_gets_its_own_bubble(detail_js):
    """Messages separated only by a hairline read as one long block."""
    assert ".cmt-bubble{" in detail_js
    assert '<div class="cmt-bubble">' in detail_js


def test_mentions_are_styled_apart_from_the_author(detail_js):
    """A tagged person is not the person speaking — undecorated, an
    @name in the body looked exactly like the author line above it."""
    assert ".cmt-at{" in detail_js
    body = detail_js[detail_js.index("function _mentions"):]
    body = body[:body.index("\n  }")]
    assert "cmt-at" in body


def test_a_mention_must_start_a_word(detail_js):
    """These comments are mostly pasted email threads, so
    "aaron@servpro10100.com" must not have its domain chipped."""
    body = detail_js[detail_js.index("function _mentions"):]
    body = body[:body.index("\n  }")]
    assert r"[\s(\[,;:]" in body, "the @ needs a boundary before it"


def test_mentions_skip_anchor_text(detail_js):
    """A URL can carry an @ in its visible text; chipping it reads as a
    person tagged inside a link."""
    body = detail_js[detail_js.index("function _mentions"):]
    body = body[:body.index("\n  }")]
    assert "<a" in body and "split" in body


def test_decoration_never_touches_markup(detail_js):
    """Mentions and highlights are applied to text BETWEEN tags — inside
    an href they would corrupt the link."""
    body = detail_js[detail_js.index("function _inTextNodes"):]
    body = body[:body.index("\n  }")]
    assert "(^|>)([^<]+)" in body


# ── the drawer is reached from a tab, not a button in a section ──────
def test_the_trello_section_is_gone(detail_js):
    """Removed on request — the drawer covers the comments and the chips
    already carried the rest."""
    assert 'id="trello-info"' not in detail_js
    assert 'data-action="comments"' not in detail_js


def test_the_enrichment_call_survived_the_section(detail_js):
    """It is ALSO what fills the footer's 📧 Copy email button. Deleting
    the section without keeping this would have silently disabled that
    button, with nothing on screen to explain why."""
    body = detail_js[detail_js.index("async function loadTrelloInfo"):]
    body = body[:body.index("\n  }")]
    assert "trello_enrichment" in body
    assert "dataset.email" in body
    assert "if (bodyEl) bodyEl.innerHTML" in body, "must tolerate no body"


def test_the_tab_lives_inside_the_drawer(detail_js):
    """That is what makes it one object: when the drawer is parked
    off-screen the tab is the part still showing, so opening slides the
    whole thing in rather than summoning a separate panel."""
    body = detail_js[detail_js.index("function _ensureCommentsDrawer"):]
    body = body[:body.index("\n  }")]
    assert 'id="cmt-tab"' in body
    assert body.index('cmt-tab') < body.index('cmt-body'), \
        "the tab is part of the drawer's own markup"


def test_the_tab_hangs_off_the_drawers_outer_edge(detail_js):
    assert ".cmt-tab{position:absolute;" in detail_js
    assert "writing-mode:vertical-rl" in detail_js, "reads as a side tab"


def test_the_tab_clears_the_scrollbar_and_the_top_bar(detail_js):
    """Measured, not assumed. A fixed drawer sits at the viewport edge
    where the scrollbar also lives, and the top bar is a different height
    in Audit than in Snapshot — a hardcoded offset is wrong in one of
    them whichever number you pick."""
    body = detail_js[detail_js.index("function _placeTab"):]
    body = body[:body.index(chr(10) + "  }")]
    assert "window.innerWidth - document.documentElement.clientWidth" in body
    assert "getBoundingClientRect" in body


def test_the_tab_clears_every_bar_not_just_the_top_one(detail_js):
    """The audit panel stacks a topbar, a mode row and a toolbar.
    Anchoring to `.topbar` alone parked the tab on top of the filter
    chips — the main content element is the honest answer to "where does
    the page actually start"."""
    body = detail_js[detail_js.index("function _placeTab"):]
    body = body[:body.index(chr(10) + "  }")]
    assert 'querySelector("main")' in body
    assert ".mode-row" in body, "and a fallback when there is no <main>"


def test_the_tab_is_re_placed_when_things_move(detail_js):
    """The toolbar changes height and the scrollbar comes and goes."""
    assert detail_js.count("_placeTab()") >= 3
    assert 'addEventListener("resize", _placeTab)' in detail_js


def test_the_tab_exists_before_the_drawer_is_opened(detail_js):
    """It is the only way in now, so it cannot be built on first open."""
    body = detail_js[detail_js.index("function syncCommentsDrawer"):]
    body = body[:body.index("\n  }")]
    assert "_ensureCommentsDrawer()" in body
    assert body.index("_ensureCommentsDrawer()") < body.index("commentsDrawerIsOpen()")


def test_no_tab_when_the_job_has_no_card(detail_js):
    """A tab that opens an empty panel is worse than no tab."""
    body = detail_js[detail_js.index("function syncCommentsDrawer"):]
    body = body[:body.index("\n  }")]
    assert "trello_card_id" in body and "display" in body


def test_the_tab_says_which_way_it_goes(detail_js):
    assert "Open Comments" in detail_js and "Close Comments" in detail_js


# ── @ in the composer ────────────────────────────────────────────────
def test_the_composer_offers_board_members(detail_js):
    """Trello only notifies on an exact @username, so a typed guess
    reaches nobody. A mention that looks right and notifies no one is
    worse than not tagging at all."""
    assert "xa_note_members" in detail_js


def test_it_reuses_the_xa_note_member_source(detail_js):
    """Same names the XA-note modal offers, so a person is spelled one
    way everywhere rather than two lists drifting apart."""
    assert detail_js.count("xa_note_members") >= 2


def test_the_trigger_needs_an_at_starting_a_word(detail_js):
    """Otherwise every email address in a pasted thread opens the
    picker mid-typing."""
    body = detail_js[detail_js.index("function _mentionState"):]
    body = body[:body.index(chr(10) + "  }")]
    assert "[" + chr(92) + "s(" + chr(92) + "[]" in body


def test_the_picker_owns_its_keys(detail_js):
    """Enter picks the highlighted name; it must not also fire the
    composer's post handler."""
    body = detail_js[detail_js.index("el.querySelector(" + chr(34) + "#cmt-new"):]
    body = body[:body.index("_wireMentions(el);")]
    assert "_mentionKey(el, e)" in body
    assert body.index("_mentionKey") < body.index("ctrlKey")


def test_selecting_keeps_focus_in_the_textarea(detail_js):
    """mousedown + preventDefault — on click the textarea has already
    blurred and the caret position is gone."""
    body = detail_js[detail_js.index("async function _showMentions"):]
    body = body[:body.index(chr(10) + "  }")]
    assert "mousedown" in body and "preventDefault" in body


def test_members_are_cached_per_job(detail_js):
    """The board roster is one call per job, not one per keystroke."""
    body = detail_js[detail_js.index("async function _members"):]
    body = body[:body.index(chr(10) + "  }")]
    assert "_memberFor" in body


def test_a_moved_caret_cancels_a_late_lookup(detail_js):
    body = detail_js[detail_js.index("async function _showMentions"):]
    body = body[:body.index(chr(10) + "  }")]
    assert "caret moved" in body or "_mentionState(el)" in body


def test_snapshot_can_reach_the_member_list():
    """The drawer is shared, so the method has to exist on both APIs."""
    import snapshot_web
    assert hasattr(snapshot_web.Api, "xa_note_members")


def test_snapshot_comments_are_docked_beside_the_form():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    shared = open(os.path.join(root, "web_shared", "audit_detail.js"),
                  encoding="utf-8").read()
    snapshot = open(os.path.join(root, "snapshot_web_assets", "index.html"),
                    encoding="utf-8").read()
    assert '<body class="snapshot-panel' in snapshot
    assert "body.snapshot-panel.cmt-docked" in shared
    assert 'padding-right:var(--cmt-dock-width,380px)' in shared
    assert 'padding-bottom:min(46vh,420px)' in shared
    assert "_syncCommentsDock(el)" in shared


def test_the_module_actually_loads():
    """`node --check` only proves it PARSES. This evaluates it against a
    stub DOM, which is what caught "ReferenceError: _wireMentions is not
    defined" being possible at all."""
    import json
    import subprocess
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    js = os.path.join(here, "web_shared", "audit_detail.js").replace("\\", "/")
    prog = (
        "const fs=require('fs');const src=fs.readFileSync(%s,'utf8');"
        "const stub=()=>({classList:{add(){},remove(){},toggle(){}},style:{},"
        "addEventListener(){},appendChild(){},querySelector:()=>null,"
        "querySelectorAll:()=>[]});"
        "global.window={addEventListener:()=>{},"
        "localStorage:{getItem:()=>null,setItem:()=>{}},innerWidth:1400};"
        "global.document={getElementById:()=>null,querySelector:()=>null,"
        "querySelectorAll:()=>[],createElement:stub,head:{appendChild(){}},"
        "body:{appendChild(){}},documentElement:{clientWidth:1385}};"
        "global.localStorage=window.localStorage;"
        "eval(src);"
        "console.log(Object.keys(global.window.AuditDetail).length);"
    ) % json.dumps(js)
    r = subprocess.run(["node", "-e", prog], capture_output=True, text=True)
    assert r.returncode == 0, f"module failed to load: {r.stderr.strip()}"
    assert int(r.stdout.strip()) > 15


def test_the_mention_picker_cannot_break_the_drawer():
    """It is an enhancement. Unguarded, anything wrong in it took the
    whole detail render down with "Failed to load" and no comments."""
    import io
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    js = io.open(os.path.join(here, "web_shared", "audit_detail.js"),
                 encoding="utf-8").read()
    assert "try { _wireMentions(el); } catch" in js


def test_the_tab_measures_the_pane_scrollbar_not_the_document(detail_js):
    """Inside the shell's iframe the PAGE rarely scrolls; a PANE does,
    and its scrollbar sits at the same right edge the fixed drawer is
    pinned to. Measuring only innerWidth-clientWidth returned 0, so the
    tab sat on top of it."""
    body = detail_js[detail_js.index("function _placeTab"):]
    body = body[:body.index(chr(10) + "  }")]
    assert "offsetWidth - node.clientWidth" in body
    assert 'querySelectorAll("main, main > *' in body


def test_an_overlay_scrollbar_is_inferred(detail_js):
    """It takes no layout width, so it cannot be measured — only
    inferred from the pane being scrollable at all."""
    body = detail_js[detail_js.index("function _placeTab"):]
    body = body[:body.index(chr(10) + "  }")]
    assert "scrollHeight - node.clientHeight" in body


def test_the_tab_hugs_the_panel_when_open(detail_js):
    """Open, the drawer covers the pane's scrollbar itself, so the
    clearance that is right when closed becomes a GAP between tab and
    panel — and a gap is what stops it reading as one object."""
    body = detail_js[detail_js.index("function _placeTab"):]
    body = body[:body.index(chr(10) + "  }")]
    assert 'commentsDrawerIsOpen() ? "-30px"' in body


def test_closing_re_places_the_tab(detail_js):
    """The offset differs by state, so closing has to recompute it or
    the tab stays hugged to a drawer that is no longer there."""
    body = detail_js[detail_js.index("function closeCommentsDrawer"):]
    body = body[:body.index(chr(10) + "  }")]
    assert "_placeTab()" in body
