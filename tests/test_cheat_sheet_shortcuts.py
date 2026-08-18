"""⭐ My Shortcuts — the user's own links and copy buttons.

The cheat sheet is a shipped markdown file: the same for everyone, and
read-only for good reason. But half of what anyone reaches for daily is
personal — a Workcenter URL, the office number, a snippet pasted twenty
times a day — and those had nowhere to live except a sticky note.

Saved in persistence rather than written back into the markdown, which
the next release would overwrite.
"""
import io
import os

import pytest

import cheat_sheet_web as cs
import persistence

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def api():
    """Real Api against the real store, with the key restored after."""
    a = cs.Api()
    before = persistence.get(cs.Api._QUICK_KEY)
    try:
        persistence.set_value(cs.Api._QUICK_KEY, [])
        yield a
    finally:
        persistence.set_value(cs.Api._QUICK_KEY, before)


@pytest.fixture(scope="module")
def js():
    return io.open(os.path.join(_ROOT, "cheat_sheet_web_assets", "app.js"),
                   encoding="utf-8").read()


# ── storing them ─────────────────────────────────────────────────────
def test_round_trip(api):
    api.save_quick_items([
        {"label": "Workcenter", "kind": "link", "value": "https://wc.example.com"},
        {"label": "Office #", "kind": "copy", "value": "951-398-3240"},
    ])
    items = api.quick_items()["items"]
    assert [i["label"] for i in items] == ["Workcenter", "Office #"]
    assert items[0]["kind"] == "link" and items[1]["kind"] == "copy"


def test_order_is_preserved(api):
    """The panel owns the ordering, so the store must not re-sort."""
    api.save_quick_items([{"label": c, "kind": "copy", "value": c}
                          for c in "CBA"])
    assert [i["label"] for i in api.quick_items()["items"]] == ["C", "B", "A"]


def test_empty_to_start(api):
    assert api.quick_items() == {"ok": True, "items": []}


@pytest.mark.parametrize("bad", [
    {"label": "", "value": "x"},
    {"label": "x", "value": ""},
    {"label": "   ", "value": "   "},
    "not a dict",
    None,
])
def test_blank_entries_are_dropped(api, bad):
    """A blank label renders an invisible button; a blank value renders
    one that does nothing."""
    api.save_quick_items([bad])
    assert api.quick_items()["items"] == []


def test_an_unknown_kind_becomes_a_copy(api):
    """Rather than rendering a button whose click does nothing."""
    api.save_quick_items([{"label": "x", "kind": "wat", "value": "y"}])
    assert api.quick_items()["items"][0]["kind"] == "copy"


def test_the_list_is_capped(api):
    api.save_quick_items([{"label": f"n{i}", "kind": "copy", "value": "v"}
                          for i in range(200)])
    assert len(api.quick_items()["items"]) == 60


def test_a_garbage_store_does_not_crash_the_panel(api):
    """state.json is a file on disk; it can be hand-edited."""
    persistence.set_value(cs.Api._QUICK_KEY, "not a list")
    assert api.quick_items() == {"ok": True, "items": []}


# ── opening them ─────────────────────────────────────────────────────
@pytest.mark.parametrize("url", [
    "file:///C:/Windows/System32", "javascript:alert(1)",
    r"\\server\share", "mailto:a@b.c", "",
])
def test_only_http_links_open(api, url):
    """A shortcut is free text the user typed. Handing an arbitrary
    scheme to the shell is not something a notes panel should do."""
    assert api.open_link(url)["ok"] is False


def test_an_http_link_is_accepted(api, monkeypatch):
    import dept_browser
    seen = []
    monkeypatch.setattr(dept_browser, "open_url", lambda u: seen.append(u))
    assert api.open_link("https://servpro.interactgo.com/")["ok"] is True
    assert seen == ["https://servpro.interactgo.com/"]


# ── the panel ────────────────────────────────────────────────────────
def test_shortcuts_are_the_first_thing_in_the_contents(js):
    """It is the part that is yours, and the part you open the panel for
    once the shipped pages are familiar."""
    body = js[js.index("function render()"):]
    body = body[:body.index("$(\"#content\").scrollTop")]
    assert body.index("mineTab") < body.index("state.sections.map")


def test_copy_shortcuts_reuse_the_existing_copy_plumbing(js):
    """The panel already has a delegated [data-copy] handler and the
    "✓ Copied" flash — a second copy path would behave differently for
    no reason."""
    assert 'data-copy="${' in js
    assert "copy-btn sc-copy" in js


def test_the_link_form_rejects_a_non_url_before_saving(js):
    """Catching it in the panel means the error lands next to the field
    you typed it in, not in a toast after a round trip."""
    assert "^https?:" in js


def test_the_value_is_shown_next_to_each_button(js):
    """Two shortcuts called "Office #" are otherwise identical, and you
    cannot tell what a copy button pastes until you have pasted it."""
    assert "sc-val" in js


def test_removing_asks_first(js):
    """Slice the DELETE HANDLER, not from the first mention of the class —
    the markup names it earlier than the wiring does."""
    i = js.index('.sc-del").forEach')
    body = js[i:js.index("render();", i)]
    assert "confirm(" in body


def test_every_change_persists_immediately(js):
    """No Save button to forget."""
    for action in ("sc-del", "sc-edit", "sc-save"):
        seg = js[js.index(action):]
        seg = seg[:seg.index("render();") + 9]
        assert "persistShortcuts()" in seg, f"{action} does not persist"
