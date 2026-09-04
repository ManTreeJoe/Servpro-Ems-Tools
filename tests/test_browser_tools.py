from pathlib import Path

from browser_tools import BrowserToolHost


ROOT = Path(__file__).resolve().parents[1]


class FakePanel:
    def load(self, name):
        return {"ok": True, "name": name}

    def save(self, payload):
        return {"ok": True, "saved": payload}

    def open_file(self, path):
        return {"ok": True, "path": path}

    def attach(self, _window):
        raise AssertionError("native attachment must not be exposed")


class FakeHome:
    def __init__(self):
        self._subs = {"jobs": FakePanel()}
        self._failed_subs = {}
        self.jobs_load = self._subs["jobs"].load
        self.jobs_save = self._subs["jobs"].save

    def header(self):
        return {"greeting": "Hello"}

    def install_update(self, _url=""):
        raise AssertionError("browser must never invoke the desktop installer")


def test_browser_host_exposes_registered_panel_through_one_interface():
    host = BrowserToolHost(FakeHome)
    assert host.call("header") == {"greeting": "Hello"}
    assert host.call("jobs_load", ["Rose, Jasmin"]) == {
        "ok": True, "name": "Rose, Jasmin"}
    assert host.call("jobs_save", [{"state": "done"}]) == {
        "ok": True, "saved": {"state": "done"}}


def test_browser_host_rejects_private_and_unregistered_methods():
    host = BrowserToolHost(FakeHome)
    assert host.call("jobs_attach")["ok"] is False
    assert host.call("__class__")["ok"] is False
    assert host.call("missing_method")["ok"] is False


def test_remote_browser_cannot_control_the_host_desktop():
    host = BrowserToolHost(FakeHome)
    result = host.call("jobs_open_file", ["X:/job.pdf"], local_request=False)
    assert result["ok"] is False
    assert result["local_only"] is True


def test_browser_never_runs_the_windows_installer_even_on_localhost():
    result = BrowserToolHost(FakeHome).call(
        "install_update", ["https://example.invalid/setup.exe"],
        local_request=True)
    assert result["ok"] is False
    assert result["desktop_only"] is True
    assert "Windows app" in result["error"]


def test_browser_shell_assets_use_the_shared_bridge_and_tool_routes():
    portal = (ROOT / "operations_portal.py").read_text(encoding="utf-8")
    bridge = (ROOT / "web_shared" / "browser_bridge.js").read_text(encoding="utf-8")
    operations = (ROOT / "operations_web_assets" / "app.js").read_text(encoding="utf-8")
    tool_routes = (ROOT / "operations_tools.py").read_text(encoding="utf-8")
    home = (ROOT / "home_web_assets" / "app.js").read_text(encoding="utf-8")
    assert '"/api/tool-call"' in bridge
    assert 'window.pywebview = { api }' in bridge
    assert '"/api/tools"' in portal
    assert '"/tools/"' in tool_routes
    assert "state.data?.tool_routes" in operations
    assert "openRequestedBrowserPanel" in home
    assert "if (window.__LINGUAR_BROWSER_TOOLS__) return;" in home


def test_tools_shell_uses_the_real_hub_mark_instead_of_gradient_placeholders():
    html = (ROOT / "home_web_assets" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "home_web_assets" / "app.css").read_text(encoding="utf-8")
    assert 'class="welcome-mark" aria-hidden="true"><img src="../linguar_hub.png"' in html
    assert 'class="fr-emoji" aria-hidden="true"><img src="../linguar_hub.png"' in html
    assert ".pane { background:var(--bg); }" in css
