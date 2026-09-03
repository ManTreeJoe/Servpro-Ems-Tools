"""Offices are a list, not a fixed IE/OC pair.

The scaffold seeded exactly IE and OC, so an install that is only one of
them got a profile it did not want — and an office that is neither (LA)
could not be created at all. `settings_web` also hardcoded IE as "the
base", so a single-OC install had a base department it could never be.
"""
import pytest

import config


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    """An isolated base config."""
    state = {"departments": {"IE": {"label": "Inland Empire"}},
             "active_department": "IE"}
    monkeypatch.setattr(config, "load_base", lambda: dict(state))
    monkeypatch.setattr(config, "save", lambda c: state.update(c))
    return state


def test_a_new_office_can_be_added(cfg):
    ok, err = config.add_department("LA", "Los Angeles")
    assert ok, err
    assert "LA" in cfg["departments"]
    assert cfg["departments"]["LA"]["label"] == "Los Angeles"


def test_a_new_office_starts_empty(cfg):
    """Inheriting the base is right; copying another office's paths would
    silently point it at the wrong share."""
    config.add_department("LA")
    assert set(cfg["departments"]["LA"]) == {"label"}


def test_the_code_defaults_to_the_label(cfg):
    config.add_department("la")
    assert "LA" in cfg["departments"]          # normalized upper


def test_adding_a_second_office_turns_multi_dept_on(cfg):
    config.add_department("LA")
    assert cfg["multi_department_enabled"] is True


def test_a_duplicate_is_refused(cfg):
    ok, err = config.add_department("IE")
    assert not ok and "exists" in err


@pytest.mark.parametrize("bad", ["", "   ", "L A!", "a/b"])
def test_a_bad_code_is_refused(cfg, bad):
    ok, err = config.add_department(bad)
    assert not ok and err


def test_an_office_can_be_removed(cfg):
    config.add_department("LA")
    ok, err = config.remove_department("LA")
    assert ok, err
    assert "LA" not in cfg["departments"]


def test_the_active_office_cannot_be_removed(cfg):
    """Removing it leaves the app resolving through a profile that no
    longer exists, which reads as 'everything inherited the base' — the
    silent cross-franchise wiring the other guards exist to stop."""
    config.add_department("LA")
    ok, err = config.remove_department("IE")
    assert not ok and "switch" in err.lower()


def test_the_last_office_cannot_be_removed(cfg):
    ok, err = config.remove_department("IE")
    assert not ok and "only office" in err.lower()


def test_dropping_to_one_office_turns_multi_dept_off(cfg):
    config.add_department("LA")
    config.remove_department("LA")
    assert cfg["multi_department_enabled"] is False


def test_companycam_is_department_scoped():
    """Each office has its own CompanyCam account. Without this every
    department fell through to the base token, so OC's projects were
    created in IE's CompanyCam."""
    assert "companycam_api_token" in config.DEPT_OVERRIDE_KEYS


def test_the_settings_form_can_set_it():
    """The plumbing is useless if there is nowhere to paste the token."""
    import settings_web
    assert any(f[0] == "companycam_api_token"
               for f in settings_web.DEPT_FIELDS)


def test_the_base_office_is_whichever_one_is_active():
    """`is_base` was a literal comparison to IE, so an only-OC install
    had a base department it could never be. It now derives from the
    active office — asserted on BEHAVIOUR, because the comment
    explaining the old bug legitimately quotes it."""
    import inspect, settings_web
    src = inspect.getsource(settings_web.Api.dept_config)
    line = next(l for l in src.splitlines() if '"is_base"' in l)
    assert "IE" not in line
    body = src[src.index('"is_base"'):]
    assert "active_department" in body[:300]


# ── the Franchise UI ───────────────────────────────────────────────────

def _settings_html():
    import io as _io, os
    return _io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "settings_web_assets", "index.html"),
        encoding="utf-8").read()


def test_the_section_is_called_franchises():
    html = _settings_html()
    assert "Franchises" in html
    assert "Enable multiple departments (OC / IE)" not in html


def test_the_toggle_does_not_name_two_specific_offices():
    """'Enable multiple departments (OC / IE)' told a single-LA install
    it had the wrong two offices."""
    html = _settings_html()
    assert "more than one franchise" in html.lower()


def test_a_franchise_can_be_added_and_removed_from_settings():
    html = _settings_html()
    assert 'id="dept-add"' in html and 'id="dept-remove"' in html
    assert "add_department" in html and "remove_department" in html


def test_removing_asks_first_and_says_what_is_lost():
    """It drops folder/Trello/CompanyCam wiring nothing else records."""
    html = _settings_html()
    i = html.index("async function removeFranchise")
    body = html[i:i + 900]
    assert "confirm(" in body
    assert "CompanyCam" in body


def test_the_help_no_longer_claims_companycam_is_shared():
    """It said 'CompanyCam ... stay shared', which was true and was
    exactly the bug: OC's projects went to IE's account."""
    html = _settings_html()
    assert "CompanyCam, appearance, and feature flags stay shared" not in html


def test_remove_is_disabled_with_a_single_franchise():
    html = _settings_html()
    assert 'document.getElementById("dept-remove").disabled' in html


# ── franchise data separation ──────────────────────────────────────────

