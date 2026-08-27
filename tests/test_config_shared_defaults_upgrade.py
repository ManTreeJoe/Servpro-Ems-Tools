import json

import config


def test_upgrade_backfills_shared_connections_without_overwriting_user_values(tmp_path, monkeypatch):
    user = tmp_path / "user.json"
    bundled = tmp_path / "bundled.json"
    user.write_text(json.dumps({
        "supabase_url": "", "supabase_anon_key": "",
        "trello_api_key": "", "trello_token": "my-personal-token",
        "runs_dir": r"C:\Users\Worker\Runs",
    }), encoding="utf-8")
    bundled.write_text(json.dumps({
        "supabase_url": "https://shared.supabase.co",
        "supabase_anon_key": "sb_publishable_shared",
        "trello_api_key": "shared-app-key",
        "trello_token": "",
        "runs_dir": "",
    }), encoding="utf-8")
    monkeypatch.setattr(config, "_USER_CFG", str(user))
    monkeypatch.setattr(config, "_DEFAULT_CFG", str(bundled))

    config._ensure_user_config()

    saved = json.loads(user.read_text(encoding="utf-8"))
    assert saved["supabase_url"] == "https://shared.supabase.co"
    assert saved["supabase_anon_key"] == "sb_publishable_shared"
    assert saved["trello_api_key"] == "shared-app-key"
    assert saved["trello_token"] == "my-personal-token"
    assert saved["runs_dir"] == r"C:\Users\Worker\Runs"


def test_upgrade_does_not_replace_existing_shared_connection(tmp_path, monkeypatch):
    user = tmp_path / "user.json"
    bundled = tmp_path / "bundled.json"
    user.write_text(json.dumps({"supabase_url": "https://custom.example"}), encoding="utf-8")
    bundled.write_text(json.dumps({"supabase_url": "https://bundled.example"}), encoding="utf-8")
    monkeypatch.setattr(config, "_USER_CFG", str(user))
    monkeypatch.setattr(config, "_DEFAULT_CFG", str(bundled))

    config._ensure_user_config()

    assert json.loads(user.read_text(encoding="utf-8"))["supabase_url"] == "https://custom.example"

