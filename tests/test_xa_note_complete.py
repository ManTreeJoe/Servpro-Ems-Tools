import audit_web


def test_xa_note_returns_copies_and_opens_the_complete_comment(monkeypatch):
    import trello_client as tc
    posted, opened = [], []
    monkeypatch.setattr(tc, "post_comment", lambda card, text: posted.append(text) or {"id": "a"})
    monkeypatch.setattr(tc, "get_card_lite", lambda card: {"desc": "card"})
    monkeypatch.setattr(tc, "card_xa_link", lambda card: "https://xa.example/right-job")
    monkeypatch.setattr(audit_web.dept_browser, "open_url", opened.append)
    api = object.__new__(audit_web.Api)

    result = api.post_xa_note("Smith", "Long Form contract total - 4,928.11", "nathan_bupte", "card1")

    assert result["ok"] and result["xa_opened"]
    assert result["comment"] == posted[0]
    assert "XA note" in result["comment"]
    assert "@nathan_bupte" in result["comment"]
    assert "Long Form contract total - 4,928.11" in result["comment"]
    assert opened == ["https://xa.example/right-job"]
