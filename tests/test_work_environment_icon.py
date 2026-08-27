from pathlib import Path
import json

import home_web
import paths


ROOT = Path(__file__).resolve().parents[1]


def test_shell_header_exposes_channel_for_icon_family():
    header = home_web.HomeApi().header()
    assert isinstance(header["is_trial"], bool)
    assert header["work_environment"] in {"EMS", "CONTENTS", "RECON"}


def test_header_mark_tracks_the_existing_environment_switch():
    js = (ROOT / "home_web_assets" / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "home_web_assets" / "index.html").read_text(encoding="utf-8")
    assert 'id="work-env-mark"' in html
    assert "renderWorkEnvironmentMark(st.active)" in js
    assert 'env === "CONTENTS"' in js
    assert 'env === "RECON"' in js
    assert 'fill="#2688ff"' in js
    assert 'stroke="#f2e500"' in js
    assert 'fill="#ff7900"' in js
    assert "workEnvironmentIcon(active)" in js
    assert "restorationCycleIcon" not in js


def test_main_and_trial_windows_icons_are_separate_assets():
    spec = (ROOT / "Linguar_Hub.spec").read_text(encoding="utf-8")
    iss = (ROOT / "Linguar_Hub.iss").read_text(encoding="utf-8")
    assert "linguar_hub.ico" in spec and "linguar_hub_trial.ico" in spec
    assert "SetupIconFile={#SetupIcon}" in iss
    for name in ("linguar_hub.ico", "linguar_hub_trial.ico"):
        assert (ROOT / name).is_file()


def test_running_window_receives_channel_taskbar_icon():
    shell = (ROOT / "home_web.py").read_text(encoding="utf-8")
    spec = (ROOT / "Linguar_Hub.spec").read_text(encoding="utf-8")

    assert '"linguar_hub_trial.ico"' in shell
    assert 'else "linguar_hub.ico"' in shell
    assert "webview.start(debug=False, http_server=True, icon=taskbar_icon)" in shell
    assert "datas.append((os.path.join(base, ICON_FILE), '.'))" in spec


def test_taskbar_identity_is_separate_and_matches_installer_shortcuts():
    shell = (ROOT / "home_web.py").read_text(encoding="utf-8")
    iss = (ROOT / "Linguar_Hub.iss").read_text(encoding="utf-8")

    for app_id in ("Servpro.LinguarHub.Main.2026",
                   "Servpro.LinguarHub.Trial.2026"):
        assert app_id in shell
        assert app_id in iss
    assert "SetCurrentProcessExplicitAppUserModelID(app_id)" in shell
    assert 'AppUserModelID: "{#AppUserModelId}"' in iss


def test_update_checker_uses_the_bundled_release_version():
    manifest = json.loads((ROOT / "version.txt").read_text(encoding="utf-8"))
    spec = (ROOT / "Linguar_Hub.spec").read_text(encoding="utf-8")

    assert paths.VERSION == manifest["version"]
    assert "datas.append((os.path.join(base, 'version.txt'), '.'))" in spec
