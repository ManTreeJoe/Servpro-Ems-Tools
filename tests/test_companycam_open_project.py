import audit_web
import trello_client as tc


def test_open_project_reads_intake_attachment(monkeypatch):
    monkeypatch.setattr(audit_web.persistence, 'get_trello_card_id', lambda _: 'test-card')
    monkeypatch.setattr(tc, 'get_card_lite', lambda _: {'desc': ''})
    monkeypatch.setattr(tc, 'get_card', lambda _: {'desc': '', 'attachments': [
        {'url': 'https://app.companycam.com/projects/1234'}]})
    opened = []
    monkeypatch.setattr(audit_web.dept_browser, 'open_url', lambda url: opened.append(url))
    assert object.__new__(audit_web.Api).open_companycam_link('Test customer')
    assert opened == ['https://app.companycam.com/projects/1234']


def test_open_project_uses_selected_card_not_name_pin(monkeypatch):
    import pipeline_web
    monkeypatch.setattr(audit_web.persistence, 'get_trello_card_id', lambda _: (_ for _ in ()).throw(AssertionError('name lookup must not replace exact card')))
    fetched = []
    monkeypatch.setattr(tc, 'get_card', lambda card: fetched.append(card) or {'attachments': [{'url': 'https://app.companycam.com/projects/4321'}]})
    opened = []
    monkeypatch.setattr(audit_web.dept_browser, 'open_url', lambda url: opened.append(url))
    api = pipeline_web.Api()
    monkeypatch.setattr(api, '_audit_api', lambda: object.__new__(audit_web.Api))
    assert api.open_companycam_link('Similar name', 'exact-contents-card')
    assert fetched == ['exact-contents-card']
    assert opened == ['https://app.companycam.com/projects/4321']
