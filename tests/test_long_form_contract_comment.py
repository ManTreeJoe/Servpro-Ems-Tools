import audit_web


def test_contract_comment_uses_deposit_then_splits_remainder():
    r = audit_web.Api.long_form_contract_comment_text("4,928.11", "1,000")
    assert r["ok"]
    assert r["text"] == (
        "Long Form contract total - 4,928.11\n\n"
        "Deposit - 1,000.00\n\n"
        "1st day of job - 1,964.05\n\n"
        "Final day / eq pulled - 1,964.06\n\n"
        "@nathan_bupte")


def test_final_payment_gets_the_rounding_penny():
    r = audit_web.Api.long_form_contract_comment_text("100.01", "0")
    assert r["first"] == "50.00"
    assert r["final"] == "50.01"


def test_deposit_cannot_exceed_total():
    r = audit_web.Api.long_form_contract_comment_text("500", "1000")
    assert not r["ok"] and "cannot exceed" in r["error"]


def test_post_uses_the_exact_preview(monkeypatch):
    import trello_client as tc
    sent = []
    monkeypatch.setattr(tc, "post_comment", lambda card, text: sent.append((card, text)) or {"id": "a1"})
    monkeypatch.setattr(tc, "get_card_lite", lambda card: {"desc": ""})
    api = object.__new__(audit_web.Api)
    preview = api.long_form_contract_comment_text("4928.11", "1000")
    posted = api.post_long_form_contract_comment("card1", "4928.11", "1000")
    assert posted["ok"] and posted["action_id"] == "a1"
    assert sent == [("card1", preview["text"])]


def test_post_opens_the_xa_link_resolved_from_the_same_card(monkeypatch):
    import trello_client as tc
    opened = []
    monkeypatch.setattr(tc, "post_comment", lambda *a: {"id": "a1"})
    monkeypatch.setattr(tc, "get_card_lite", lambda card: {"desc": "card"})
    monkeypatch.setattr(tc, "card_xa_link", lambda card: "https://xa.example/job")
    monkeypatch.setattr(audit_web.dept_browser, "open_url", opened.append)
    api = object.__new__(audit_web.Api)
    r = api.post_long_form_contract_comment("card1", "4928.11", "1000")
    assert r["xa_opened"] is True
    assert opened == ["https://xa.example/job"]


def test_edited_comment_is_the_exact_text_posted(monkeypatch):
    import trello_client as tc
    sent = []
    monkeypatch.setattr(tc, "post_comment", lambda card, text: sent.append(text) or {})
    monkeypatch.setattr(tc, "get_card_lite", lambda card: {"desc": ""})
    api = object.__new__(audit_web.Api)
    edited = "Edited total\n\nEdited payment plan\n\n@nathan_bupte"
    r = api.post_long_form_contract_comment("card1", "4928.11", "1000", edited)
    assert r["ok"] and r["text"] == edited
    assert sent == [edited]
