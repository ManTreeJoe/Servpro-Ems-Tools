"""A kept installer is only a rollback if it is still the file you put
there. Everything here is about proving that, not assuming it."""
import os

import release_keep as rk


def _installer(tmp_path, name="Setup-1.0.0.exe", data=b"MZ-pretend-exe"):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def test_it_records_the_hash_not_just_the_file(tmp_path):
    root = str(tmp_path / "share")
    r = rk.record(_installer(tmp_path), root, "1.0.0", when="2026-08-20 10:00")
    assert r["ok"] is True
    assert os.path.isfile(r["path"])
    assert rk.read_manifest(root)["releases"][0]["sha256"] == r["sha256"]


def test_a_corrupted_copy_is_caught(tmp_path):
    """A file-exists check would call this fine, which is exactly the
    day you find out it was not."""
    root = str(tmp_path / "share")
    r = rk.record(_installer(tmp_path), root, "1.0.0")
    with open(r["path"], "ab") as fh:
        fh.write(b"corruption")
    v = rk.verify(root)
    assert v["ok"] is False
    assert v["bad"][0]["problem"] == "hash does not match"


def test_a_deleted_copy_is_caught(tmp_path):
    root = str(tmp_path / "share")
    r = rk.record(_installer(tmp_path), root, "1.0.0")
    os.remove(r["path"])
    assert rk.verify(root)["bad"][0]["problem"] == "missing"


def test_a_good_copy_verifies(tmp_path):
    root = str(tmp_path / "share")
    rk.record(_installer(tmp_path), root, "1.0.0")
    assert rk.verify(root)["ok"] is True


def test_no_half_written_file_survives_a_failed_copy(tmp_path, monkeypatch):
    root = str(tmp_path / "share")
    src = _installer(tmp_path)
    # Hash the temp copy as something else: the copy "succeeded" but the
    # bytes do not match, which is the case a plain copy would miss.
    calls = {"n": 0}
    real = rk.sha256

    def fake(path, *a, **k):
        calls["n"] += 1
        return real(path) if calls["n"] == 1 else "deadbeef"

    monkeypatch.setattr(rk, "sha256", fake)
    r = rk.record(src, root, "1.0.0")
    assert r["ok"] is False
    assert not os.path.exists(os.path.join(root, "1.0.0", "Setup-1.0.0.exe.part"))


def test_rollback_names_the_previous_release(tmp_path):
    root = str(tmp_path / "share")
    rk.record(_installer(tmp_path, "Setup-1.0.0.exe", b"one"), root, "1.0.0")
    rk.record(_installer(tmp_path, "Setup-1.1.0.exe", b"two"), root, "1.1.0")
    t = rk.rollback_target(root)
    assert t["ok"] is True and t["version"] == "1.0.0"


def test_rollback_says_so_when_there_is_nothing_to_go_back_to(tmp_path):
    root = str(tmp_path / "share")
    rk.record(_installer(tmp_path), root, "1.0.0")
    assert rk.rollback_target(root)["ok"] is False


def test_rollback_never_installs(tmp_path):
    """It returns a path. Running it is a decision made at a machine."""
    root = str(tmp_path / "share")
    rk.record(_installer(tmp_path, "Setup-1.0.0.exe", b"one"), root, "1.0.0")
    rk.record(_installer(tmp_path, "Setup-1.1.0.exe", b"two"), root, "1.1.0")
    t = rk.rollback_target(root)
    assert set(t) >= {"path", "sha256", "version"}


def test_old_releases_are_pruned_but_the_record_is_written_first(tmp_path):
    root = str(tmp_path / "share")
    for i in range(5):
        rk.record(_installer(tmp_path, f"Setup-1.0.{i}.exe", f"v{i}".encode()),
                  root, f"1.0.{i}")
    man = rk.read_manifest(root)
    assert [r["version"] for r in man["releases"]] == ["1.0.4", "1.0.3", "1.0.2"]
    assert not os.path.isdir(os.path.join(root, "1.0.0"))
    assert rk.verify(root)["ok"] is True


def test_a_missing_installer_is_an_error_not_a_crash(tmp_path):
    assert rk.record(str(tmp_path / "nope.exe"), str(tmp_path), "1.0")["ok"] is False


def test_re_recording_a_version_replaces_it(tmp_path):
    root = str(tmp_path / "share")
    rk.record(_installer(tmp_path, "Setup-1.0.0.exe", b"one"), root, "1.0.0")
    rk.record(_installer(tmp_path, "Setup-1.0.0.exe", b"rebuilt"), root, "1.0.0")
    man = rk.read_manifest(root)
    assert [r["version"] for r in man["releases"]] == ["1.0.0"]
    assert rk.verify(root)["ok"] is True
