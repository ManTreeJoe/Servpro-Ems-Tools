"""CompanyCam photo tags survive the process.

Tags come from /photos/{id}/tags — one call per photo, no bulk form (the
project photo list carries no tags). A job with 194 missing photos is 194
requests, and at 240 GET/min that's ~48s of budget however many threads
you use. Held only in memory, that was paid again on every app restart
and every department switch for answers that hadn't changed.
"""
import json

import pytest

import companycam_api as cc


@pytest.fixture
def api(tmp_path, monkeypatch):
    """Isolated sidecar + a counting stub for the tag endpoint."""
    calls = []

    def _fake_call(path, **kw):
        calls.append(path)
        pid = path.split("/")[2]
        if pid == "untagged":
            return []
        return [{"display_value": "Initial"}, {"display_value": "Kitchen"}]

    monkeypatch.setattr(cc, "_call", _fake_call)
    monkeypatch.setattr(cc, "_tag_disk_path",
                        lambda: str(tmp_path / "tags.json"))
    cc._TAG_CACHE.clear()
    cc._TAG_DISK = None
    cc._TAG_DISK_DIRTY = 0
    yield cc, calls, tmp_path
    cc._TAG_CACHE.clear()
    cc._TAG_DISK = None
    cc._TAG_DISK_DIRTY = 0


def test_first_lookup_hits_the_api(api):
    cc_, calls, _ = api
    assert cc_.photo_tags("p1") == ["Initial", "Kitchen"]
    assert calls == ["/photos/p1/tags"]


def test_second_lookup_in_the_same_run_does_not(api):
    cc_, calls, _ = api
    cc_.photo_tags("p1")
    cc_.photo_tags("p1")
    assert len(calls) == 1


def test_a_new_process_reads_the_sidecar_instead_of_the_api(api):
    """The actual win: reopening the job costs no requests."""
    cc_, calls, _ = api
    cc_.photo_tags("p1")
    cc_.flush_tag_cache()
    # Simulate a restart — memory gone, sidecar on disk.
    cc_._TAG_CACHE.clear()
    cc_._TAG_DISK = None
    calls.clear()
    assert cc_.photo_tags("p1") == ["Initial", "Kitchen"]
    assert calls == [], "restart should not re-fetch a known photo"


def test_a_batch_of_many_photos_costs_one_call_each_then_none(api):
    cc_, calls, _ = api
    photos = [{"id": f"p{i}"} for i in range(30)]
    cc_.attach_tags(photos)
    assert len(calls) == 30
    cc_._TAG_CACHE.clear()
    cc_._TAG_DISK = None
    calls.clear()
    cc_.attach_tags([{"id": f"p{i}"} for i in range(30)])
    assert calls == [], "second look at the same shoot should be free"


def test_untagged_photos_are_not_persisted(api):
    """A photo with no tags is usually one nobody has tagged YET — techs
    tag late, and suggest-a-stage exists because shoots arrive untagged.
    Persisting the empty answer would freeze them as untagged forever."""
    cc_, calls, tmp_path = api
    assert cc_.photo_tags("untagged") == []
    cc_.flush_tag_cache()
    saved = json.loads((tmp_path / "tags.json").read_text(encoding="utf-8")) \
        if (tmp_path / "tags.json").exists() else {}
    assert "untagged" not in saved


def test_untagged_still_cached_in_memory_for_this_run(api):
    cc_, calls, _ = api
    cc_.photo_tags("untagged")
    cc_.photo_tags("untagged")
    assert len(calls) == 1


def test_invalidate_keeps_the_sidecar(api):
    """cache_bust clears this on every department switch. A photo id is
    unique to its company, so another token's entries are simply never
    asked for — re-fetching them would cost the 48s this exists to
    avoid."""
    cc_, calls, _ = api
    cc_.photo_tags("p1")
    cc_.flush_tag_cache()
    cc_.invalidate_tag_cache()
    calls.clear()
    assert cc_.photo_tags("p1") == ["Initial", "Kitchen"]
    assert calls == []


def test_a_corrupt_sidecar_costs_a_refetch_not_a_crash(api):
    cc_, calls, tmp_path = api
    (tmp_path / "tags.json").write_text("{not json", encoding="utf-8")
    cc_._TAG_DISK = None
    assert cc_.photo_tags("p1") == ["Initial", "Kitchen"]
    assert calls == ["/photos/p1/tags"]


def test_blank_id_asks_nothing(api):
    cc_, calls, _ = api
    assert cc_.photo_tags("") == []
    assert cc_.photo_tags(None) == []
    assert calls == []


def test_flush_without_changes_writes_nothing(api):
    cc_, _calls, tmp_path = api
    cc_._tag_disk_load()
    cc_.flush_tag_cache()
    assert not (tmp_path / "tags.json").exists()
