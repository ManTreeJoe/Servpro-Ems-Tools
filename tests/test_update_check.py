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
    ("1.9.0", "1.10.0", True),
])
def test_check_success(monkeypatch, current, latest, available):
    monkeypatch.setattr(update_check, "_CHANNEL", "trial")
    monkeypatch.setattr(paths, "VERSION", current)
    manifest = {"version": latest, "url": "https://github.com/ManTreeJoe/linguar-hub-releases/releases/tag/test",
                "installer": "https://github.com/ManTreeJoe/linguar-hub-releases/releases/download/test/setup.exe", "notes": "Test build"}

    def urlopen(request, timeout):
        assert request.full_url == update_check.RAW_URL
        assert request.get_header("Authorization") is None
        assert timeout == 3
        return io.BytesIO(json.dumps(manifest).encode())

    monkeypatch.setattr(update_check.urllib.request, "urlopen", urlopen)
    assert update_check.check(timeout=3) == {
        "ok": True, "update_available": available, "current": current,
        "latest": latest, "private_download": False, "source": update_check.RAW_URL, "sha256": "", **{key: manifest[key] for key in ("url", "installer", "notes")},
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


def private_manifest(**changes):
    return dict({'version': '1.8.48', 'url': 'https://updates.oneloss.work/',
                 'installer': 'https://updates.oneloss.work/downloads/OneLoss-1.8.48.exe',
                 'sha256': 'a' * 64, 'notes': 'Fixture'}, **changes)


def test_main_prefers_private_metadata_without_auth(monkeypatch):
    monkeypatch.setattr(update_check, '_CHANNEL', 'main')
    monkeypatch.setattr(paths, 'VERSION', '1.8.47')
    calls = []
    def fake(request, timeout):
        calls.append(request.full_url)
        assert request.get_header('Authorization') is None
        assert timeout == 6
        return io.BytesIO(json.dumps(private_manifest()).encode())
    monkeypatch.setattr(update_check.urllib.request, 'urlopen', fake)
    result = update_check.check()
    assert calls == [update_check.TEAM_URL]
    assert result['private_download'] and result['update_available']


@pytest.mark.parametrize('bad', [b'<html>Access login</html>', b'[]', b'{}',
    json.dumps(private_manifest(sha256='')).encode(),
    json.dumps(private_manifest(installer='https://attacker.invalid/setup.exe')).encode(),
    json.dumps(private_manifest(version='')).encode()])
def test_main_bad_private_feed_falls_back_to_github(monkeypatch, bad):
    monkeypatch.setattr(update_check, '_CHANNEL', 'main')
    calls = []
    manifest = {'version':'1.8.48', 'url':'https://github.com/ManTreeJoe/linguar-hub-releases/releases/tag/test',
                'installer':'https://github.com/ManTreeJoe/linguar-hub-releases/releases/download/test/setup.exe'}
    def fake(request, timeout):
        calls.append(request.full_url)
        return io.BytesIO(bad if len(calls) == 1 else json.dumps(manifest).encode())
    monkeypatch.setattr(update_check.urllib.request, 'urlopen', fake)
    result = update_check.check()
    assert calls == [update_check.TEAM_URL, update_check.RAW_URL]
    assert result['ok'] and not result['private_download']


def test_network_error_falls_back(monkeypatch):
    monkeypatch.setattr(update_check, '_CHANNEL', 'main')
    calls = []
    def fake(request, timeout):
        calls.append(request.full_url)
        raise OSError('offline')
    monkeypatch.setattr(update_check.urllib.request, 'urlopen', fake)
    assert update_check.check()['ok'] is False
    assert calls == [update_check.TEAM_URL, update_check.RAW_URL]


def test_private_installer_opens_browser_only(monkeypatch):
    # Execute just this actual method with a fake API; no home/application imports.
    import ast
    from pathlib import Path
    from types import SimpleNamespace
    tree = ast.parse((Path(__file__).parents[1] / 'home_web.py').read_text(encoding='utf-8'))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'install_update')
    scope = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), 'home_web.py', 'exec'), scope)
    monkeypatch.setattr(update_check, 'check', lambda: dict(private_manifest(), private_download=True))
    monkeypatch.setattr(update_check.urllib.request, 'urlopen', lambda *a, **kw: pytest.fail('Installer download attempted'))
    opened = []
    result = scope['install_update'](SimpleNamespace(open_url=lambda url: opened.append(url) or True))
    assert opened == [private_manifest()['installer']]
    assert result == {'ok':True, 'launched':False, 'opened_page':True, 'private_download':True}
