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


# ── per-shoot stage assignment ────────────────────────────────────────
# A project's photos are often untagged (Gary Mongue: 181 photos, zero
# tags, eight shoots by six techs across six dates). One stage for the
# whole project is wrong for every job with more than one visit, so each
# shoot carries its own destination.

def test_untagged_photos_group_by_tech_and_day(monkeypatch):
    """With no tags at all, the shoot is still recoverable: CompanyCam
    knows who took each photo and when."""
    photos = [
        _photo("a1", DAY1, "Maria Espinoza", []),
        _photo("a2", DAY1, "Maria Espinoza", []),
        _photo("a3", DAY1, "Jose Estrada", []),      # same day, other tech
        _photo("a4", DAY2, "Maria Espinoza", []),    # same tech, next day
    ]
    monkeypatch.setattr(cc, "list_project_photos", lambda pid: photos)
    monkeypatch.setattr(cc, "_id_tokens_on_disk", lambda d: set())
    monkeypatch.setattr(cc.os.path, "isdir", lambda d: True)

    r = cc.plan_pull("1", r"X:\job\PICS")
    assert len(r["groups"]) == 3          # ME day1, JE day1, ME day2
    assert all(g["stage"] == "" or g["stage"] == "(no stage tag)"
               for g in r["groups"])
    counts = sorted(g["count"] for g in r["groups"])
    assert counts == [1, 1, 2]


def test_each_untagged_shoot_can_take_a_different_stage(monkeypatch):
    """The whole point: pulling one visit as Demo and another as Monitor
    in a single pass."""
    photos = [_photo("a1", DAY1, "ME", []), _photo("a2", DAY2, "ME", [])]
    monkeypatch.setattr(cc, "list_project_photos", lambda pid: photos)
    monkeypatch.setattr(cc, "_id_tokens_on_disk", lambda d: set())
    monkeypatch.setattr(cc.os.path, "isdir", lambda d: True)

    plan = cc.plan_pull("1", r"X:\job\PICS")
    ids = {g["date"]: g["photo_ids"] for g in plan["groups"]}
    assert len(ids) == 2

    # Routing each with its own stage puts them in different folders.
    a = cc.route_photo(photos[0], subfolder="Demo", tech="ME")
    b = cc.route_photo(photos[1], subfolder="Monitor", tech="ME")
    assert a["parts"][0] == "Demo"
    assert b["parts"][0] == "Monitor"


def test_a_tagged_shoot_keeps_its_own_stage_over_the_fallback(monkeypatch):
    """A dropdown must never override what CompanyCam already knows."""
    p = _photo("a1", DAY1, "ME", ["Kitchen", "Demo"])
    r = cc.route_photo(p, subfolder="Initial", tech="ME")
    assert r["stage"] == "Demo"


# ── tags must actually be loaded, and the tech must be overridable ────

def test_plan_loads_tags_before_grouping(monkeypatch):
    """Tags come from a SEPARATE per-photo call, so a photo list alone
    carries none. Without fetching them the plan showed every shoot as
    "(no stage tag)" on jobs CompanyCam HAD tagged — the preview claiming
    a job was untagged when it wasn't. Caught on Gary Mongue: 6 of his 9
    shoots are tagged Post / Demo / Monitor."""
    photos = [_photo("a1", DAY1, "ME", None), _photo("a2", DAY2, "ME", None)]
    monkeypatch.setattr(cc, "list_project_photos", lambda pid: photos)
    monkeypatch.setattr(cc, "_id_tokens_on_disk", lambda d: set())
    monkeypatch.setattr(cc.os.path, "isdir", lambda d: True)
    monkeypatch.setattr(
        cc, "photo_tags",
        lambda pid, updated_at="": ["Demo"] if pid == "a1" else ["Monitor"])

    r = cc.plan_pull("1", r"X:\job\PICS")
    stages = sorted(g["stage"] for g in r["groups"])
    assert stages == ["Demo", "Monitor"]


def test_a_broken_tag_fetch_still_produces_a_plan(monkeypatch):
    """Untagged routing is a worse plan, not a broken one."""
    photos = [_photo("a1", DAY1, "ME", None)]
    monkeypatch.setattr(cc, "list_project_photos", lambda pid: photos)
    monkeypatch.setattr(cc, "_id_tokens_on_disk", lambda d: set())
    monkeypatch.setattr(cc.os.path, "isdir", lambda d: True)
    monkeypatch.setattr(cc, "attach_tags",
                        lambda ps, **kw: (_ for _ in ()).throw(OSError("down")))
    r = cc.plan_pull("1", r"X:\job\PICS")
    assert r["ok"] and len(r["groups"]) == 1


