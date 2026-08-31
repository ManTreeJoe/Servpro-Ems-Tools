import os

import machine_folders


def test_windows_user_path_rebases_when_same_tail_exists(tmp_path, monkeypatch):
    home = tmp_path / "Samantha"
    target = home / "OneDrive - servpro10100.com" / "IE Public"
    target.mkdir(parents=True)
    old = r"C:\Users\Nathan\OneDrive - servpro10100.com\IE Public"
    result = machine_folders.rebase_user_path(old, str(home))
    assert os.path.normcase(result) == os.path.normcase(str(target))


def test_mapped_and_unc_paths_are_not_rewritten():
    assert machine_folders.rebase_user_path(r"X:\IE_Public") == os.path.normpath(r"X:\IE_Public")
    assert machine_folders.rebase_user_path(r"\\server\jobs") == os.path.normpath(r"\\server\jobs")


def test_daily_run_is_derived_under_selected_root(tmp_path, monkeypatch):
    root = tmp_path / "IE_Public"
    run = root / "Daily Run" / "2031"
    run.mkdir(parents=True)
    monkeypatch.setattr(machine_folders.datetime, "date", type(
        "Date", (), {"today": staticmethod(lambda: type("D", (), {"year": 2031})())}))
    assert machine_folders.derive_daily_run(str(root)) == os.path.normpath(str(run))
