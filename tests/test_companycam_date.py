"""CompanyCam import must date folders by the photo CAPTURE date, not the
zip's export/download date (which is usually today).

Regression: every import was landing in a "today" folder because the date
came from the zip name (export date) instead of the photo filename stamp."""
import os
import zipfile

import companycam_import as cc


def _zip(path, names):
    with zipfile.ZipFile(path, "w") as z:
        for n in names:
            z.writestr(n, b"x")
    return str(path)


def test_photo_capture_date_beats_zip_export_date(tmp_path):
    # Zip NAMED with a July export date; photos SHOT in June.
    zp = _zip(tmp_path / "photos-2026-07-01-abc123.zip", [
        "Proj/Kitchen Post-1-Jun 17 2026 05_08pm-GJrY.jpg",
        "Proj/Garage-2-Jun 17 2026 05_12pm-Hh2Q.jpg",
    ])
    assert cc.date_from_zip_name(os.path.basename(zp)) == "2026-07-01"
    assert cc.date_from_photos(zp) == "2026-06-17"


def test_most_common_capture_date_wins(tmp_path):
    zp = _zip(tmp_path / "photos-2026-07-01-x.zip", [
        "P/a-1-Jun 17 2026 01_00pm-AA.jpg",
        "P/b-2-Jun 17 2026 01_05pm-BB.jpg",
        "P/c-3-Jun 18 2026 09_00am-CC.jpg",
    ])
    assert cc.date_from_photos(zp) == "2026-06-17"


def test_no_parseable_stamp_returns_blank(tmp_path):
    zp = _zip(tmp_path / "photos-2026-07-01-x.zip", ["P/plain.jpg"])
    assert cc.date_from_photos(zp) == ""


def test_untagged_photo_capture_date(tmp_path):
    # Fully-untagged CompanyCam name: "<N>-<date>-<rand>.jpg"
    zp = _zip(tmp_path / "photos-2026-07-01-x.zip",
              ["P/1-Jun 20 2026 05_08pm-GJrY.jpg"])
    assert cc.date_from_photos(zp) == "2026-06-20"


# ── File-metadata timestamping from the filename ───────────────────────
import datetime  # noqa: E402


def test_capture_datetime_parses_stamp():
    assert cc.capture_datetime("Demo-1-Jun 30 2026 01_04pm-j78D.jpg") == \
        datetime.datetime(2026, 6, 30, 13, 4)
    assert cc.capture_datetime("Kitchen Post-10-Jul 1 2026 09_00am-AB.jpg") == \
        datetime.datetime(2026, 7, 1, 9, 0)
    assert cc.capture_datetime("no stamp here.jpg") is None


def test_retime_folder_sets_mtime(tmp_path):
    d = tmp_path / "Robert 06-30-2026"
    d.mkdir()
    f = d / "Demo-1-Jun 30 2026 01_04pm-j78D.jpg"
    f.write_bytes(b"x")
    assert cc.retime_folder(str(tmp_path)) == 1
    assert datetime.datetime.fromtimestamp(os.path.getmtime(f)) == \
        datetime.datetime(2026, 6, 30, 13, 4)


def test_import_stamps_capture_time(tmp_path):
    zp = _zip(tmp_path / "photos-2026-07-01-x.zip",
              ["P/Demo-1-Jun 30 2026 01_04pm-AA.jpg"])
    pics = tmp_path / "PICS"
    pics.mkdir()
    cc.import_zip(zp, str(pics), force_subfolder="Demo")
    written = None
    for root, _dirs, files in os.walk(str(pics)):
        for f in files:
            written = os.path.join(root, f)
    assert written is not None
    assert datetime.datetime.fromtimestamp(os.path.getmtime(written)) == \
        datetime.datetime(2026, 6, 30, 13, 4)
