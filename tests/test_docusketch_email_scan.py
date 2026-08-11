"""Docusketch delivery emails close the request they name.

The parsing is backwards on purpose: instead of learning Docusketch's
template and pulling a name out of it, this asks which of the jobs we
are ALREADY waiting on appears in the email. Their template is theirs
to change — a subject regex breaks silently the day they reword it and
the tracker just stops closing — whereas matching our own list keeps
working as long as the name is in there somewhere.
"""
import pytest

import docusketch_email_scan as des


REAL_BODY = (
    "<http://2uil.mj.am/lnk/AAA/1/xyz/aHR0cHM6Ly9kb2N1c2tldGNoLmNvbS8> "
    "<https://2uil.mj.am/img2/2uil/74f9bb92/content> "
    "Interior sketch request for project 5193826 {verb} "
    "Dear customer, Your sketch request has been {verb} and added to your "
    "project. You can find your sketch request details below: "
    "Request ID 3490065 Request date 2026-08-07 Project ID 5193826 "
    "Project name {name} Sketch type XACTIMATE Sketch "
    "Download file Open 360 tour You may now download your sketch")


def _msg(subject=None, name="Hilaflor hernandez", verb="delivered",
         addr="help@docusketch.com", mid="m1", body=None):
    """A message shaped like the real thing: the job name lives in the
    BODY behind ~250 characters of tracking URLs, and the subject only
    carries DocuSketch's own project number."""
    if subject is None:
        subject = f"Sketch request for the project 5193826 {verb}"
    if body is None:
        body = REAL_BODY.format(verb=verb, name=name)
    return {
        "id": mid, "subject": subject, "bodyPreview": body,
        "receivedDateTime": "2026-08-11T10:00:00Z",
        "from": {"emailAddress": {"address": addr, "name": "DocuSketch"}},
    }


# ── sender ─────────────────────────────────────────────────────────────
def test_recognises_the_docusketch_sender():
    assert des.is_docusketch(_msg())
    assert des.is_docusketch(_msg(addr="noreply@mail.docusketch.com"))


def test_ignores_everything_else():
    assert not des.is_docusketch(_msg(addr="adjuster@aaa.com"))
    assert not des.is_docusketch({})


# ── name matching ──────────────────────────────────────────────────────
def test_matches_a_job_named_in_the_subject():
    s = des.name_in_text("Smith, David - Mercury",
                         "Your sketch for Smith David Mercury is ready")
    assert s > 0


def test_word_order_and_punctuation_do_not_matter():
    assert des.name_in_text("Smith, David - Mercury",
                            "David Smith (Mercury) — sketch complete") > 0


def test_every_token_must_be_present():
    """Matching on the surname alone would close the wrong Smith. These
    emails mark a job DELIVERED, so a false positive is expensive."""
    assert des.name_in_text("Smith, David - Mercury",
                            "Sketch ready for Smith, Christine") == 0


def test_short_tokens_are_ignored():
    """A two-letter token would hit every email in the inbox."""
    assert des._tokens("Smith, DJ - AAA") == ["smith", "aaa"]


def test_no_match_scores_zero():
    assert des.name_in_text("Smith, David", "nothing relevant here") == 0
    assert des.name_in_text("", "anything") == 0


def test_longer_full_matches_outrank_shorter_ones():
    text = "Sketch for Smith, David - Mercury is ready"
    a = des.name_in_text("Smith, David - Mercury", text)
    b = des.name_in_text("Smith, David", text)
    assert a > b


# ── ties defer to a human ──────────────────────────────────────────────
def test_an_ambiguous_email_matches_nothing():
    """A client and their second claim both appearing is exactly when a
    guess resolves the wrong one."""
    name, score = des.best_match(
        "sketch ready", ["Smith, David", "Jones, Amy"])
    assert name is None
    # both absent → no match, and equally so
    name2, _ = des.best_match("Smith David and Smith David",
                              ["Smith, David", "Smith David"])
    assert name2 is None


def test_the_clear_winner_is_returned():
    name, score = des.best_match(
        "Sketch for Smith, David - Mercury attached",
        ["Smith, David - Mercury", "Jones, Amy - AAA"])
    assert name == "Smith, David - Mercury" and score > 0


# ── the scan ───────────────────────────────────────────────────────────
@pytest.fixture
def tracker(monkeypatch, tmp_path):
    """Two pending requests and a recording resolve()."""
    import docusketch_requests as dr
    import paths
    monkeypatch.setattr(paths, "data", lambda n: str(tmp_path / n))
    monkeypatch.setattr(dr, "pending_requests", lambda: [
        {"card_id": "c1", "client_name": "Smith, David - Mercury"},
        {"card_id": "c2", "client_name": "Jones, Amy - AAA"},
    ])
    done = []
    monkeypatch.setattr(dr, "resolve", lambda cid: done.append(cid))
    monkeypatch.setattr(des, "_seen", lambda: [])
    monkeypatch.setattr(des, "_mark_seen", lambda ids: None)
    return done


