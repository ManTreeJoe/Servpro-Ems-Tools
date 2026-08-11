"""The pull preview must name the folder the download actually uses.

`route_photo` exists so the preview and the download cannot disagree —
"a preview that shows a different folder than the download uses is worse
than no preview". `plan_pull` threw that away for multi-room shoots: it
took `target` from whichever photo happened to be FIRST in the group,
room included, so Kavuri's 66 photos previewed as
"Initial\\FB 07-22-2026\\Downstairs" while 31 of them were routed to
Kitchen.

Shoots are grouped by (stage, tech-date box); the room is a subfolder
WITHIN a shoot. So target is the shared prefix and the rooms are listed
separately with counts.
"""
import os

import pytest

import companycam_api as cc


def _epoch(y, m, d):
    """Local-midnight epoch. date_label uses fromtimestamp(), which is
    LOCAL, so a UTC-built stamp would shift the folder name by a day for
    anyone west of Greenwich."""
    import datetime as _dt
    return int(_dt.datetime(y, m, d, 12, 0).timestamp())


def _photo(pid, room, stage="Initial", creator="Fernando Baca",
           when=None):
    return {
        "id": pid,
        # date_label reads captured_at, a Unix timestamp — not created_at.
        "captured_at": when if when is not None else _epoch(2026, 7, 22),
        "creator_name": creator,
        "uris": [{"type": "original", "uri": f"http://x/{pid}.jpg"}],
        # classify_tags takes plain STRINGS. The API returns tag objects
        # and attach_tags flattens them; these tests stub attach_tags out,
        # so the fixture has to supply the flattened form.
        "tags": [room, stage],
    }


@pytest.fixture
def planned(monkeypatch, tmp_path):
    """A single shoot whose photos span three rooms."""
    photos = ([_photo(f"a{i}", "Kitchen") for i in range(31)]
              + [_photo(f"b{i}", "Downstairs") for i in range(20)]
              + [_photo(f"c{i}", "Bathroom 1") for i in range(15)])
    monkeypatch.setattr(cc, "list_project_photos", lambda *a, **k: photos)
    monkeypatch.setattr(cc, "attach_tags", lambda ph, **k: ph)
    return cc.plan_pull("proj", str(tmp_path))


def test_target_is_the_shared_prefix_not_one_room(planned):
    assert planned["ok"]
    g = planned["groups"][0]
    assert g["target"] == os.path.join("Initial", "FB 07-22-2026")


def test_target_never_names_a_room(planned):
    g = planned["groups"][0]
    for room in ("Kitchen", "Downstairs", "Bathroom 1"):
        assert room not in g["target"], (
            f"target {g['target']!r} names one room out of several")


def test_every_room_is_reported_with_its_count(planned):
    g = planned["groups"][0]
    assert dict(g["rooms"]) == {"Kitchen": 31, "Downstairs": 20,
                                "Bathroom 1": 15}
    assert sum(n for _, n in g["rooms"]) == g["count"] == 66


def test_rooms_are_ordered_biggest_first(planned):
    counts = [n for _, n in planned["groups"][0]["rooms"]]
    assert counts == sorted(counts, reverse=True)


def test_the_prefix_matches_what_route_photo_would_build(planned):
    """The actual contract: whatever the download does, the preview says.
    route_photo's parts are stage, box, room, qualifier — so the shared
    prefix is exactly its first two."""
    p = _photo("a0", "Kitchen")
    r = cc.route_photo(p, tech_date_folder=True)
    expected = os.path.join(*[x for x in (r["stage"], r["box"]) if x])
    assert planned["groups"][0]["target"] == expected
    # and the room the preview omits is the third part
    assert r["parts"][:2] == [r["stage"], r["box"]]
    assert r["room"] == "Kitchen"


def test_one_room_shoot_is_unchanged(monkeypatch, tmp_path):
    monkeypatch.setattr(cc, "list_project_photos",
                        lambda *a, **k: [_photo("a1", "Kitchen")])
    monkeypatch.setattr(cc, "attach_tags", lambda ph, **k: ph)
    g = cc.plan_pull("proj", str(tmp_path))["groups"][0]
    assert g["target"] == os.path.join("Initial", "FB 07-22-2026")
    assert dict(g["rooms"]) == {"Kitchen": 1}


def test_untagged_photos_still_group(monkeypatch, tmp_path):
    """A shoot with no stage tag is the common case and still needs a
    box to file under."""
    p = {"id": "z1", "captured_at": _epoch(2026, 7, 22),
         "creator_name": "Fernando Baca",
         "uris": [{"type": "original", "uri": "http://x/z.jpg"}], "tags": []}
    monkeypatch.setattr(cc, "list_project_photos", lambda *a, **k: [p])
    monkeypatch.setattr(cc, "attach_tags", lambda ph, **k: ph)
    g = cc.plan_pull("proj", str(tmp_path))["groups"][0]
    assert g["stage"] == "(no stage tag)"
    assert "FB 07-22-2026" in g["target"]


def test_separate_shoots_stay_separate(monkeypatch, tmp_path):
    """Grouping is (stage, box) — two techs on two days is four shoots,
    not one. This is the whole reason the dialog divides at all."""
    photos = [
        _photo("a", "Kitchen", "Initial", "Fernando Baca", _epoch(2026, 7, 22)),
        _photo("b", "Kitchen", "Demo", "Fernando Baca", _epoch(2026, 7, 22)),
        _photo("c", "Kitchen", "Initial", "Mark Escobar", _epoch(2026, 7, 23)),
    ]
    monkeypatch.setattr(cc, "list_project_photos", lambda *a, **k: photos)
    monkeypatch.setattr(cc, "attach_tags", lambda ph, **k: ph)
    groups = cc.plan_pull("proj", str(tmp_path))["groups"]
    assert len(groups) == 3
    assert len({g["target"] for g in groups}) == 3
