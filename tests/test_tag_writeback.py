"""Tagging a job's photos from the app.

Everything here follows from what the live API actually does, probed
before any of it was written:

  * POST /photos/{id}/tags APPENDS. The response echoes only what was
    added, which is what made it look like a replace at first glance.
    Appending is what makes it safe to tag a photo that already carries
    a room tag.
  * A tag write does NOT change the photo's `updated_at`, so the tag
    cache — which revalidates on that stamp — must be cleared by hand or
    it serves the pre-write answer forever.
  * There is NO removal endpoint. A tag written here comes off only in
    the CompanyCam app, which is why nothing writes without a preview.
"""
import companycam_api as cc


def _photo(pid, tags=(), when=1_700_000_000, who="FB"):
    return {"id": pid, "captured_at": when, "creator_name": who,
            "tags": list(tags)}


def _stub(monkeypatch, photos, posted=None):
    monkeypatch.setattr(cc, "list_project_photos", lambda pid, **k: photos)
    monkeypatch.setattr(cc, "attach_tags", lambda ph, **k: None)
    if posted is not None:
        def _call(path, method="GET", data=None, **k):
            posted.append((path, method, data))
            return []
        monkeypatch.setattr(cc, "_call", _call)


# ── the guards ─────────────────────────────────────────────────────────

def test_an_untagged_photo_is_proposed(monkeypatch):
    _stub(monkeypatch, [_photo("1")])
    p = cc.plan_stage_tagging("proj", "Demo")
    assert [r["id"] for r in p["tag"]] == ["1"]


def test_a_photo_already_classified_is_left_alone(monkeypatch):
    """Overwriting somebody's classification from a run-doc line is not a
    tidy-up."""
    _stub(monkeypatch, [_photo("1", ["Initial Inspection"])])
    p = cc.plan_stage_tagging("proj", "Demo")
    assert p["tag"] == []
    assert "already classified as Initial" in p["skip"][0]["why"]


def test_a_room_tag_alone_does_not_block_it(monkeypatch):
    """A room is not a stage. A photo tagged only "Kitchen" still needs
    to know which visit it belongs to."""
    _stub(monkeypatch, [_photo("1", ["Kitchen"])])
    assert [r["id"] for r in cc.plan_stage_tagging("proj", "Demo")["tag"]] == ["1"]


def test_a_photo_that_already_has_this_exact_tag_is_skipped(monkeypatch):
    _stub(monkeypatch, [_photo("1", ["Demo"])])
    p = cc.plan_stage_tagging("proj", "Demo")
    assert p["tag"] == [] and "already tagged Demo" in p["skip"][0]["why"]


def test_only_untagged_can_be_turned_off_deliberately(monkeypatch):
    _stub(monkeypatch, [_photo("1", ["Initial Inspection"])])
    p = cc.plan_stage_tagging("proj", "Demo", only_untagged=False)
    assert [r["id"] for r in p["tag"]] == ["1"]


def test_another_visit_is_not_touched(monkeypatch):
    a, b = _photo("1"), _photo("2", when=1_700_500_000)
    _stub(monkeypatch, [a, b])
    day = cc.date_label(a)
    p = cc.plan_stage_tagging("proj", "Demo", on_date=day)
    assert [r["id"] for r in p["tag"]] == ["1"]


def test_a_different_tech_is_not_touched(monkeypatch):
    _stub(monkeypatch, [_photo("1", who="FB"), _photo("2", who="Uli")])
    p = cc.plan_stage_tagging("proj", "Demo", tech="uli")
    assert [r["id"] for r in p["tag"]] == ["2"]


def test_planning_writes_nothing(monkeypatch):
    posted = []
    _stub(monkeypatch, [_photo("1")], posted)
    cc.plan_stage_tagging("proj", "Demo")
    assert not [x for x in posted if x[1] == "POST"]


def test_a_missing_stage_is_refused(monkeypatch):
    _stub(monkeypatch, [])
    assert cc.plan_stage_tagging("proj", "")["ok"] is False


# ── the write ──────────────────────────────────────────────────────────

def test_the_write_appends_one_tag(monkeypatch):
    posted = []
    _stub(monkeypatch, [], posted)
    r = cc.add_photo_tags("77", ["Demo"])
    assert r["ok"] is True
    assert posted == [("/photos/77/tags", "POST", {"tags": ["Demo"]})]


def test_the_cache_is_cleared_because_updated_at_will_not_change(monkeypatch):
    """Verified against the live API: a tag write leaves updated_at
    alone, so photo_tags would keep serving the pre-write answer."""
    posted = []
    _stub(monkeypatch, [], posted)
    cc._TAG_CACHE["77"] = {"t": ["Kitchen"], "u": "stamp"}
    cc.add_photo_tags("77", ["Demo"])
    assert "77" not in cc._TAG_CACHE


def test_a_failed_write_is_reported_not_swallowed(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("403 forbidden")

    monkeypatch.setattr(cc, "_call", _boom)
    r = cc.add_photo_tags("77", ["Demo"])
    assert r["ok"] is False and "403" in r["error"]


def test_a_partial_apply_is_not_a_success(monkeypatch):
    calls = {"n": 0}

    def _call(path, method="GET", data=None, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("rate limited")
        return []

    monkeypatch.setattr(cc, "_call", _call)
    r = cc.apply_stage_tagging([{"id": "1"}, {"id": "2"}], "Demo")
    assert r["ok"] is False
    assert r["tagged"] == 1 and len(r["failed"]) == 1


def test_the_plan_says_tags_cannot_be_removed(monkeypatch):
    """The constraint has to reach the person clicking, not just the
    commit message."""
    _stub(monkeypatch, [_photo("1")])
    assert "cannot be removed" in cc.plan_stage_tagging("proj", "Demo")["note"]
