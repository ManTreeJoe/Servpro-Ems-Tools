"""One job, two CompanyCam projects, photos on only one of them.

Bell Mountain, live: "Menifee Union School District (Bell Mountain ) -
8/14" had 0 photos and "Bell Mountain Middle School" had 29, both at
28525 La Piedra Rd. The job is named after its Trello card, so the name
match scored 100 against the EMPTY one — exactly right, and useless. The
pull then reported no photos for a job that plainly had them.

Address is the signal that resolves it: two projects at one address are
the same physical loss whatever they are called. The switch is OFFERED,
never made automatically — which project is really the job is a judgement,
and the photo counts are the evidence to make it on.
"""
import pytest

import companycam_api as cc
import companycam_web_api as cw


ADDR = "28525 La Piedra Rd, Menifee, CA, 92584"


def _proj(pid, name, addr=ADDR):
    return {"id": pid, "name": name,
            "address": {"street_address_1": addr.split(",")[0].strip(),
                        "city": "Menifee", "state": "CA",
                        "postal_code": "92584"}}


@pytest.fixture
def cam(monkeypatch):
    state = {
        "projects": [
            _proj("112272489", "Menifee Union School District (Bell Mountain ) - 8/14"),
            _proj("112251669", "Bell Mountain Middle School"),
        ],
        "photos": {"112272489": [], "112251669": [{"id": f"p{i}"} for i in range(29)]},
        "queries": [],
    }

    def _list(query="", **kw):
        state["queries"].append(query)
        q = (query or "").lower()
        return [p for p in state["projects"]
                if q in p["name"].lower()
                or q in (p["address"]["street_address_1"] or "").lower()]

    monkeypatch.setattr(cc, "list_projects", _list)
    monkeypatch.setattr(cc, "list_project_photos",
                        lambda pid, **kw: list(state["photos"].get(str(pid), [])))
    monkeypatch.setattr(
        cc, "get_project",
        lambda pid: next((cc._shape(p) for p in state["projects"]
                          if p["id"] == str(pid)), None))
    return state


# ── address matching ─────────────────────────────────────────────────
def test_addresses_compare_past_punctuation_and_case():
    assert cc._addr_key("28525 La Piedra Rd, Menifee, CA, 92584") == \
           cc._addr_key("28525 LA PIEDRA RD,  Menifee CA 92584")


def test_siblings_finds_the_other_project_at_the_address(cam):
    sibs = cc.siblings_at_address(ADDR, "112272489")
    assert [s["id"] for s in sibs] == ["112251669"]


def test_siblings_never_returns_the_project_you_asked_about(cam):
    assert all(s["id"] != "112251669"
               for s in cc.siblings_at_address(ADDR, "112251669"))


def test_siblings_searches_by_street_not_the_whole_line(cam):
    """The full "street, city, state, zip" line matches nothing; the
    street does, and it is one call rather than listing every project."""
    cc.siblings_at_address(ADDR, "112272489")
    assert cam["queries"] == ["28525 La Piedra Rd"]


def test_a_different_address_is_not_a_sibling(cam, monkeypatch):
    cam["projects"].append(_proj("999", "Somewhere Else", "1 Other St"))
    monkeypatch.setattr(cc, "list_projects",
                        lambda query="", **kw: list(cam["projects"]))
    assert all(s["id"] != "999"
               for s in cc.siblings_at_address(ADDR, "112272489"))


def test_no_address_means_no_guessing(cam):
    assert cc.siblings_at_address("", "112272489") == []
    assert cc.siblings_at_address(None, "1") == []


# ── what the probe offers ────────────────────────────────────────────
@pytest.fixture
def api():
    return cw.CompanyCamApi.__new__(cw.CompanyCamApi)


def test_the_empty_project_offers_the_one_with_the_photos(cam, api):
    alts = api._cc_alternates("112272489")
    assert len(alts) == 1
    assert alts[0]["name"] == "Bell Mountain Middle School"
    assert alts[0]["count"] == 29


def test_a_sibling_with_no_photos_is_not_offered(cam, api):
    """Offering an equally empty project would just move the problem."""
    assert api._cc_alternates("112251669") == []


def test_alternates_are_ordered_by_photo_count(cam, api):
    cam["projects"].append(_proj("3", "Third Project"))
    cam["photos"]["3"] = [{"id": "x"} for i in range(50)]
    got = api._cc_alternates("112272489")
    assert [a["count"] for a in got] == [50, 29]


def test_an_unreadable_project_is_not_an_error(api, monkeypatch):
    monkeypatch.setattr(cc, "get_project", lambda pid: None)
    assert api._cc_alternates("nope") == []


def test_probe_only_looks_for_alternates_when_there_are_no_photos(api,
                                                                  monkeypatch):
    """The normal path must not pay for this."""
    called = []
    monkeypatch.setattr(cc, "is_configured", lambda: True)
    monkeypatch.setattr(cc, "probe_new", lambda pid: {"count": 5,
                                                      "uploaders": []})
    monkeypatch.setattr(cw.CompanyCamApi, "_cc_resolve",
                        lambda self, c, cid="": ("112272489", "x"))
    monkeypatch.setattr(cw.CompanyCamApi, "_cc_alternates",
                        lambda self, pid: called.append(pid) or [])
    res = api.companycam_probe("Bell Mountain")
    assert res["count"] == 5
    assert called == [], "no sibling lookup when photos were found"
    assert "alternates" not in res


def test_probe_surfaces_alternates_when_empty(api, monkeypatch):
    monkeypatch.setattr(cc, "is_configured", lambda: True)
    monkeypatch.setattr(cc, "probe_new", lambda pid: {"count": 0,
                                                      "uploaders": []})
    monkeypatch.setattr(cw.CompanyCamApi, "_cc_resolve",
                        lambda self, c, cid="": ("112272489", "the empty one"))
    monkeypatch.setattr(
        cw.CompanyCamApi, "_cc_alternates",
        lambda self, pid: [{"id": "112251669", "name": "Bell Mountain Middle School",
                            "count": 29, "approx": False, "address": ADDR}])
    res = api.companycam_probe("Bell Mountain")
    assert res["count"] == 0
    assert res["alternates"][0]["count"] == 29
    assert res["project_id"] == "112272489"


# ── the UI must offer, not switch ────────────────────────────────────
def _detail_js():
    import io
    import os
    return io.open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "web_shared", "audit_detail.js"), encoding="utf-8").read()


def test_the_switch_is_offered_before_the_pull_is_planned():
    """Planning against the empty project is what produced "no photos"."""
    js = _detail_js()
    body = js[js.index('} else if (action === "cc-pull") {'):]
    body = body[:body.index("companycam_plan_pull")]
    assert "ccOfferAlternate" in body


def test_switching_pins_the_chosen_project():
    js = _detail_js()
    body = js[js.index("function ccOfferAlternate"):]
    body = body[:body.index("\n  function ccManualPick")]
    assert "companycam_pin" in body
    assert "cc-alt-keep" in body, "keeping the matched project stays possible"


def test_the_offer_shows_the_photo_counts():
    """The counts are the evidence — an unlabelled list of names asks the
    user to guess the thing the tool already knows."""
    js = _detail_js()
    body = js[js.index("function ccOfferAlternate"):]
    body = body[:body.index("\n  function ccManualPick")]
    assert "a.count" in body
