import ems_db
import ems_db_sqlite
import persistence


def test_pinning_folder_never_waits_for_shared_database(monkeypatch):
    state = {}
    remote, local = [], []
    monkeypatch.setattr(persistence, "_load", lambda: state)
    monkeypatch.setattr(persistence, "_save", lambda value: None)
    monkeypatch.setattr(ems_db, "resolve_and_link", lambda *a, **k: remote.append((a, k)))
    monkeypatch.setattr(ems_db_sqlite, "resolve_and_link", lambda *a, **k: local.append((a, k)))
    persistence.set_folder_path("Folder Test", "C:/Jobs/Folder Test")
    assert state["folder_paths"]
    assert remote == [], "pinning a local folder must not call the shared backend"
    assert len(local) == 1, "local job matching must still learn the chosen folder"
