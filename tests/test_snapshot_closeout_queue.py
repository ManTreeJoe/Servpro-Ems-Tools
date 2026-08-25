from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_closeout_queue_has_name_board_and_lane_filters():
    html = (ROOT / "snapshot_web_assets" / "index.html").read_text(
        encoding="utf-8")
    for control in ("queue-search", "queue-board", "queue-lane", "queue-count"):
        assert f'id="{control}"' in html
    assert "Use the Snapshot toggle" in html
    assert "Close-out queue" in html


def test_jobs_deep_link_filters_queue_not_tracked_history():
    js = (ROOT / "snapshot_web_assets" / "app.js").read_text(
        encoding="utf-8")
    block = js[js.index("const _focus ="):js.index("} else {", js.index("const _focus ="))]
    assert 'snapshotShowTab("today")' in block
    assert 'state.queue.search = _focus' in block
    assert '$("#queue-search")' in block
    assert 'snapshotShowTab("tracked")' not in block
    assert '$("#tracked-search")' not in block


def test_queue_backend_is_estimating_cards_with_snapshot_state():
    source = (ROOT / "snapshot_web.py").read_text(encoding="utf-8")
    block = source[source.index("def candidate_jobs"):
                   source.index("def load_closeout_checklist")]
    assert 'if "ESTIMATING" not in bn' in block
    assert '"SNAPSHOT" in (lst.get("name") or "").upper()' in block
    assert '"snapshot": is_snapshot' in block
