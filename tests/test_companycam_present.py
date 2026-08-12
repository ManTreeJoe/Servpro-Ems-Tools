"""Photos already on disk must stop coming back pre-checked.

Files pulled before the id-truncation fix carry an 8-character prefix.
When two CompanyCam ids share that prefix the old rule gave up and called
BOTH missing — which never resolved, so the same shoot came back on every
pull and each pull added another copy. Real case: Ochoa's six Initial
photos, three colliding pairs, all six already filed.

Capture time is the tiebreak: pulled filenames already embed it.
"""

import datetime as dt

import companycam_api as cc


def _p(pid, when=None):
    """A photo dict with an id and (optionally) a capture time."""
    d = {"id": str(pid)}
    if when is not None:
        d["captured_at"] = int(dt.datetime.strptime(
            when, "%Y-%m-%d %H-%M-%S").timestamp())
    return d


def _stamps(*whens):
    return set(whens)


# ── the plain cases still work ──────────────────────────────────────

def test_full_id_on_disk_is_present():
    photos = [_p("3446396888")]
    assert cc._present_tokens(photos, {"3446396888"}) == {"3446396888"}


def test_nothing_on_disk_is_missing():
    photos = [_p("3446396888")]
    assert cc._present_tokens(photos, set()) == set()


def test_a_unique_legacy_prefix_still_matches():
    # One photo, 8-char token on disk — the pre-existing behaviour.
    photos = [_p("3446396888")]
    assert cc._present_tokens(photos, {"34463968"}) == {"3446396888"}


# ── the collision, which is the bug ─────────────────────────────────

COLLIDE = ["3446396888", "3446396810"]   # both truncate to "34463968"


def test_colliding_prefixes_alone_are_still_treated_as_missing():
    # Without capture times there is genuinely no way to tell them apart,
    # and re-downloading a duplicate beats skipping a photo.
    photos = [_p(i) for i in COLLIDE]
    assert cc._present_tokens(photos, {"34463968"}) == set()


def test_capture_time_resolves_a_collision():
    photos = [_p(COLLIDE[0], "2026-08-06 11-44-21"),
              _p(COLLIDE[1], "2026-08-06 11-44-06")]
    stamps = _stamps("2026-08-06 11-44-21", "2026-08-06 11-44-06")
    assert cc._present_tokens(photos, {"34463968"}, stamps) == set(COLLIDE)


def test_only_the_half_of_a_collision_thats_on_disk_counts():
    photos = [_p(COLLIDE[0], "2026-08-06 11-44-21"),
              _p(COLLIDE[1], "2026-08-06 11-44-06")]
    stamps = _stamps("2026-08-06 11-44-21")          # only the first filed
    got = cc._present_tokens(photos, {"34463968"}, stamps)
    assert got == {COLLIDE[0]}


# ── the guard that keeps this safe ──────────────────────────────────

def test_two_photos_sharing_a_second_are_not_matched_by_time():
    # A burst can put two DIFFERENT photos in the same second. Matching
    # then risks skipping one that was never pulled, which is the one
    # unrecoverable outcome — so it errs toward re-downloading.
    photos = [_p(COLLIDE[0], "2026-08-06 11-44-21"),
              _p(COLLIDE[1], "2026-08-06 11-44-21")]
    stamps = _stamps("2026-08-06 11-44-21")
    assert cc._present_tokens(photos, {"34463968"}, stamps) == set()


def test_a_photo_with_no_capture_time_is_never_matched_by_time():
    photos = [_p(COLLIDE[0]), _p(COLLIDE[1])]
    assert cc._present_tokens(photos, {"34463968"}, _stamps("x")) == set()


def test_a_stamp_on_disk_for_a_photo_thats_genuinely_new_is_ignored():
    # Same second on disk, but this photo's full id is unknown to the
    # folder and its prefix doesn't collide — the prefix rule already
    # answers it, and it must not be dragged in by a coincidental stamp.
    photos = [_p("9999999999", "2026-08-06 11-44-21")]
    got = cc._present_tokens(photos, set(), _stamps("2026-08-06 11-44-21"))
    assert got == {"9999999999"}      # unique stamp, on disk → present


# ── the filename helpers agree ──────────────────────────────────────

def test_capture_stamp_matches_the_filename_format():
    p = _p("1", "2026-08-06 11-44-21")
    stamp = cc.capture_stamp(p)
    assert stamp == "2026-08-06 11-44-21"
    # and the scanner finds that exact form in a real pulled name
    name = f"CC Fernando Baca {stamp} 34463968.jpg"
    assert cc._STAMP_RE.search(name).group(1) == stamp


def test_capture_stamp_survives_junk():
    assert cc.capture_stamp({}) == ""
    assert cc.capture_stamp({"captured_at": None}) == ""
    assert cc.capture_stamp({"captured_at": "not-a-time"}) == ""


def test_stamps_on_disk_reads_nested_folders(tmp_path):
    d = tmp_path / "PICS" / "Initial" / "FB 08-06-2026"
    d.mkdir(parents=True)
    (d / "CC Fernando Baca 2026-08-06 11-44-21 34463968.jpg").write_text("x")
    (d / "not-a-photo.txt").write_text("x")
    got = cc._capture_stamps_on_disk(str(tmp_path))
    assert got == {"2026-08-06 11-44-21"}
