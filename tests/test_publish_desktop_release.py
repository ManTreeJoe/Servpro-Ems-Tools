import base64
import hashlib
import io
import json
import urllib.error

import pytest

from tools import publish_desktop_release as publisher


@pytest.fixture
def release_api(tmp_path, monkeypatch):
    installer = tmp_path / "Setup.exe"
    installer.write_bytes(b"fake installer for offline tests")
    release = {"tag_name": "v1.8.26", "draft": True, "prerelease": False,
               "body": "Notes\n\nSource commit: source-sha",
               "url": publisher.BASE + "/releases/1",
               "html_url": "https://example.org/release",
               "upload_url": "https://uploads.github.com/test{?name}",
               "assets_url": publisher.BASE + "/releases/1/assets"}
    asset = {"name": installer.name, "size": installer.stat().st_size,
             "digest": "sha256:" + hashlib.sha256(installer.read_bytes()).hexdigest(),
             "browser_download_url": "https://github.com/ManTreeJoe/linguar-hub-releases/releases/download/untagged-deadbeef/Setup.exe"}
    state = {"existing": [], "current": None, "asset": asset, "calls": [], "download_status": 200, "heads": []}

    def request(method, url, **kwargs):
        state["calls"].append((method, url, kwargs))
        if method == "GET" and "/releases?" in url:
            return state["existing"]
        if method == "GET" and url.endswith("/assets"):
            return [state["asset"]]
        if method == "GET" and "/contents/" in url:
            assert kwargs["missing_ok"]
            return state["current"]
        if method == "POST" and url.endswith("/releases"):
            release.update(kwargs["body"])
            return release.copy()
        if method == "PATCH":
            release.update(kwargs["body"])
            return release.copy()
        return {}

    def urlopen(request, timeout):
        assert request.get_method() == "HEAD"
        assert request.get_header("Authorization") is None
        assert timeout == 180
        assert release["draft"] is False
        assert state["calls"][-1][0] == "PUT"
        manifest = json.loads(base64.b64decode(state["calls"][-1][2]["body"]["content"]))
        assert request.full_url == manifest["installer"]
        state["heads"].append(request.full_url)
        if state["download_status"] >= 400:
            raise urllib.error.HTTPError(request.full_url, state["download_status"], "Error", {}, None)
        response = io.BytesIO()
        response.status = state["download_status"]
        return response

    monkeypatch.setattr(publisher.urllib.request, "urlopen", urlopen)

    def run(action="trial", channel="trial"):
        return publisher.publish_release(request, action=action, version="1.8.26",
                                         commit="source-sha", installer=installer,
                                         notes="Notes", channel=channel)
    return state, release, run


@pytest.mark.parametrize("current", [None, {"sha": "old-feed-sha"}])
def test_trial_verifies_before_publishing_and_updates_feed(release_api, current):
    state, release, run = release_api
    state["current"] = current
    assert run()["draft"] is False
    assert release["prerelease"] is True
    assert release["make_latest"] == "false"
    assert release["target_commitish"] == "main"
    calls = state["calls"]
    assert [c[0] for c in calls] == ["GET", "POST", "POST", "GET", "PATCH", "GET", "PUT"]
    _, url, kwargs = calls[-1]
    assert url.endswith("/contents/trial/version.txt")
    body = kwargs["body"]
    assert body["branch"] == "main"
    assert body.get("sha") == (current["sha"] if current else None)
    assert json.loads(base64.b64decode(body["content"])) == {
        "version": "1.8.26", "url": release["html_url"],
        "installer": "https://github.com/ManTreeJoe/linguar-hub-releases/releases/download/v1.8.26/Setup.exe",
        "notes": "Notes"}
    assert len(state["heads"]) == 1


@pytest.mark.parametrize("field,value", [("size", 0), ("digest", "sha256:wrong"), ("digest", None)])
def test_bad_asset_never_publishes_or_updates_feed(release_api, field, value):
    state, _, run = release_api
    state["asset"][field] = value
    with pytest.raises(RuntimeError, match="size/hash"):
        run()
    assert not any(method in ("PATCH", "PUT") for method, _, _ in state["calls"])


def test_stable_draft_then_publish(release_api):
    state, release, run = release_api
    assert run("draft", "main")["draft"] is True
    assert not any(method in ("PATCH", "PUT") for method, _, _ in state["calls"])
    assert state["heads"] == []
    state["existing"] = [release.copy()]
    state["calls"].clear()
    assert run("publish", "main")["draft"] is False
    assert release["make_latest"] == "true"
    manifest = json.loads(base64.b64decode(state["calls"][-1][2]["body"]["content"]))
    assert manifest["installer"] == (
        "https://github.com/ManTreeJoe/linguar-hub-releases/releases/download/v1.8.26/Setup.exe")
    assert state["heads"] == [manifest["installer"]]
    assert state["calls"][-1][1].endswith("/contents/main/version.txt")
    assert not any(method == "POST" for method, _, _ in state["calls"])


def test_existing_release_not_overwritten(release_api):
    state, release, run = release_api
    state["existing"] = [release]
    with pytest.raises(RuntimeError, match="already exists"):
        run()
    assert len(state["calls"]) == 1


def test_mismatched_source_draft_not_published(release_api):
    state, release, run = release_api
    state["existing"] = [{**release, "body": "Different source revision"}]
    with pytest.raises(RuntimeError, match="matching draft"):
        run("publish", "main")
    assert len(state["calls"]) == 1


def test_missing_token_fails_before_network():
    with pytest.raises(RuntimeError, match="not configured"):
        publisher.token_request("")


def test_token_transport_json_upload_and_404(monkeypatch, tmp_path):
    installer = tmp_path / "Setup.exe"
    installer.write_bytes(b"installer")
    calls = []

    def urlopen(request, timeout):
        assert timeout == 180
        assert request.get_header("Authorization") == "Bearer test-only-token"
        if request.full_url.endswith("/missing"):
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)
        if hasattr(request.data, "read"):
            assert request.data.read() == b"installer"
            assert request.get_header("Content-length") == "9"
        else:
            assert json.loads(request.data) == {"draft": True}
        calls.append(request)
        return io.BytesIO(b'{"ok":true}')

    monkeypatch.setattr(publisher.urllib.request, "urlopen", urlopen)
    request = publisher.token_request("test-only-token")
    assert request("POST", "https://example.org/release", body={"draft": True})["ok"]
    assert request("POST", "https://example.org/asset", installer=installer)["ok"]
    assert calls[-1].data.closed
    assert request("GET", "https://example.org/missing", missing_ok=True) is None
    with pytest.raises(RuntimeError, match="HTTP 404"):
        request("GET", "https://example.org/missing")


@pytest.mark.parametrize("action,channel", [("trial", "trial"), ("publish", "main")])
@pytest.mark.parametrize("status", [200, 204, 404])
def test_post_publish_download_status(release_api, action, channel, status):
    state, release, run = release_api
    if action == "publish":
        state["existing"] = [release.copy()]
    state["download_status"] = status
    if status == 200:
        assert run(action, channel)["draft"] is False
    else:
        with pytest.raises(RuntimeError, match=f"HTTP {status}: https://github.com/.*/v1.8.26/Setup.exe"):
            run(action, channel)
    assert release["draft"] is False
    assert len(state["heads"]) == 1
