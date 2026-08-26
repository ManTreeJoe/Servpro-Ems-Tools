import json
import os


def _configure(config, tmp_path, root, monkeypatch):
    data = {
        "multi_department_enabled": True,
        "active_department": "OC",
        "departments": {"OC": {"label": "Orange County",
                                "audit_base": root}},
    }
    path = tmp_path / ("cfg-" + str(abs(hash(root))) + ".json")
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(config, "_USER_CFG", str(path))
    monkeypatch.setattr(config, "_CACHE", None)
    monkeypatch.setattr(config, "_CACHE_MTIME", None)


def test_persistence_pin_uses_each_employees_local_root(tmp_path, monkeypatch):
    import config
    import ems_db
    import ems_db_common
    import persistence

    state = tmp_path / "state.json"
    monkeypatch.setattr(persistence, "_STATE_PATH", str(state))
    monkeypatch.setattr(persistence, "_CACHE", None)
    monkeypatch.setattr(persistence, "_CACHE_MTIME", None)
    monkeypatch.setattr(ems_db, "resolve_and_link", lambda *a, **k: None)

    root_a = r"C:\Users\Nathan\OneDrive - SERVPRO\OC Jobs"
    root_b = r"C:\Users\Laura\OneDrive - SERVPRO\OC Jobs"
    _configure(config, tmp_path, root_a, monkeypatch)
    ems_db_common.invalidate_department_cache()
    path_a = os.path.join(root_a, "2026", "Smith, Jane")
    persistence.set_folder_path("Smith, Jane", path_a)

    raw = json.loads(state.read_text(encoding="utf-8"))["folder_paths"]
    stored = next(iter(raw.values()))
    assert stored.startswith("linguar-folder://OC/")
    assert "Nathan" not in stored

    _configure(config, tmp_path, root_b, monkeypatch)
    ems_db_common.invalidate_department_cache()
    got = persistence.get_folder_path("Smith, Jane")
    assert os.path.normcase(got) == os.path.normcase(os.path.join(
        root_b, "2026", "Smith, Jane"))
