"""APA new-doc carry-forward rules (user 2026-06-24):
  • every EXTENDED job rolls into the new doc — even if highlighted;
  • an UPLOADED job is done and must NOT carry — even if its row is
    still highlighted yellow (stale highlight used to drag it forward).
Round-trips through real write_doc / parse_existing_doc so the .docx
status suffix + highlight survive exactly as in production.
"""
import datetime as dt
import apa_web
import apa_logic as apa


def _run(tmp_path, prior_items):
    """Write a prior-day doc with `prior_items` ({section: [(text, hl)]}),
    then create today's doc and return its parsed {section: [(text, hl)]}."""
    today = dt.date(2026, 6, 24)
    yest = today - dt.timedelta(days=1)
    paths = {
        today: str(tmp_path / "today.docx"),
        yest:  str(tmp_path / "yest.docx"),
    }

    orig = apa.doc_path_for_today

    def fake_path(d=None):
        dd = d or dt.date.today()
        if isinstance(dd, dt.datetime):
            dd = dd.date()
        return paths.get(dd, str(tmp_path / f"{dd}.docx"))

    apa.doc_path_for_today = fake_path
    try:
        apa.write_doc(paths[yest], yest, prior_items)
        # refresh_lanes=False: this exercises carry-forward, and the
        # lane re-check is a live Trello round trip per item.
        res = apa_web.Api().create_doc(today.isoformat(), True,
                                       refresh_lanes=False)
        assert res.get("ok"), res
        return apa.parse_existing_doc(paths[today]) or {}
    finally:
        apa.doc_path_for_today = orig


def _flat(parsed):
    return {t for items in parsed.values() for (t, _hl) in items}


def test_extended_carries_uploaded_dropped(tmp_path):
    sec = apa.SECTION_ORDER[0]
    prior = {sec: [
        ("Smith, John - AAA-extended", False),     # extended → carry
        ("Kim, Lee - AAA-extended", True),          # extended + highlight → carry
        ("Doe, Jane - Mercury-uploaded", False),    # uploaded → drop
        ("Roe, Ann - SF-uploaded", True),           # uploaded + STALE highlight → drop
        ("Brown, Bob - SF-pending", True),          # pending → carry
    ]}
    out = _flat(_run(tmp_path, prior))
    # A new day restamps every carried item back to pending (the status
    # described YESTERDAY), so assert the job carried, not its old suffix.
    assert "Smith, John - AAA-pending" in out
    assert "Kim, Lee - AAA-pending" in out
    assert "Brown, Bob - SF-pending" in out
    assert not any(t.endswith("-extended") for t in out)
    # The two uploaded jobs must NOT appear in the new doc.
    assert not any("uploaded" in t.lower() for t in out)
    assert "Doe, Jane - Mercury-uploaded" not in out
    assert "Roe, Ann - SF-uploaded" not in out
