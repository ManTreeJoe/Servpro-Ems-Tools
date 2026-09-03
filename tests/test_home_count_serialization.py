import threading
import time

import home_web


def test_concurrent_sidebar_count_uses_last_snapshot(monkeypatch):
    api = object.__new__(home_web.HomeApi)
    api._counts_cache = (time.monotonic() - 120, {"pipeline": 17})
    api._counts_lock = threading.Lock()
    entered, release = threading.Event(), threading.Event()
    def slow_pass():
        entered.set()
        release.wait(timeout=2)
        return {"pipeline": 18}
    monkeypatch.setattr(api, "_compute_counts", slow_pass)
    result = []
    worker = threading.Thread(target=lambda: result.append(api.counts()))
    worker.start()
    assert entered.wait(timeout=1)
    assert api.counts() == {"pipeline": 17}
    release.set()
    worker.join(timeout=2)
    assert result == [{"pipeline": 18}]
