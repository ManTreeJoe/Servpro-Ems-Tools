"""CompanyCam import per-batch room rule (user, 2026-06-19):
  • all photos share ONE room, or have NO room label → land FLAT in the
    stage container (no per-room and no per-photo subfolders).
  • 2+ distinct rooms → organize into per-room subfolders.

Regression: the Montebello Eric EQ folder got 14 single-photo subfolders
because fully-untagged photos ("1-Jun 17 2026 05_08pm-GJrY.jpg") were
read as having a unique room. Untagged photos must now flatten.
"""
import zipfile
import companycam_import as cc


def _make_zip(tmp_path, names, project="Eric Montebello"):
    z = tmp_path / "photos-2026-06-17-zzzz.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for n in names:
            zf.writestr(f"{project}/{n}", b"\xff\xd8\xff\xe0")  # fake jpg
    return str(z)


def test_untagged_photos_flatten_into_forced_stage(tmp_path):
    # The EQ case: fully-untagged photos, forced into "EQ". They must land
    # directly in PICS/EQ — not in a subfolder per photo.
    pics = tmp_path / "PICS"
    pics.mkdir()
    z = _make_zip(tmp_path, [
        "1-Jun 17 2026 05_08pm-GJrY.jpg",
        "2-Jun 17 2026 05_08pm-qzUH.jpg",
        "3-Jun 17 2026 05_09pm-m2wN.jpg",
    ])
    cc.import_zip(z, str(pics), date_label="06-17-2026", force_subfolder="EQ")
    eq = pics / "EQ"
    assert eq.is_dir()
    jpgs = sorted(p.name for p in eq.glob("*.jpg"))
    assert len(jpgs) == 3                       # all three photos, flat
    assert not any(p.is_dir() for p in eq.iterdir())   # no subfolders


def test_same_single_room_flattens(tmp_path):
    # Every photo is the same room ("Kitchen") under Demo → no Kitchen
    # subfolder; photos land flat in PICS/Demo.
    pics = tmp_path / "PICS"
    pics.mkdir()
    z = _make_zip(tmp_path, [
        "Kitchen Demo-1-Jun 17 2026 10_00am-aa.jpg",
        "Kitchen Demo-2-Jun 17 2026 10_01am-bb.jpg",
    ])
    cc.import_zip(z, str(pics), date_label="06-17-2026")
    demo = pics / "Demo"
    assert demo.is_dir()
    assert not (demo / "Kitchen").exists()
    assert len(sorted(demo.glob("*.jpg"))) == 2


def test_distinct_rooms_still_organize(tmp_path):
    # 2+ rooms under one stage → per-room subfolders (organize).
    pics = tmp_path / "PICS"
    pics.mkdir()
    z = _make_zip(tmp_path, [
        "Kitchen Demo-1-Jun 17 2026 10_00am-aa.jpg",
        "Garage Demo-2-Jun 17 2026 10_01am-bb.jpg",
    ])
    cc.import_zip(z, str(pics), date_label="06-17-2026")
    assert (pics / "Demo" / "Kitchen").is_dir()
    assert (pics / "Demo" / "Garage").is_dir()


def test_fully_untagged_parse_returns_no_room():
    # The parse helper itself must not treat the numbering stamp as a room.
    room, stage = cc.parse_room_stage("1-Jun 17 2026 05_08pm-GJrY.jpg")
    assert room == ""
    assert stage == ""
