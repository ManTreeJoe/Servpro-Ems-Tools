from pathlib import Path

import home_web


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
    assert 'env === "EMS"' in js
    assert 'env === "CONTENTS"' in js
    assert 'env === "RECON"' in js


def test_main_and_trial_windows_icons_are_separate_assets():
    spec = (ROOT / "Linguar_Hub.spec").read_text(encoding="utf-8")
    iss = (ROOT / "Linguar_Hub.iss").read_text(encoding="utf-8")
    assert "linguar_hub.ico" in spec and "linguar_hub_trial.ico" in spec
    assert "SetupIconFile={#SetupIcon}" in iss
    for name in ("linguar_hub.ico", "linguar_hub_trial.ico"):
        assert (ROOT / name).is_file()
