"""Carried-forward jobs Trello can't place must be REPORTED, not hidden.

`refresh_doc_lanes` routes what it can from each job's live Trello lane.
Anything it can't — no pinned card, no readable lane, a lane that maps to
no APA section — used to stay silently in yesterday's section, which
nobody notices until the job is filed wrong. It now comes back in
`unrouted` so the UI can ask where those jobs should go.
"""
import datetime as dt

import apa_logic as apa
import apa_web
import persistence
import trello_client


def _by_text(unrouted):
    return {u["text"]: u for u in unrouted}


def test_every_kind_of_unroutable_item_is_reported(tmp_path, monkeypatch):
    today = dt.date(2026, 6, 25)
    path = str(tmp_path / "t.docx")
    monkeypatch.setattr(apa, "doc_path_for_today", lambda d=None: path)

    pins = {
        apa._franchise_key("Smith, John - AAA"): "cardSC",     # routes fine
        apa._franchise_key("Doe, Jane - Mercury"): "cardBLANK",  # no lane
        apa._franchise_key("Roe, Ann - SF"): "cardWEIRD",      # unmapped lane
        # "Lee, Amy" has no pin at all
    }
    monkeypatch.setattr(persistence, "get_trello_card_id",
                        lambda key: pins.get(key, ""))
    lanes = {
        "cardSC":    "SERVICE CALLS - Program",
        "cardBLANK": "",
        "cardWEIRD": "Some Random Lane",
    }
    monkeypatch.setattr(trello_client, "get_card_lane",
                        lambda cid: lanes.get(cid, ""))

    start = apa.SECTION_ORDER[0]
    apa.write_doc(path, today, {start: [
        ("Smith, John - AAA-extended", False),
        ("Doe, Jane - Mercury-pending", True),
        ("Roe, Ann - SF-extended", False),
        ("Lee, Amy - USAA-pending", True),
    ]})

    res = apa_web.Api().refresh_doc_lanes(today.isoformat())
    assert res["ok"], res

    got = _by_text(res["unrouted"])
    # The one that routed is NOT reported.
    assert "Smith, John - AAA-extended" not in got
    assert got["Doe, Jane - Mercury-pending"]["reason"] == "no_lane"
    assert got["Roe, Ann - SF-extended"]["reason"] == "unmapped_lane"
    assert got["Lee, Amy - USAA-pending"]["reason"] == "no_card"
    # Each carries the section it's stuck in, so the UI can default to it.
    assert got["Lee, Amy - USAA-pending"]["section"] == start


def test_a_fully_routed_doc_reports_nothing(tmp_path, monkeypatch):
    today = dt.date(2026, 6, 25)
    path = str(tmp_path / "t.docx")
    monkeypatch.setattr(apa, "doc_path_for_today", lambda d=None: path)
    monkeypatch.setattr(persistence, "get_trello_card_id", lambda key: "cardSC")
    monkeypatch.setattr(trello_client, "get_card_lane",
                        lambda cid: "SERVICE CALLS - Program")
    apa.write_doc(path, today, {apa.SECTION_ORDER[0]: [
        ("Smith, John - AAA-extended", False)]})

    res = apa_web.Api().refresh_doc_lanes(today.isoformat())
    assert res["ok"] and res["unrouted"] == []


def test_an_item_already_in_the_right_section_is_not_unrouted(
        tmp_path, monkeypatch):
    # Routed correctly but not MOVED (already there) — still not a
    # question for the user.
    today = dt.date(2026, 6, 25)
    path = str(tmp_path / "t.docx")
    monkeypatch.setattr(apa, "doc_path_for_today", lambda d=None: path)
    monkeypatch.setattr(persistence, "get_trello_card_id", lambda key: "cardSC")
    monkeypatch.setattr(trello_client, "get_card_lane",
                        lambda cid: "SERVICE CALLS - Program")
    apa.write_doc(path, today, {apa.SEC_EST_SERVICE_CALL: [
        ("Smith, John - AAA-extended", False)]})

    res = apa_web.Api().refresh_doc_lanes(today.isoformat())
    assert res["ok"] and res["moved"] == 0
    assert res["unrouted"] == []


def test_a_trello_outage_reports_every_item_rather_than_none(
        tmp_path, monkeypatch):
    # If Trello is down, get_card_lane raises. The items are unplaced, so
    # they must be surfaced — silence would read as "all routed".
    today = dt.date(2026, 6, 25)
    path = str(tmp_path / "t.docx")
    monkeypatch.setattr(apa, "doc_path_for_today", lambda d=None: path)
    monkeypatch.setattr(persistence, "get_trello_card_id", lambda key: "cardSC")

    def boom(_cid):
        raise RuntimeError("trello down")
    monkeypatch.setattr(trello_client, "get_card_lane", boom)

    apa.write_doc(path, today, {apa.SECTION_ORDER[0]: [
        ("Smith, John - AAA-extended", False)]})

    res = apa_web.Api().refresh_doc_lanes(today.isoformat())
    assert res["ok"]
    assert [u["reason"] for u in res["unrouted"]] == ["no_lane"]


def test_unrouted_items_keep_their_place_in_the_doc(tmp_path, monkeypatch):
    # Reporting must not move anything on its own.
    today = dt.date(2026, 6, 25)
    path = str(tmp_path / "t.docx")
    monkeypatch.setattr(apa, "doc_path_for_today", lambda d=None: path)
    monkeypatch.setattr(persistence, "get_trello_card_id", lambda key: "")
    start = apa.SECTION_ORDER[0]
    apa.write_doc(path, today, {start: [("Lee, Amy - USAA-pending", True)]})

    apa_web.Api().refresh_doc_lanes(today.isoformat())
    parsed = apa.parse_existing_doc(path)
    assert parsed[start][0][0] == "Lee, Amy - USAA-pending"
    assert parsed[start][0][1] is True     # highlight preserved
