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
def test_api_and_zip_classify_the_same_tags_identically(tags, zip_name):
    """One job pulled both ways must land in ONE folder layout."""
    assert cc.classify_tags(tags) == ci.parse_room_stage(zip_name)


@pytest.mark.parametrize("tags,room,stage", [
    (["Exterior", "Initial Inspection"], "Exterior", "Initial"),
    (["Attic"],                          "Attic", ""),
    ([],                                 "", ""),
    (["", None],                         "", ""),
])
def test_classify_real_account_tag_combinations(tags, room, stage):
    assert cc.classify_tags(tags) == (room, stage)


@pytest.mark.parametrize("tag,stage", [
    ("Monitor",   "Monitor"),
    ("Equipment", "Equipment"),
])
def test_monitor_and_equipment_are_stages_on_both_paths(tag, stage):
    """Reconciled 2026-07-30. These are real stages and real CompanyCam
    tags, but `_STAGE_RULES` didn't know them — so the same word became a
    ROOM folder from CompanyCam and a STAGE folder from Workcenter."""
    import import_grouping as ig
    assert ci.room_stage_from_label(tag)[1] == stage
    assert (ig.detect_stage(tag) or "") == stage
    assert cc.classify_tags([tag]) == ("", stage)


def test_monitor_and_equipment_still_split_room_from_stage():
    assert cc.classify_tags(["Master Bath", "Monitor"]) == ("Master Bath",
                                                            "Monitor")
    assert cc.classify_tags(["Equipment", "Master Bath"]) == ("Master Bath",
                                                              "Equipment")


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
    monkeypatch.setattr(cc, "photo_tags", lambda pid: ["Attic"])
    photos = [{"id": "a"}, {"id": "b"}]
    cc.attach_tags(photos)
    assert [p["tags"] for p in photos] == [["Attic"], ["Attic"]]


def test_attach_tags_respects_the_cap(monkeypatch):
    """An accidental full-history pull must not spend thousands of calls
    against the 240/min budget."""
    seen = []

    def fake(pid):
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

def _fake_photo(pid, tags, ts=1785435221):
    return {"id": pid, "captured_at": ts, "original_url": f"http://x/{pid}.jpg",
            "tags": tags}


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


def test_pull_files_photos_under_their_room(pull_env, monkeypatch):
    dest, written = pull_env
    monkeypatch.setattr(cc, "new_photos", lambda pid, since_epoch=None: [
        _fake_photo("a", ["Kitchen", "Demo"]),
        _fake_photo("b", ["Master Bath"]),
    ])
    res = cc.pull_new_photos("1", str(dest), since_epoch=None)
    assert res["ok"] and res["downloaded"] == 2
    rels = sorted(os.path.relpath(w, dest) for w in written)
    assert rels[0].startswith("Kitchen" + os.sep)
    assert rels[1].startswith("Master Bath" + os.sep)
    assert res["rooms"] == {"Kitchen": 1, "Master Bath": 1}


def test_untagged_photos_stay_at_the_top_rather_than_an_unsorted_bucket(
        pull_env, monkeypatch):
    dest, written = pull_env
    monkeypatch.setattr(cc, "new_photos", lambda pid, since_epoch=None: [
        _fake_photo("a", []),
    ])
    res = cc.pull_new_photos("1", str(dest), since_epoch=None)
    assert res["untagged"] == 1
    assert os.sep not in os.path.relpath(written[0], dest)


def test_room_nests_under_the_callers_stage_subfolder(pull_env, monkeypatch):
    """The review panel picks the stage; the room goes INSIDE it."""
    dest, written = pull_env
    monkeypatch.setattr(cc, "new_photos", lambda pid, since_epoch=None: [
        _fake_photo("a", ["Kitchen"]),
    ])
    cc.pull_new_photos("1", str(dest), since_epoch=None, subfolder="Initial")
    rel = os.path.relpath(written[0], dest)
    assert rel.startswith(os.path.join("Initial", "Kitchen"))


def test_organize_can_be_turned_off(pull_env, monkeypatch):
    dest, written = pull_env
    monkeypatch.setattr(cc, "new_photos", lambda pid, since_epoch=None: [
        _fake_photo("a", ["Kitchen"]),
    ])
    cc.pull_new_photos("1", str(dest), since_epoch=None,
                       organize_by_tags=False)
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
