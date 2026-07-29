"""APA "refresh lanes from Trello" — re-route carried items to the section
matching each job's CURRENT Trello lane (new-day cleanup).

A carried-forward item keeps yesterday's section; refresh_doc_lanes pulls
its pinned card's live lane and MOVES it to the matching APA section.
Items with no pin or an unmapped lane stay put. Mocks Trello +
persistence so it's deterministic and offline.
"""
import datetime as dt
import apa_web
import apa_logic as apa
import persistence
import trello_client


def _section_of(parsed, text):
    for sec, items in parsed.items():
        for t, _hl in items:
            if t == text:
                return sec
    return None


def test_refresh_moves_items_to_trello_lane_sections(tmp_path, monkeypatch):
    today = dt.date(2026, 6, 25)
    path = str(tmp_path / "today.docx")

    def fake_path(d=None):
        return path
    monkeypatch.setattr(apa, "doc_path_for_today", fake_path)

    # Card pins: APA franchise key -> card id.
    pins = {
        apa._franchise_key("Smith, John - AAA"): "cardSC",   # → Service Call lane
        apa._franchise_key("Doe, Jane - Mercury"): "cardTBA", # → TBA lane
        apa._franchise_key("Roe, Ann - SF"): "cardJUAN",     # → estimator lane
        # "Lee, Amy" has NO pin → stays put
    }
    monkeypatch.setattr(persistence, "get_trello_card_id",
                        lambda key: pins.get(key, ""))

    lanes = {
        "cardSC":   "SERVICE CALLS - Program",
        "cardTBA":  "TO BE ASSIGNED - Non-Program",
        "cardJUAN": "JUANTES",
    }
    monkeypatch.setattr(trello_client, "get_card_lane",
                        lambda cid: lanes.get(cid, ""))

    # Seed the doc: everything dumped in Final Uploads (the wrong place).
    start = apa.SECTION_ORDER[0]
    seed = {start: [
        ("Smith, John - AAA-extended", False),
        ("Doe, Jane - Mercury-pending", True),
        ("Roe, Ann - SF-extended", False),
        ("Lee, Amy - USAA-pending", True),     # no pin → stays in `start`
    ]}
    apa.write_doc(path, today, seed)

    res = apa_web.Api().refresh_doc_lanes(today.isoformat())
    assert res["ok"], res
    assert res["checked"] == 3        # three pinned items looked up
    assert res["moved"] == 3          # all three re-routed

    parsed = apa.parse_existing_doc(path)
    assert _section_of(parsed, "Smith, John - AAA-extended") == apa.SEC_EST_SERVICE_CALL
    assert _section_of(parsed, "Doe, Jane - Mercury-pending") == apa.SEC_EST_TBA
    assert _section_of(parsed, "Roe, Ann - SF-extended") == "JUAN"
    # Unpinned item never moved.
    assert _section_of(parsed, "Lee, Amy - USAA-pending") == start


def test_refresh_keeps_items_when_lane_unmapped(tmp_path, monkeypatch):
    today = dt.date(2026, 6, 25)
    path = str(tmp_path / "t.docx")
    monkeypatch.setattr(apa, "doc_path_for_today", lambda d=None: path)
    monkeypatch.setattr(persistence, "get_trello_card_id", lambda key: "cardX")
    # A lane that doesn't map to any APA section → item stays.
    monkeypatch.setattr(trello_client, "get_card_lane",
                        lambda cid: "Some Random Lane")
    start = apa.SECTION_ORDER[0]
    apa.write_doc(path, today, {start: [("Smith, John - AAA-pending", True)]})
    res = apa_web.Api().refresh_doc_lanes(today.isoformat())
    assert res["ok"] and res["moved"] == 0
    parsed = apa.parse_existing_doc(path)
    assert _section_of(parsed, "Smith, John - AAA-pending") == start