@pytest.mark.parametrize("key", [
    "snapshots_root",         # IE's Excel workbook was read by OC
    "dispute_tracker_path",   # one shared workbook for both franchises
    "companycam_api_token",   # OC's projects created in IE's account
])
def test_franchise_owned_data_is_scoped(key):
    """These pointed at IE's share for EVERY franchise, so the two read
    and wrote each other's records with no sign of it."""
    assert key in config.DEPT_OVERRIDE_KEYS


@pytest.mark.parametrize("key", ["snapshots_root", "dispute_tracker_path"])
def test_they_can_be_set_per_franchise(key):
    """Scoping is useless if there is nowhere to type the path."""
    import settings_web
    assert any(f[0] == key for f in settings_web.DEPT_FIELDS)


def test_machine_paths_stay_shared():
    """`scripts_dir` and the Python path describe THIS PC, not a
    franchise — scoping them would ask for the same value twice."""
    for key in ("scripts_dir", "pythonw"):
        assert key not in config.DEPT_OVERRIDE_KEYS


# ── blank means "none of my own", not "use theirs" ─────────────────────

@pytest.fixture
def two_franchises(tmp_path, monkeypatch):
    """IE owns the base values; OC has a profile but no records."""
    cfg = {
        "multi_department_enabled": True,
        "active_department": "IE",
        "base_department": "IE",
        "dispute_tracker_path": r"X:\shared\Dispute Tracker.xlsx",
        "disputes_board_short_link": "bnV8zbpJ",
        "audit_base": r"X:\ie",
        "departments": {"IE": {"label": "IE"},
                        "OC": {"label": "OC", "audit_base": str(tmp_path)}},
    }
    monkeypatch.setattr(config, "_read_raw", lambda: dict(cfg))
    monkeypatch.setattr(config, "load_base", lambda: dict(cfg))
    return cfg


def test_the_base_franchise_keeps_the_shared_records(two_franchises):
    eff = config.load_for("IE")
    assert eff["dispute_tracker_path"] == r"X:\shared\Dispute Tracker.xlsx"
    assert eff["disputes_board_short_link"] == "bnV8zbpJ"


def test_another_franchise_does_not_inherit_records(two_franchises):
    """The bug this exists for: OC opened IE's tracker and pulled IE's
    disputes board, so two offices wrote one file."""
    eff = config.load_for("OC")
    assert eff["dispute_tracker_path"] == ""
    assert eff["disputes_board_short_link"] == ""


def test_credentials_still_inherit(two_franchises):
    """Blank-inherits stays right for things OC genuinely shares - it
    uses IE's Trello account, so only the RECORDS are un-inherited."""
    two_franchises["trello_token"] = "tok"
    assert config.load_for("OC")["trello_token"] == "tok"


def test_the_base_does_not_move_when_you_switch_offices(two_franchises):
    """It was derived as "whoever is active", so switching to OC made OC
    the base - and IE became the one that inherited."""
    two_franchises["active_department"] = "OC"
    assert config.base_department() == "IE"
    assert config.load_for("OC")["dispute_tracker_path"] == ""


def test_a_blank_tracker_resolves_to_this_franchises_own(two_franchises,
                                                         monkeypatch):
    import dispute_tracker as dt
    monkeypatch.setattr(config, "load", lambda: config.load_for("OC"))
    monkeypatch.setattr(config, "active_department", lambda: "OC")
    p = dt.path()
    assert p.endswith("Dispute Tracker.xlsx")
    assert "shared" not in p


def test_no_board_syncs_nothing_rather_than_someone_elses(two_franchises,
                                                          monkeypatch):
    import sys

    import dispute_tracker as dt
    monkeypatch.setattr(config, "load", lambda: config.load_for("OC"))
    monkeypatch.setattr(config, "active_department", lambda: "OC")

    # If the guard ever fails, this must FAIL rather than quietly dial
    # Trello - a test that reaches the network hangs instead of telling
    # you what broke.
    class _NoNetwork:
        @staticmethod
        def api_get(*a, **k):
            raise AssertionError("synced with no board configured")

    monkeypatch.setitem(sys.modules, "trello_client", _NoNetwork)

    assert dt.configured_board_link() == ""
    res = dt.sync_from_trello_board()
    assert res["no_board"] is True
    assert res["added"] == 0


def test_shell_notifies_long_lived_panels_after_office_switch(monkeypatch):
    import home_web

    calls = []

    class _Sub:
        def _department_changed(self):
            calls.append("changed")

    api = home_web.HomeApi.__new__(home_web.HomeApi)
    api._subs = {"pipeline": _Sub()}
    api._counts_cache = {"pipeline": 1}
    api.department_state = lambda: {
        "departments": [{"key": "IE"}, {"key": "OC"}]}
    monkeypatch.setattr(config, "active_department", lambda: "IE")
    monkeypatch.setattr(config, "set_active_department", lambda key: key == "OC")
    monkeypatch.setattr(home_web, "_invalidate_scoped_caches", lambda: None)

    result = home_web.HomeApi.switch_department(api, "OC")

    assert result == {"ok": True, "switched_to": "OC", "reload": True}
    assert calls == ["changed"]
    assert api._counts_cache is None
