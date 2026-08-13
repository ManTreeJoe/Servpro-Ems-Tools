"""Imports bring in photos, not video.

`_IMAGE_EXTS` used to list .mp4/.mov/.m4v/.avi, so every import path that
filters on it copied clips into the PICS stage folders as though they
were photos. 34 .MOV and 2 .mp4 files are sitting in the 2026 jobs
because of it, with phone names like IMG_3007.MOV.

Two reasons that's wrong: the audit counts what's in PICS to decide
whether a stage is documented, and a walkthrough clip isn't a
documentation photo; and audit_logic's own image set never included
video, so the two disagreed about what a photo is.
"""
import pytest

import sharepoint as sp


VIDEOS = [".mp4", ".mov", ".m4v", ".avi", ".mkv", ".wmv"]
PHOTOS = [".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif"]


@pytest.mark.parametrize("ext", VIDEOS)
def test_video_is_not_an_image(ext):
    assert ext not in sp._IMAGE_EXTS


@pytest.mark.parametrize("ext", PHOTOS)
def test_photos_are_still_images(ext):
    """The point is to drop video, not to narrow what counts as a photo —
    phones produce HEIC and screenshots arrive as PNG."""
    assert ext in sp._IMAGE_EXTS


@pytest.mark.parametrize("ext", VIDEOS)
def test_video_extensions_are_named_somewhere(ext):
    """Kept as a set rather than deleted, so a caller that wants clips
    can ask for them instead of re-listing extensions by hand."""
    assert ext in sp._VIDEO_EXTS


def test_media_is_the_union(ext=None):
    assert sp._MEDIA_EXTS == sp._IMAGE_EXTS | sp._VIDEO_EXTS
    assert not (sp._IMAGE_EXTS & sp._VIDEO_EXTS), \
        "an extension must not be both"


def test_case_is_the_caller_s_job_but_the_set_is_lowercase():
    """Every caller lowercases before testing; a stray uppercase entry
    here would silently never match."""
    assert all(e == e.lower() for e in sp._IMAGE_EXTS | sp._VIDEO_EXTS)


def test_agrees_with_audit_logic_about_what_a_photo_is():
    """audit_logic decides whether a stage has photos; sharepoint decides
    what gets imported. If they disagree, a folder fills with files the
    audit then says aren't there."""
    import audit_logic
    assert not (audit_logic.IMAGE_EXTS & sp._VIDEO_EXTS)
