"""Regression coverage for live-run stability failures."""
from pathlib import Path

import data_backup
import home_web
import persistence


ROOT = Path(__file__).resolve().parents[1]


def test_audit_search_normalizes_optional_lists():
    js = (ROOT / "audit_web_assets" / "app.js").read_text(encoding="utf-8")
    search = js[js.index("const q = state.search"):js.index("function setFilter")]
    for field in ("r.techs", "r.form_issues", "r.photo_issues"):
        assert f"Array.isArray({field})" in search
    assert "...r.techs" not in search
    assert "...r.form_issues" not in search
    assert "...r.photo_issues" not in search


def test_audit_loader_uses_current_cache_key():
    html = (ROOT / "audit_web_assets" / "index.html").read_text(
        encoding="utf-8")
    assert 'app.js?v=20260903b' in html


def test_normal_backup_worker_schedules_the_next_check(monkeypatch):
    scheduled = []
    monkeypatch.setattr(data_backup, "run_once", lambda force=False: {})
    monkeypatch.setattr(data_backup, "_schedule_next",
                        lambda: scheduled.append(True))
    worker = data_backup.start_background()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert scheduled == [True]


def test_forced_backup_worker_stays_one_shot(monkeypatch):
    scheduled = []
    monkeypatch.setattr(data_backup, "run_once", lambda force=False: {})
    monkeypatch.setattr(data_backup, "_schedule_next",
                        lambda: scheduled.append(True))
    worker = data_backup.start_background(force=True)
    worker.join(timeout=5)
    assert scheduled == []


def test_main_claims_instance_before_starting_either_shell():
    import inspect

    src = inspect.getsource(home_web.main)
    claim = src.index("_claim_single_instance()")
    assert claim < src.index('if "--quickimport"')
    assert claim < src.index("webview.create_window")


def test_main_and_trial_use_separate_single_instance_locks(monkeypatch):
    import paths

    monkeypatch.setattr(paths, "IS_TRIAL", False)
    assert home_web._instance_mutex_name() == (
        "Local\\LinguarHub.Main.SingleInstance")

    monkeypatch.setattr(paths, "IS_TRIAL", True)
    assert home_web._instance_mutex_name() == (
        "Local\\LinguarHub.Trial.SingleInstance")


def test_state_replace_retries_a_brief_windows_lock(tmp_path, monkeypatch):
    src = tmp_path / "state.tmp"
    dst = tmp_path / "state.json"
    src.write_text("{}", encoding="utf-8")
    real_replace = persistence.os.replace
    attempts = []
    delays = []

    def flaky_replace(a, b):
        attempts.append((a, b))
        if len(attempts) < 3:
            raise PermissionError("temporarily locked")
        return real_replace(a, b)

    monkeypatch.setattr(persistence.os, "replace", flaky_replace)
    monkeypatch.setattr(persistence.time, "sleep", delays.append)

    persistence._replace_with_retry(str(src), str(dst))

    assert dst.read_text(encoding="utf-8") == "{}"
    assert len(attempts) == 3
    assert delays == [0.02, 0.05]


def test_state_replace_stops_after_the_bounded_retry_budget(tmp_path, monkeypatch):
    src = tmp_path / "state.tmp"
    src.write_text("{}", encoding="utf-8")
    attempts = []
    monkeypatch.setattr(
        persistence.os, "replace",
        lambda *_args: (attempts.append(True), (_ for _ in ()).throw(
            PermissionError("still locked")))[1])
    monkeypatch.setattr(persistence.time, "sleep", lambda _delay: None)

    import pytest
    with pytest.raises(PermissionError):
        persistence._replace_with_retry(str(src), str(tmp_path / "state.json"))
    assert len(attempts) == len(persistence._REPLACE_DELAYS) + 1
