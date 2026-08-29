from pathlib import Path
import time

import home_web


ROOT = Path(__file__).resolve().parents[1]


def test_sidebar_counts_reuse_fresh_snapshot():
    api = home_web.HomeApi.__new__(home_web.HomeApi)
    api._counts_cache = (time.monotonic(), {"pipeline": 12, "audit": 4})
    assert api.counts() == {"pipeline": 12, "audit": 4}


def test_shell_keeps_bounded_warm_panel_working_set():
    js = (ROOT / "home_web_assets" / "app.js").read_text(encoding="utf-8")
    assert "frames: new Map()" in js
    assert "MAX_WARM_PANELS = 6" in js
    assert "state.frames.get(key)" in js
    assert "evicted.remove()" in js
    assert "state.activeFrame" in js


def test_pipeline_starts_fast_and_deep_workspace_reads_concurrently():
    js = (ROOT / "pipeline_web_assets" / "app.js").read_text(encoding="utf-8")
    handler = js[js.index("async function onAuditCard"):js.index(
        "function instantWorkspaceData")]
    deep = handler.index("const fullPromise = pywebview.api.job_card_workspace")
    fast = handler.index("await pywebview.api.job_card_workspace_fast")
    consume = handler.index("await fullPromise")
    assert deep < fast < consume
