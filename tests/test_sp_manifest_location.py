"""SharePoint import manifest must live under DATA_DIR, never inside
the PICS folder (which lives in the shared OneDrive).

Also: legacy in-PICS manifests get migrated transparently on first read.
"""
import json
import os
import sys
import types

import pytest


@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch):
    """Redirect paths.data() at module load so the manifest lands in tmp."""
    fake_data_dir = tmp_path / "appdata"
    fake_data_dir.mkdir()

    # Stub paths module BEFORE importing run_audit_gui so its module-level
    # _SP_MANIFEST_DIR uses our temp location.
    fake_paths = types.ModuleType("paths")
    fake_paths.data = lambda name: str(fake_data_dir / name)
    fake_paths.resource = lambda name: ""
    fake_paths.DATA_DIR = str(fake_data_dir)
    fake_paths.RESOURCE_DIR = ""
    fake_paths.VERSION = "test"
    fake_paths.is_first_run = lambda: False
    fake_paths.mark_configured = lambda: None
    fake_paths.spawn_tool = lambda *a, **kw: None
    fake_paths.launcher_command = lambda *a, **kw: []
    fake_paths.FROZEN = False
    monkeypatch.setitem(sys.modules, "paths", fake_paths)

    # Stub config so importing run_audit_gui doesn't read real config.json
    fake_config = types.ModuleType("config")
    fake_config.load = lambda: {"runs_dir": str(tmp_path / "runs"),
                                 "audit_base": str(tmp_path / "audit_base")}
    fake_config.save = lambda cfg: None
    fake_config.user_config_path = lambda: ""
    monkeypatch.setitem(sys.modules, "config", fake_config)
    (tmp_path / "runs").mkdir()
    (tmp_path / "audit_base").mkdir()

    # Now reload sp_enrich + run_audit_gui so module-level constants pick up
    # the stubs. The manifest dir (_SP_MANIFEST_DIR = paths.data("sp_imports"))
    # is computed in sp_enrich, so it must be reloaded too — run_audit_gui
    # only re-exports it via the shim.
    for mod in ("sp_enrich", "run_audit_gui"):
        if mod in sys.modules:
            del sys.modules[mod]
    import run_audit_gui  # noqa: F401
    return run_audit_gui, fake_data_dir


def test_manifest_path_is_under_data_dir(isolated_data_dir, tmp_path):
    rag, fake_data_dir = isolated_data_dir
    pics_path = tmp_path / "audit_base" / "2026" / "Smith" / "EMS" / "PICS"
    pics_path.mkdir(parents=True)

    manifest_path = rag._sp_manifest_path(str(pics_path))
    # Must be in DATA_DIR/sp_imports, not the PICS folder
    assert str(fake_data_dir) in manifest_path
    assert "PICS" not in os.path.basename(manifest_path)
    assert str(pics_path) not in manifest_path


def test_append_writes_to_data_dir(isolated_data_dir, tmp_path):
    rag, fake_data_dir = isolated_data_dir
    pics_path = tmp_path / "audit_base" / "2026" / "Smith" / "EMS" / "PICS"
    pics_path.mkdir(parents=True)

    rag._append_sp_manifest_originals(str(pics_path), ["IMG_001.jpg"])

    # Manifest exists under DATA_DIR/sp_imports
    sp_dir = fake_data_dir / "sp_imports"
    assert sp_dir.is_dir()
    files = list(sp_dir.glob("*.json"))
    assert len(files) == 1

    # No file written into the PICS folder itself
    assert not (pics_path / ".sharepoint_imported.json").exists()

    # Contents are correct
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["version"] == 2
    assert "img_001.jpg" in data["originals"]


def test_legacy_manifest_migrated_and_deleted(isolated_data_dir, tmp_path):
    rag, fake_data_dir = isolated_data_dir
    pics_path = tmp_path / "audit_base" / "2026" / "Smith" / "EMS" / "PICS"
    pics_path.mkdir(parents=True)

    # Plant a legacy v1 manifest inside the PICS folder
    legacy = pics_path / ".sharepoint_imported.json"
    legacy.write_text(
        json.dumps({"originals": ["IMG_LEGACY.jpg"]}),
        encoding="utf-8",
    )

    # First read should migrate + return the legacy entries
    originals = rag._read_sp_manifest_originals(str(pics_path))
    assert "img_legacy.jpg" in originals

    # Legacy file deleted from the OneDrive PICS folder
    assert not legacy.exists()

    # New file lives under DATA_DIR
    sp_dir = fake_data_dir / "sp_imports"
    assert any(sp_dir.glob("*.json"))


def test_clear_removes_both_locations(isolated_data_dir, tmp_path):
    rag, fake_data_dir = isolated_data_dir
    pics_path = tmp_path / "audit_base" / "2026" / "Smith" / "EMS" / "PICS"
    pics_path.mkdir(parents=True)

    # Write to DATA_DIR location
    rag._append_sp_manifest_originals(str(pics_path), ["IMG_001.jpg"])
    # And a leftover legacy file inside PICS
    legacy = pics_path / ".sharepoint_imported.json"
    legacy.write_text(
        json.dumps({"originals": ["IMG_002.jpg"]}),
        encoding="utf-8",
    )

    n = rag._clear_sp_manifest(str(pics_path))
    assert n >= 1
    # Both locations gone
    assert not legacy.exists()
    sp_dir = fake_data_dir / "sp_imports"
    assert not list(sp_dir.glob("*.json"))


def test_different_pics_paths_have_different_keys(isolated_data_dir, tmp_path):
    rag, _ = isolated_data_dir
    a = str(tmp_path / "Smith" / "PICS")
    b = str(tmp_path / "Jones" / "PICS")
    assert rag._sp_manifest_key(a) != rag._sp_manifest_key(b)


def test_same_pics_path_normalizes_consistently(isolated_data_dir, tmp_path):
    rag, _ = isolated_data_dir
    p = str(tmp_path / "Smith" / "PICS")
    # Trailing slash, different case (Windows is case-insensitive)
    assert rag._sp_manifest_key(p) == rag._sp_manifest_key(p + os.sep)
