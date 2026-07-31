"""The pull PREVIEW: what would come in, grouped by shoot.

"142 photos missing" isn't actionable — it's usually four or five separate
visits, and you may want yesterday's demo but not a re-shoot of the
initial. plan_pull turns that into one row per (stage, tech + date) so the
choice can be made per shoot.

The load-bearing property is that the preview and the download agree about
destinations. They share `route_photo` for exactly that reason, and the
first test here is what keeps them honest.
"""
import companycam_api as cc


def _photo(pid, captured_at, who, tags):
    return {"id": pid, "captured_at": captured_at,
            "creator_name": who, "tags": tags}


# 2026-07-30 and 2026-07-31, midday UTC-ish — exact wall dates don't
# matter, only that the two land on different days.
DAY1 = 1753900000
DAY2 = DAY1 + 86400


def test_preview_and_download_agree_on_the_destination():
    """If these ever diverge, the preview is lying about where photos go —
    worse than showing no preview at all."""
    p = _photo("a1", DAY1, "Fernando Baca", ["Kitchen", "Demo", "Equipment"])
    r = cc.route_photo(p, subfolder="Initial", tech="FB")
    assert r["parts"] == ["Demo", r["box"], "Kitchen", "Equipment"]
    assert r["stage"] == "Demo"        # the photo's own tag wins
    assert r["qualifier"] == "Equipment"   # gear IN a room, not a stage


def test_untagged_photo_falls_back_to_the_chosen_stage():
    p = _photo("a2", DAY1, "Fernando Baca", [])
    r = cc.route_photo(p, subfolder="Initial", tech="FB")
    assert r["stage"] == "Initial"
    assert r["room"] == ""            # no invented "Unsorted" bucket


def test_groups_split_by_day_and_by_what_was_done(monkeypatch):
    photos = [
        _photo("a1", DAY1, "Fernando Baca", ["Kitchen", "Initial"]),
        _photo("a2", DAY1, "Fernando Baca", ["Bath", "Initial"]),
        _photo("a3", DAY2, "Fernando Baca", ["Kitchen", "Demo"]),
    ]
    monkeypatch.setattr(cc, "list_project_photos", lambda pid: photos)
    monkeypatch.setattr(cc, "_id_tokens_on_disk", lambda d: set())
    monkeypatch.setattr(cc.os.path, "isdir", lambda d: True)

    r = cc.plan_pull("1", r"X:\job\PICS")
    assert r["ok"] and r["missing"] == 3
    # Two shoots: an initial on day 1 (2 photos) and a demo on day 2.
    assert len(r["groups"]) == 2
    stages = {g["stage"]: g["count"] for g in r["groups"]}
    assert stages == {"Initial": 2, "Demo": 1}


def test_newest_shoot_is_listed_first(monkeypatch):
    """The thing you just did is the thing you're most likely pulling."""
    photos = [
        _photo("a1", DAY1, "FB", ["Initial"]),
        _photo("a2", DAY2, "FB", ["Demo"]),
    ]
    monkeypatch.setattr(cc, "list_project_photos", lambda pid: photos)
    monkeypatch.setattr(cc, "_id_tokens_on_disk", lambda d: set())
    monkeypatch.setattr(cc.os.path, "isdir", lambda d: True)
    r = cc.plan_pull("1", r"X:\job\PICS")
    assert r["groups"][0]["stage"] == "Demo"      # the later day


def test_a_group_carries_its_photo_ids_so_a_subset_can_be_pulled(monkeypatch):
    photos = [_photo("a1", DAY1, "FB", ["Initial"]),
              _photo("a2", DAY1, "FB", ["Initial"])]
    monkeypatch.setattr(cc, "list_project_photos", lambda pid: photos)
    monkeypatch.setattr(cc, "_id_tokens_on_disk", lambda d: set())
    monkeypatch.setattr(cc.os.path, "isdir", lambda d: True)
    r = cc.plan_pull("1", r"X:\job\PICS")
    assert sorted(r["groups"][0]["photo_ids"]) == ["a1", "a2"]


def test_photos_already_on_disk_are_not_offered(monkeypatch):
    """The preview is of what's MISSING; showing photos already filed would
    invite re-pulling them."""
    photos = [_photo("aaaaaaaa11", DAY1, "FB", ["Initial"]),
              _photo("bbbbbbbb22", DAY1, "FB", ["Initial"])]
    monkeypatch.setattr(cc, "list_project_photos", lambda pid: photos)
    monkeypatch.setattr(cc, "_id_tokens_on_disk",
                        lambda d: {cc.photo_id_token(photos[0]).lower()})
    monkeypatch.setattr(cc.os.path, "isdir", lambda d: True)
    r = cc.plan_pull("1", r"X:\job\PICS")
    assert r["missing"] == 1
    assert r["groups"][0]["photo_ids"] == ["bbbbbbbb22"]


def test_rooms_are_summarised_per_group(monkeypatch):
    photos = [_photo("a1", DAY1, "FB", ["Kitchen", "Initial"]),
              _photo("a2", DAY1, "FB", ["Kitchen", "Initial"]),
              _photo("a3", DAY1, "FB", ["Bath", "Initial"])]
    monkeypatch.setattr(cc, "list_project_photos", lambda pid: photos)
    monkeypatch.setattr(cc, "_id_tokens_on_disk", lambda d: set())
    monkeypatch.setattr(cc.os.path, "isdir", lambda d: True)
    r = cc.plan_pull("1", r"X:\job\PICS")
    # Busiest room first, so a glance says what the visit was about.
    assert r["groups"][0]["rooms"][0] == ("Kitchen", 2)


def test_nothing_missing_gives_no_groups(monkeypatch):
    photos = [_photo("aaaaaaaa11", DAY1, "FB", ["Initial"])]
    monkeypatch.setattr(cc, "list_project_photos", lambda pid: photos)
    monkeypatch.setattr(cc, "_id_tokens_on_disk",
                        lambda d: {cc.photo_id_token(photos[0]).lower()})
    monkeypatch.setattr(cc.os.path, "isdir", lambda d: True)
    r = cc.plan_pull("1", r"X:\job\PICS")
    assert r["ok"] and r["missing"] == 0 and r["groups"] == []