def test_scan_resolves_the_named_request(tracker):
    res = des.scan_inbox(messages=[
        _msg(name="Smith, David - Mercury")])
    assert res["ok"] and res["matched"] == 1 and res["resolved"] == 1
    assert tracker == ["c1"]


def test_dry_run_changes_nothing(tracker):
    res = des.scan_inbox(apply=False, messages=[
        _msg(name="Jones, Amy - AAA")])
    assert res["matched"] == 1 and res["resolved"] == 0
    assert tracker == []


def test_non_docusketch_mail_is_skipped(tracker):
    res = des.scan_inbox(messages=[
        _msg(name="Smith, David - Mercury", addr="adjuster@aaa.com")])
    assert res["checked"] == 0 and res["matched"] == 0
    assert tracker == []


def test_an_unmatched_email_is_reported_not_resolved(tracker):
    res = des.scan_inbox(messages=[_msg(name="Nobody We Track")])
    assert res["matched"] == 0
    assert len(res["unmatched"]) == 1
    assert tracker == []


def test_already_seen_messages_are_skipped(monkeypatch, tracker):
    monkeypatch.setattr(des, "_seen", lambda: ["m1"])
    res = des.scan_inbox(messages=[
        _msg(name="Smith, David - Mercury")])
    assert res["checked"] == 0 and tracker == []


def test_an_unmatched_email_is_not_marked_seen(monkeypatch):
    """It may match once the request is actually raised, so it has to
    stay eligible for the next scan."""
    import docusketch_requests as dr
    monkeypatch.setattr(dr, "pending_requests", lambda: [])
    marked = []
    monkeypatch.setattr(des, "_seen", lambda: [])
    monkeypatch.setattr(des, "_mark_seen", lambda ids: marked.extend(ids))
    des.scan_inbox(messages=[_msg(name="Nobody We Track")])
    assert marked == []


def test_a_resolve_failure_is_reported_not_swallowed(monkeypatch, tracker):
    import docusketch_requests as dr

    def _boom(cid):
        raise RuntimeError("tracker locked")
    monkeypatch.setattr(dr, "resolve", _boom)
    res = des.scan_inbox(messages=[
        _msg(name="Smith, David - Mercury")])
    assert res["matched"] == 1 and res["resolved"] == 0
    assert "tracker locked" in res["results"][0]["error"]


def test_outlook_being_unavailable_is_not_fatal(monkeypatch):
    import docusketch_requests as dr
    monkeypatch.setattr(dr, "pending_requests", lambda: [])
    import builtins
    real = builtins.__import__

    def _no_outlook(name, *a, **k):
        if name == "outlook_local":
            raise ImportError("no Outlook on this machine")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", _no_outlook)
    res = des.scan_inbox()
    assert res["ok"] is False and "Outlook" in res["error"]


# ── what the real emails taught me ─────────────────────────────────────
def test_created_notices_are_ignored():
    """"created" and "delivered" use the IDENTICAL template and both
    arrive for every job. Acting on "created" would close the tracker
    the moment the sketch was ordered — exactly backwards."""
    assert des.parse_delivery(_msg(verb="created")) is None
    assert des.parse_delivery(_msg(verb="delivered")) is not None


def test_created_notice_resolves_nothing(tracker):
    res = des.scan_inbox(messages=[
        _msg(name="Smith, David - Mercury", verb="created")])
    assert res["checked"] == 0 and res["matched"] == 0
    assert tracker == []


def test_the_structured_fields_are_parsed():
    got = des.parse_delivery(_msg(name="Hilaflor hernandez"))
    assert got["project_name"] == "Hilaflor hernandez"
    assert got["project_id"] == "5193826"
    assert got["request_id"] == "3490065"
    assert got["request_date"] == "2026-08-07"


def test_the_name_is_found_behind_the_tracking_urls():
    """The first ~250 characters are tracking links, so a 255-char
    bodyPreview contains no usable text — the scan reads the full body
    and strips markup and URLs before parsing."""
    body = des.clean_body(REAL_BODY.format(verb="delivered",
                                           name="Hilaflor hernandez"))
    assert "http" not in body
    assert "Project name Hilaflor hernandez" in body


def test_a_multi_word_name_is_not_truncated_at_the_next_label():
    got = des.parse_delivery(_msg(name="Rodriguez Marina & Manuel Alvarez"))
    assert got["project_name"] == "Rodriguez Marina & Manuel Alvarez"


def test_an_invoice_from_the_same_domain_is_not_a_delivery():
    inv = _msg(subject="Invoice Notification", body="Your invoice is ready",
               addr="no-reply@docusketch.com")
    assert des.parse_delivery(inv) is None
