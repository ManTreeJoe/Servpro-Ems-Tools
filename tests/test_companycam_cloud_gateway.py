import companycam_api
import supabase_client


def test_edge_function_invocation_uses_signed_in_token(monkeypatch):
    captured = {}
    monkeypatch.setattr(supabase_client, "access_token", lambda: "user-jwt")
    monkeypatch.setattr(
        supabase_client, "_raw",
        lambda method, path, **kwargs: captured.update(
            method=method, path=path, **kwargs) or {"ok": True})

    result = supabase_client.invoke_function("companycam-gateway", {"path": "/projects"})

    assert result == {"ok": True}
    assert captured["path"] == "/functions/v1/companycam-gateway"
    assert captured["token"] == "user-jwt"


def test_companycam_uses_cloud_when_local_key_is_blank(monkeypatch):
    monkeypatch.setattr(companycam_api.config, "load", lambda: {"companycam_api_token": ""})
    monkeypatch.setattr(companycam_api, "cloud_gateway_available", lambda: True)
    monkeypatch.setattr(companycam_api, "_cloud_call", lambda *args, **kwargs: {
        "path": args[0], "method": kwargs["method"]})

    assert companycam_api._call("/projects", method="GET") == {
        "path": "/projects", "method": "GET"}


def test_companycam_keeps_local_key_rollout_fallback(monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def read(self): return b'[]'

    monkeypatch.setattr(companycam_api.config, "load", lambda: {
        "companycam_api_token": "local-key"})
    monkeypatch.setattr(companycam_api, "_cloud_call", lambda *_a, **_k: (_ for _ in ()).throw(
        AssertionError("cloud should not be called")))
    monkeypatch.setattr(companycam_api.urllib.request, "urlopen", lambda *_a, **_k: Response())

    assert companycam_api._call("/projects") == []


def test_gateway_source_checks_membership_and_never_returns_secret():
    from pathlib import Path
    source = (Path(__file__).parents[1] / "supabase" / "functions" /
              "companycam-gateway" / "index.ts").read_text(encoding="utf-8")
    assert "my_app_access" in source
    assert "memberships.includes(department)" in source
    assert "COMPANYCAM_${department}_KEY" in source
    assert "console.log(credential" not in source
    assert "credential:" not in source
    assert "{ credential }" not in source
