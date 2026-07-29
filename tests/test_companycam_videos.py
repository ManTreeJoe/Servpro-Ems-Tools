"""CompanyCam import routes video clips into a Videos subfolder.

User rule (2026-07-01): videos ride along with SP / CompanyCam imports but
land in a "Videos" subfolder of the same stage container instead of the photo
grid. Previously non-image files were dropped entirely."""
import os
import zipfile

import companycam_import as cc


def _zip(tmp_path, files):
    zpath = tmp_path / "proj.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return str(zpath)


def test_video_lands_in_videos_subfolder(tmp_path):
    zpath = _zip(tmp_path, {
        "proj/photo.jpg": b"img",
        "proj/clip.mp4": b"vid",
    })
    pics = tmp_path / "PICS"
    pics.mkdir()
    cc.import_zip(zpath, str(pics), force_subfolder="Demo")
    assert (pics / "Demo" / "photo.jpg").is_file()
    assert (pics / "Demo" / "Videos" / "clip.mp4").is_file()
    # The clip must NOT sit flat next to the photos.
    assert not (pics / "Demo" / "clip.mp4").exists()


def test_multiple_video_extensions(tmp_path):
    zpath = _zip(tmp_path, {
        "proj/a.mov": b"v", "proj/b.m4v": b"v", "proj/c.avi": b"v",
        "proj/e.mkv": b"v", "proj/f.3gp": b"v", "proj/g.webm": b"v",
        "proj/d.png": b"i",
    })
    pics = tmp_path / "PICS"
    pics.mkdir()
    cc.import_zip(zpath, str(pics), force_subfolder="Post")
    vids = pics / "Post" / "Videos"
    for n in ("a.mov", "b.m4v", "c.avi", "e.mkv", "f.3gp", "g.webm"):
        assert (vids / n).is_file(), n
    assert (pics / "Post" / "d.png").is_file()


def test_videos_still_imported_not_dropped(tmp_path):
    """Regression: a video-only export must not silently import nothing."""
    zpath = _zip(tmp_path, {"proj/only.mp4": b"vid"})
    pics = tmp_path / "PICS"
    pics.mkdir()
    cc.import_zip(zpath, str(pics), force_subfolder="Demo")
    assert (pics / "Demo" / "Videos" / "only.mp4").is_file()
