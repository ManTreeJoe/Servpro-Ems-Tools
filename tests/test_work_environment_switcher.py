from unittest.mock import patch

import home_web


def _api():
    return home_web.HomeApi.__new__(home_web.HomeApi)


def test_work_environment_defaults_to_ems():
    with patch.object(home_web.persistence, "get", return_value=None):
        assert _api().active_work_environment() == "EMS"


def test_state_lists_the_three_job_divisions():
    with patch.object(home_web.persistence, "get", return_value="CONTENTS"):
        state = _api().work_environment_state()
    assert state["active"] == "CONTENTS"
    assert [item["key"] for item in state["environments"]] == [
        "EMS", "CONTENTS", "RECON"
    ]


def test_switch_saves_the_work_environment():
    api = _api()
    with patch.object(api, "active_work_environment", return_value="EMS"), \
         patch.object(home_web.persistence, "set_value") as save:
        result = api.switch_work_environment("RECON")
    assert result == {"ok": True, "active": "RECON", "reload": True}
    save.assert_called_once_with("home_work_environment", "RECON")


def test_switch_rejects_unknown_environment():
    assert _api().switch_work_environment("roofing")["ok"] is False


def test_shell_does_not_treat_job_division_as_a_global_mode():
    path = home_web.os.path.join(home_web._HERE, "home_web_assets", "app.js")
    with open(path, encoding="utf-8") as handle:
        javascript = handle.read()
    html_path = home_web.os.path.join(home_web._HERE, "home_web_assets", "index.html")
    with open(html_path, encoding="utf-8") as handle:
        html = handle.read()
    assert 'params.set("work_environment", state.header.work_environment)' not in javascript
    assert 'id="work-env-switch"' not in html
    assert "renderWorkEnvironmentSwitch" not in javascript
