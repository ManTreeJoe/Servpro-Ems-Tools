"""API-pull labels: fetching tags and filing photos by room.

The 📷 Pull button ignored labels entirely, so every photo landed in one
flat dump. CompanyCam photos carry no descriptive filename — the zip export
bakes the tags into the name, the API does not — so the tag IS the room
signal, and it costs a separate GET /photos/{id}/tags per photo.

Companion to test_companycam_tags.py, which covers the ZIP side. The key
guarantee here is that both transports classify the same tags identically.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import companycam_api as cc
import companycam_import as ci


@pytest.fixture(autouse=True)
def _clear_cache():
    cc.invalidate_tag_cache()
    yield
    cc.invalidate_tag_cache()


# ── the two transports must agree ───────────────────────────────────────

@pytest.mark.parametrize("tags,zip_name", [
    (["Initial Inspection", "Master Bath"],
     "Initial Inspection Master Bath-11-Jun 17 2026 11_35am-6oWw.jpg"),
    (["Garage", "Initial Inspection"],
     "Garage Initial Inspection-10-Jun 17 2026 11_35am-6oWw.jpg"),
    (["Kitchen", "Post"], "Kitchen Post-1-Jun 17 2026 11_35am-6oWw.jpg"),
    (["Demo"], "Demo-3-Jun 17 2026 11_35am-6oWw.jpg"),
    (["Master Bath"], "Master Bath-19-Jun 17 2026 11_35am-6oWw.jpg"),
])
def test_api_and_zip_agree_on_room_and_stage(tags, zip_name):
    """One job pulled both ways must land in ONE folder layout. (The API
    also returns a qualifier; the zip path has no equivalent.)"""
    room, stage, _qual = cc.classify_tags(tags)
    assert (room, stage) == ci.parse_room_stage(zip_name)


@pytest.mark.parametrize("tags,room,stage,qual", [
    (["Exterior", "Initial Inspection"], "Exterior", "Initial", ""),
    (["Attic"],                          "Attic", "", ""),
    ([],                                 "", "", ""),
    (["", None],                         "", "", ""),
    # Equipment is NOT a stage — it is gear photographed IN a room, so it
    # nests inside that room instead of pulling the shot into its own
    # stage folder.
    (["Equipment", "Master Bath"],       "Master Bath", "", "Equipment"),
    (["Initial Inspection", "Master Bedroom", "Equipment"],
                                         "Master Bedroom", "Initial",
                                         "Equipment"),
])
def test_classify_real_account_tag_combinations(tags, room, stage, qual):
    assert cc.classify_tags(tags) == (room, stage, qual)


def test_monitor_is_a_stage_on_both_paths():
    """Reconciled 2026-07-30: `_STAGE_RULES` didn't know Monitor, so the
    same word became a ROOM folder from CompanyCam and a STAGE folder from
    Workcenter."""
    import import_grouping as ig
    assert ci.room_stage_from_label("Monitor")[1] == "Monitor"
    assert (ig.detect_stage("Monitor") or "") == "Monitor"
    assert cc.classify_tags(["Monitor"]) == ("", "Monitor", "")


def test_equipment_is_a_qualifier_on_the_api_path_only():
    """DELIBERATE divergence (2026-07-30, user's folder model).

    The API path files photos <stage>\\<room>\\<qualifier>, where Equipment
    is gear photographed IN a room — so it nests under that room instead of
    pulling the shot out into a stage folder of its own.

    The ZIP path has no qualifier level: `parse_room_stage` returns only
    (room, stage), and _STAGE_RULES still reads Equipment as a stage. So a
    job imported both ways puts Equipment photos in different places.
    Changing the zip side would move photos already on disk, so it needs
    its own decision.
    """
    assert cc.classify_tags(["Equipment"]) == ("", "", "Equipment")
    assert ci.room_stage_from_label("Equipment")[1] == "Equipment"


def test_monitor_and_equipment_still_split_room_from_stage():
    assert cc.classify_tags(["Master Bath", "Monitor"]) == ("Master Bath",
                                                            "Monitor", "")
    assert cc.classify_tags(["Equipment", "Master Bath"]) == ("Master Bath",
                                                              "", "Equipment")


def test_remaining_divergence_mold_after():
    """Still inconsistent, deliberately. CompanyCam reads "Mold After" as
    Post Mold (the after-mold photos); import_grouping reads it as Mold.
    Post Mold looks more correct, but changing import_grouping moves
    Workcenter photos, so it needs its own decision."""
    import import_grouping as ig
    assert ci.room_stage_from_label("Mold After")[1] == "Post Mold"
    assert (ig.detect_stage("Mold After") or "") == "Mold"


# ── tag fetching ────────────────────────────────────────────────────────

def test_photo_tags_shapes_and_caches(monkeypatch):
    calls = {"n": 0}

    def fake_call(path, **kw):
        calls["n"] += 1
        return [{"display_value": "Kitchen"}, {"value": "Demo"}, {}]

    monkeypatch.setattr(cc, "_call", fake_call)
    assert cc.photo_tags("p1") == ["Kitchen", "Demo"]
    assert cc.photo_tags("p1") == ["Kitchen", "Demo"]
    assert calls["n"] == 1, "second lookup should hit the cache"


def test_photo_tags_never_raises(monkeypatch):
    """A rate-limited label lookup must not break the download."""
    def boom(path, **kw):
        raise RuntimeError("429")
    monkeypatch.setattr(cc, "_call", boom)
    assert cc.photo_tags("p1") == []


def test_photo_tags_blank_id_costs_no_call(monkeypatch):
    monkeypatch.setattr(cc, "_call",
                        lambda *a, **k: pytest.fail("should not call"))
    assert cc.photo_tags("") == []
    assert cc.photo_tags(None) == []


def test_attach_tags_populates_in_place(monkeypatch):
    monkeypatch.setattr(cc, "photo_tags",
                        lambda pid, updated_at="": ["Attic"])
    photos = [{"id": "a"}, {"id": "b"}]
    cc.attach_tags(photos)
    assert [p["tags"] for p in photos] == [["Attic"], ["Attic"]]


def test_attach_tags_respects_the_cap(monkeypatch):
    """An accidental full-history pull must not spend thousands of calls
    against the 240/min budget."""
    seen = []

    def fake(pid, updated_at=""):
        seen.append(pid)
        return ["X"]

    monkeypatch.setattr(cc, "photo_tags", fake)
    photos = [{"id": str(i)} for i in range(10)]
    cc.attach_tags(photos, cap=3)
    assert len(seen) == 3
    assert photos[0]["tags"] == ["X"]
    assert photos[5]["tags"] == [], "past the cap: degrade, don't error"


# ── folder-name safety ──────────────────────────────────────────────────

def test_safe_folder_strips_path_separators():
    """'Water Heater / HVAC Closet' is a real tag on this account — the
    slash would silently create a nested folder."""
    out = cc._safe_folder("Water Heater / HVAC Closet")
    assert "/" not in out and "\\" not in out


@pytest.mark.parametrize("bad", ['a<b', 'a>b', 'a:b', 'a"b', "a|b", "a?b", "a*b"])
def test_safe_folder_strips_illegal_windows_chars(bad):
    assert not set(cc._safe_folder(bad)) & set('<>:"/\\|?*')


def test_safe_folder_rejects_trailing_dot_and_space():
    assert cc._safe_folder("Attic. ") == "Attic"


def test_safe_folder_caps_length():
    assert len(cc._safe_folder("x" * 200)) <= 40


# ── the pull routes into room folders ───────────────────────────────────

def _fake_photo(pid, tags, ts=1785435221, who="Fernando Baca"):
    return {"id": pid, "captured_at": ts, "original_url": f"http://x/{pid}.jpg",
            "creator_name": who, "tags": tags}


# The per-shoot box every pulled path now carries: <tech> <MM-DD-YYYY>,
# matching what the zip importer writes. Derived from _fake_photo's
# defaults so the tests move with the fixture.
BOX = "FB 07-30-2026"


@pytest.fixture
def pull_env(tmp_path, monkeypatch):
    written = []

    def fake_download(url, dest):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(b"x")
        written.append(dest)
        return dest

    monkeypatch.setattr(cc, "_download", fake_download)
    monkeypatch.setattr(cc, "attach_tags", lambda ph, **k: ph)

    import persistence
    monkeypatch.setattr(persistence, "get_companycam_seen", lambda pid: {})
    monkeypatch.setattr(persistence, "set_companycam_seen",
                        lambda *a, **k: None)
    return tmp_path, written


def test_pull_files_photos_under_stage_then_room(pull_env, monkeypatch):
    """<stage>/<room>/ — the photo's OWN tags decide both."""
    dest, written = pull_env
    monkeypatch.setattr(cc, "new_photos", lambda pid, since_epoch=None: [
        _fake_photo("a", ["Kitchen", "Demo"]),
        _fake_photo("b", ["Master Bath"]),
    ])
    res = cc.pull_new_photos("1", str(dest), since_epoch=None)
    assert res["ok"] and res["downloaded"] == 2
    rels = sorted(os.path.relpath(w, dest) for w in written)
    assert rels[0].startswith(os.path.join("Demo", BOX, "Kitchen"))
    assert rels[1].startswith(os.path.join(BOX, "Master Bath"))  # no stage tag
    assert res["rooms"] == {"Kitchen": 1, "Master Bath": 1}
    assert res["stages"] == {"Demo": 1}


def test_two_room_tags_do_not_become_one_folder(pull_env, monkeypatch):
    """Live bug on 'Carmen Johnson': the API returns DISCRETE tags, and
    joining them first produced a folder literally named
    'Master Bedroom Master Closet'. The zip path can join, because it
    receives one pre-made label where a room is legitimately multi-word."""
    dest, written = pull_env
    monkeypatch.setattr(cc, "new_photos", lambda pid, since_epoch=None: [
        _fake_photo("a", ["Initial Inspection", "Master Bedroom",
                          "Master Closet"]),
    ])
    cc.pull_new_photos("1", str(dest), since_epoch=None)
    rel = os.path.relpath(written[0], dest)
    assert rel.startswith(os.path.join("Initial", BOX, "Master Bedroom"))
    assert "Master Bedroom Master Closet" not in rel


def test_multiword_room_tag_survives():
    """'Master Bath' is ONE tag — splitting per-tag must not break it."""
    assert cc.classify_tags(["Equipment", "Master Bath"])[0] == "Master Bath"


def test_photo_stage_tag_overrides_the_callers_stage(pull_env, monkeypatch):
    """Live bug: the tag stage was computed and then thrown away, so every
    photo went under whichever stage the review panel picked."""
    dest, written = pull_env
    monkeypatch.setattr(cc, "new_photos", lambda pid, since_epoch=None: [
        _fake_photo("a", ["Demo", "Kitchen"]),
    ])
    cc.pull_new_photos("1", str(dest), since_epoch=None, subfolder="Initial")
    rel = os.path.relpath(written[0], dest)
    assert rel.startswith(os.path.join("Demo", BOX, "Kitchen"))
    assert not rel.startswith("Initial")


def test_equipment_nests_inside_the_room(pull_env, monkeypatch):
    """<stage>\\<room>\\Equipment — gear shots stay WITH their room rather
    than being pulled into a stage folder of their own."""
    dest, written = pull_env
    monkeypatch.setattr(cc, "new_photos", lambda pid, since_epoch=None: [
        _fake_photo("a", ["Equipment", "Master Bath"]),
        _fake_photo("b", ["Initial Inspection", "Master Bedroom",
                          "Equipment"]),
    ])
    cc.pull_new_photos("1", str(dest), since_epoch=None, subfolder="Initial")
    rels = sorted(os.path.relpath(w, dest) for w in written)
    # No stage tag of its own → the caller's stage, then room, then Equipment
    assert rels[0].startswith(
        os.path.join("Initial", BOX, "Master Bath", "Equipment"))
    # Its own stage tag wins, and Equipment still nests under the room
    assert rels[1].startswith(
        os.path.join("Initial", BOX, "Master Bedroom", "Equipment"))


def test_untagged_photos_stay_at_the_top_rather_than_an_unsorted_bucket(
        pull_env, monkeypatch):
    dest, written = pull_env
    monkeypatch.setattr(cc, "new_photos", lambda pid, since_epoch=None: [
        _fake_photo("a", []),
    ])
    res = cc.pull_new_photos("1", str(dest), since_epoch=None)
    assert res["untagged"] == 1
    # No room and no stage — only the per-shoot box.
    assert os.path.relpath(written[0], dest).startswith(BOX + os.sep)


def test_room_nests_under_the_callers_stage_subfolder(pull_env, monkeypatch):
    """The review panel picks the stage; the room goes INSIDE it."""
    dest, written = pull_env
    monkeypatch.setattr(cc, "new_photos", lambda pid, since_epoch=None: [
        _fake_photo("a", ["Kitchen"]),
    ])
    cc.pull_new_photos("1", str(dest), since_epoch=None, subfolder="Initial")
    rel = os.path.relpath(written[0], dest)
    assert rel.startswith(os.path.join("Initial", BOX, "Kitchen"))


def test_organize_can_be_turned_off(pull_env, monkeypatch):
    dest, written = pull_env
    monkeypatch.setattr(cc, "new_photos", lambda pid, since_epoch=None: [
        _fake_photo("a", ["Kitchen"]),
    ])
    cc.pull_new_photos("1", str(dest), since_epoch=None,
                       organize_by_tags=False, tech_date_folder=False)
    assert os.sep not in os.path.relpath(written[0], dest)


def test_filename_leads_with_the_companycam_tags(pull_env, monkeypatch):
    """The photo's "true name" is its tags — the same information the zip
    export puts in the filename."""
    dest, written = pull_env
    monkeypatch.setattr(cc, "new_photos", lambda pid, since_epoch=None: [
        _fake_photo("abcdef1234", ["Initial Inspection", "Master Bath"]),
    ])
    cc.pull_new_photos("1", str(dest), since_epoch=None, tech="FB")
    name = os.path.basename(written[0])
    assert name.startswith("Initial Inspection Master Bath FB ")
    assert "abcdef12" in name, "id token must survive — it's the dedup key"
    assert "2026-" in name, "capture timestamp must survive for sorting"


def test_untagged_photo_keeps_the_cc_prefix(pull_env, monkeypatch):
    dest, written = pull_env
    monkeypatch.setattr(cc, "new_photos", lambda pid, since_epoch=None: [
        _fake_photo("abcdef1234", []),
    ])
    cc.pull_new_photos("1", str(dest), since_epoch=None, tech="FB")
    assert os.path.basename(written[0]).startswith("CC FB ")


def test_rename_does_not_re_download_already_pulled_photos(pull_env,
                                                            monkeypatch):
    """The critical migration case: photos pulled under the OLD 'CC …'
    naming must be recognized by their id token, or the first run after
    this change re-downloads the entire history."""
    dest, written = pull_env
    old = dest / "CC FB 2026-06-30 13-04-11 abcdef12.jpg"
    old.write_bytes(b"x")
    monkeypatch.setattr(cc, "new_photos", lambda pid, since_epoch=None: [
        _fake_photo("abcdef1234", ["Kitchen"]),
    ])
    res = cc.pull_new_photos("1", str(dest), since_epoch=None, tech="FB")
    assert res["downloaded"] == 0 and res["skipped"] == 1
    assert written == []


def test_retagged_photo_is_not_downloaded_twice(pull_env, monkeypatch):
    """Tags get edited in CompanyCam after the fact; a changed label must
    not read as a new photo."""
    dest, written = pull_env
    (dest / "Kitchen FB 2026-06-30 13-04-11 abcdef12.jpg").write_bytes(b"x")
    monkeypatch.setattr(cc, "new_photos", lambda pid, since_epoch=None: [
        _fake_photo("abcdef1234", ["Master Bath", "Demo"]),
    ])
    res = cc.pull_new_photos("1", str(dest), since_epoch=None, tech="FB")
    assert res["downloaded"] == 0 and res["skipped"] == 1


def test_capture_time_is_stamped_on_the_file(pull_env, monkeypatch):
    dest, written = pull_env
    ts = 1785435221
    monkeypatch.setattr(cc, "new_photos", lambda pid, since_epoch=None: [
        _fake_photo("a", ["Kitchen"], ts=ts),
    ])
    cc.pull_new_photos("1", str(dest), since_epoch=None)
    assert abs(os.path.getmtime(written[0]) - ts) < 2


# ── the tech / date box ─────────────────────────────────────────────────

def test_tech_label_uses_initials_like_the_zip_import():
    assert cc.tech_label({"creator_name": "Fernando Baca"}) == "FB"


def test_tech_label_falls_back_to_the_picked_tech():
    """CompanyCam normally knows the photographer; the picked tech is only
    a backstop for a photo with no creator."""
    assert cc.tech_label({}, "Fernando Baca") == "FB"
    assert cc.tech_label({}) == ""


def test_photo_creator_beats_the_picked_tech():
    """A mixed-crew day must attribute per photo — the zip path can't,
    because an export carries no photographer at all."""
    assert cc.tech_label({"creator_name": "Fernando Baca"}, "Someone Else") == "FB"


def test_date_label_matches_the_zip_import_format():
    assert cc.date_label({"captured_at": 1785435221}) == "07-30-2026"
    assert cc.date_label({}) == ""


def test_tech_date_box_shape():
    p = {"creator_name": "Fernando Baca", "captured_at": 1785435221}
    assert cc.tech_date_box(p) == "FB 07-30-2026"
    assert cc.tech_date_box({"captured_at": 1785435221}) == "07-30-2026"
    assert cc.tech_date_box({}) == ""


def test_two_techs_same_day_get_separate_boxes(pull_env, monkeypatch):
    """The reason this is derived per photo rather than per batch."""
    dest, written = pull_env
    monkeypatch.setattr(cc, "new_photos", lambda pid, since_epoch=None: [
        _fake_photo("a", ["Kitchen"], who="Fernando Baca"),
        _fake_photo("b", ["Kitchen"], who="Jose  Estrella"),
    ])
    res = cc.pull_new_photos("1", str(dest), since_epoch=None,
                             subfolder="Initial")
    assert len(res["boxes"]) == 2, res["boxes"]
    rels = sorted(os.path.relpath(w, dest) for w in written)
    assert rels[0] != rels[1]


def test_tech_date_box_can_be_turned_off(pull_env, monkeypatch):
    dest, written = pull_env
    monkeypatch.setattr(cc, "new_photos", lambda pid, since_epoch=None: [
        _fake_photo("a", ["Kitchen"]),
    ])
    cc.pull_new_photos("1", str(dest), since_epoch=None, subfolder="Initial",
                       tech_date_folder=False)
    assert os.path.relpath(written[0], dest).startswith(
        os.path.join("Initial", "Kitchen"))
