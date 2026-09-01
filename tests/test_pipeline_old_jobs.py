from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_old_jobs_board_is_lazy_and_not_in_startup_boards():
    backend = (ROOT / "pipeline_web.py").read_text(encoding="utf-8")
    frontend = (ROOT / "pipeline_web_assets" / "app.js").read_text(encoding="utf-8")
    assert 'ARCHIVE_BOARD_SPEC = ("logs", "THE LOGS - EMS")' in backend
    board_specs = backend[backend.index("BOARD_SPECS ="):backend.index("ARCHIVE_BOARD_SPEC")]
    assert "THE LOGS - EMS" not in board_specs
    assert 'pywebview.api.board_view_one("logs")' in frontend
    assert "loadArchiveBoard" in frontend
    assert 'board.key === "logs" ? 80' in frontend


def test_old_jobs_remain_read_only_on_trello_board():
    backend = (ROOT / "pipeline_web.py").read_text(encoding="utf-8")
    frontend = (ROOT / "pipeline_web_assets" / "app.js").read_text(encoding="utf-8")
    assert '"historical": True, "mirrored": False' in backend
    assert 'if (active.key === "logs") return;' in frontend
