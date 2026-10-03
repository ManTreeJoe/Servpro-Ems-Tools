import importlib
import io
import json

import pytest

import paths
import update_check


@pytest.mark.parametrize("trial,channel", [(False, "main"), (True, "trial")])
def test_channel_url(monkeypatch, trial, channel):
    with monkeypatch.context() as patch:
        patch.setattr(paths, "IS_TRIAL", trial)
        importlib.reload(update_check)
        assert update_check.RAW_URL == (
            f"https://raw.githubusercontent.com/ManTreeJoe/"
            f"linguar-hub-releases/main/{channel}/version.txt")
    importlib.reload(update_check)


@pytest.mark.parametrize("value,expected", [
    ("1.10.0", (1, 10, 0)), ("1.8.26-trial.5", (1, 8, 26, 5)),
    ("", (0,)), ("unknown", (0,)),
])
def test_version_tuple(value, expected):
    assert update_check._tuple(value) == expected


@pytest.mark.parametrize("current,latest,available", [
    ("1.8.26", "1.8.26-trial.5", True),
    ("1.8.26-trial.5", "1.8.26-trial.6", True),
    ("1.8.26-trial.5", "1.8.26-trial.5", False),
    ("1.8.26-trial.5", "1.8.26", False),
    ("1.9.0", "1.10.0", True), ("2.0", "", False),
])
def test_check_success(monkeypatch, current, latest, available):
    monkeypatch.setattr(paths, "VERSION", current)
    manifest = {"version": latest, "url": "https://example.org/release",
                "installer": "https://example.org/setup.exe", "notes": "Test build"}

    def urlopen(request, timeout):
        assert request.full_url == update_check.RAW_URL
        assert request.get_header("Authorization") is None
        assert timeout == 3
        return io.BytesIO(json.dumps(manifest).encode())

    monkeypatch.setattr(update_check.urllib.request, "urlopen", urlopen)
    assert update_check.check(timeout=3) == {
        "ok": True, "update_available": available, "current": current,
        "latest": latest, **{key: manifest[key] for key in ("url", "installer", "notes")},
    }


@pytest.mark.parametrize("payload", [None, b"not JSON", b"[]"])
def test_check_failure_never_raises(monkeypatch, payload):
    def urlopen(*args, **kwargs):
        if payload is None:
            raise OSError("offline")
        return io.BytesIO(payload)
    monkeypatch.setattr(update_check.urllib.request, "urlopen", urlopen)
    result = update_check.check()
    assert result["ok"] is False
    assert result["update_available"] is False
    assert result["error"]
