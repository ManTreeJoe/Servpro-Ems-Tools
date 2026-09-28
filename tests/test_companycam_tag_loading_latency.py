"""Exercise the actual cold import planner with simulated provider latency."""
import threading
import time

import companycam_api as cc


def test_cold_import_does_not_pay_network_latency_serially(monkeypatch, tmp_path):
    photos = [{"id": str(i), "updated_at": "now", "creator_name": "Test Tech",
               "captured_at": 1700000000} for i in range(8)]
    monkeypatch.setattr(cc, "list_project_photos", lambda _: photos)
    monkeypatch.setattr(cc.os.path, "isdir", lambda _: False)
    monkeypatch.setattr(cc, "_TAG_CACHE", {})
    monkeypatch.setattr(cc, "_TAG_DISK", {})
    monkeypatch.setattr(cc, "_TAG_DISK_DIRTY", 0)
    monkeypatch.setattr(cc, "_tag_disk_path", lambda: str(tmp_path / "tags.json"))
    lock = threading.Lock()
    active = peak = 0
    def slow_provider(*args, **kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            time.sleep(0.5)
            return [{"display_value": "Initial"}]
        finally:
            with lock:
                active -= 1
    monkeypatch.setattr(cc, "_call", slow_provider)
    start = time.monotonic()
    result = cc.plan_pull("project", "folder")
    elapsed = time.monotonic() - start
    print(f"cold plan: {elapsed:.2f}s, peak requests: {peak}")
    assert result["missing"] == 8
    assert all("Initial" in group["current_tags"] for group in result["groups"])
    assert 1 < peak <= 4, "independent tag reads should overlap, with a bounded limit"
    assert elapsed < 3.5, "8 half-second reads must not cost four serial seconds"
