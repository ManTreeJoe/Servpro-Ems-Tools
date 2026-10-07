"""Pinning a provider card must not replace the app's durable job identity."""
import ems_db
import persistence
import trello_client


def test_pin_does_not_create_or_merge_job_from_provider_title(monkeypatch):
    state = {}
    effects = []
    monkeypatch.setattr('division_cards.validate_pin', lambda card, division: card)
    monkeypatch.setattr(ems_db, 'get_links', lambda *a: [{'link_value':'old'}])
    monkeypatch.setattr(persistence, '_load', lambda: state)
    monkeypatch.setattr(persistence, '_save', lambda value: None)
    monkeypatch.setattr(ems_db, 'resolve_and_link', lambda *a, **k: {'canon_key': 'durable-job'})
    monkeypatch.setattr(ems_db, 'remove_link', lambda *a, **k: effects.append(('remove', a)))
    monkeypatch.setattr(ems_db, 'set_link', lambda *a, **k: effects.append(('link', a)))
    monkeypatch.setattr(ems_db, 'upsert_job', lambda *a, **k: effects.append(('create', k)))
    monkeypatch.setattr(ems_db, 'add_alias', lambda *a, **k: effects.append(('alias', a)))
    monkeypatch.setattr(ems_db, 'merge_jobs', lambda *a, **k: effects.append(('merge', a)))
    monkeypatch.setattr(trello_client, 'get_card', lambda *a, **k: {'name': 'Patterson, Janette- AAA'})

    persistence.set_trello_card_ids('Janette Patterson', ['card-1'])

    assert effects == [('remove', ('durable-job', 'trello_card', 'old')),
                       ('link', ('durable-job', 'trello_card', 'card-1'))]
    assert persistence.get_trello_card_ids('Janette Patterson') == ['card-1']