def test_creator_wins_by_default():
    """A mixed-crew day should attribute per photo, not per batch."""
    p = _photo("a1", DAY1, "Fernando Baca", [])
    assert cc.route_photo(p, tech="ML")["box"].startswith("FB ")


def test_a_typed_tech_overrides_the_creator():
    """CompanyCam's creator is whoever's phone took the shot — not always
    who the folder should be filed under."""
    p = _photo("a1", DAY1, "Fernando Baca", [])
    assert cc.route_photo(p, tech="ML", force_tech=True)["box"].startswith("ML ")


def test_forcing_an_empty_tech_falls_back_to_the_creator():
    """Clearing the box must not produce a nameless folder."""
    p = _photo("a1", DAY1, "Fernando Baca", [])
    assert cc.route_photo(p, tech="", force_tech=True)["box"].startswith("FB ")


# ── id collisions: "we already have it" when we don't ─────────────────
# Tokens used to be the id truncated to 8 chars, but live ids are 10
# digits. On Gary Mongue 181 photos collapsed to 160 distinct tokens, so
# verify reported "present 181, missing 0" while 37 photos had never been
# downloaded — the failure was silent AND the dangerous way round.

def test_ids_that_share_a_prefix_are_distinguishable():
    a, b = {"id": "3415908719"}, {"id": "3415908711"}
    assert cc.photo_id_token(a) != cc.photo_id_token(b)


def test_a_photo_is_not_called_present_because_a_sibling_shares_its_prefix(
        monkeypatch):
    """The exact live failure: one file on disk, two photos whose ids share
    an 8-char prefix. Neither may be assumed present."""
    photos = [{"id": "3415908719", "captured_at": DAY1},
              {"id": "3415908711", "captured_at": DAY1}]
    monkeypatch.setattr(cc, "list_project_photos", lambda pid: photos)
    monkeypatch.setattr(cc, "_id_tokens_on_disk", lambda d: {"34159087"})
    monkeypatch.setattr(cc.os.path, "isdir", lambda d: True)

    v = cc.verify_project("1", r"X:\job")
    assert v["present"] == 0
    assert v["missing"] == 2


def test_a_legacy_filename_still_counts_as_present(monkeypatch):
    """Files pulled before the fix carry an 8-char name. Requiring a full
    id would call every one of them missing and re-download the lot."""
    photos = [{"id": "3410341012", "captured_at": DAY1}]
    monkeypatch.setattr(cc, "list_project_photos", lambda pid: photos)
    monkeypatch.setattr(cc, "_id_tokens_on_disk", lambda d: {"34103410"})
    monkeypatch.setattr(cc.os.path, "isdir", lambda d: True)
    v = cc.verify_project("1", r"X:\job")
    assert v["present"] == 1 and v["missing"] == 0


def test_a_full_id_filename_counts_as_present(monkeypatch):
    photos = [{"id": "3410341012", "captured_at": DAY1}]
    monkeypatch.setattr(cc, "list_project_photos", lambda pid: photos)
    monkeypatch.setattr(cc, "_id_tokens_on_disk", lambda d: {"3410341012"})
    monkeypatch.setattr(cc.os.path, "isdir", lambda d: True)
    v = cc.verify_project("1", r"X:\job")
    assert v["present"] == 1 and v["missing"] == 0


def test_a_legacy_file_is_not_counted_as_an_orphan(monkeypatch):
    """extra_files means "deleted in CompanyCam after being pulled". An
    8-char legacy name must not be mistaken for one."""
    photos = [{"id": "3410341012", "captured_at": DAY1}]
    monkeypatch.setattr(cc, "list_project_photos", lambda pid: photos)
    monkeypatch.setattr(cc, "_id_tokens_on_disk", lambda d: {"34103410"})
    monkeypatch.setattr(cc.os.path, "isdir", lambda d: True)
    assert cc.verify_project("1", r"X:\job")["extra_files"] == 0


def test_a_failed_download_is_counted_not_swallowed(monkeypatch, tmp_path):
    """The folder is created BEFORE the download, so swallowing the error
    made a failed pull look identical to a successful one: new folders, no
    photos, no message. That is what "it says it pulled but nothing showed
    up" looked like."""
    photos = [{"id": "1111111111", "captured_at": DAY1, "creator_name": "ME",
               "original_url": "https://x/1.jpg", "processing_status": "processed",
               "tags": []}]
    monkeypatch.setattr(cc, "new_photos", lambda pid, since_epoch=None: photos)
    monkeypatch.setattr(cc, "_download",
                        lambda url, dest: (_ for _ in ()).throw(
                            OSError("connection reset")))
    r = cc.pull_new_photos("1", str(tmp_path), since_epoch=None,
                           advance_watermark=False)
    assert r["downloaded"] == 0
    assert r["failed"] == 1
    assert "connection reset" in r["error"]
