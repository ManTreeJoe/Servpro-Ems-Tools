from unittest.mock import Mock
import pytest
import persistence
import ems_db
import trello_client
import audit_web


def test_legacy_contents_pin_rejected_before_any_write(monkeypatch):
    save, remove, link = Mock(), Mock(), Mock()
    monkeypatch.setattr(persistence, '_load', lambda: {})
    monkeypatch.setattr(persistence, '_save', save)
    monkeypatch.setattr(ems_db, 'resolve_and_link', lambda *a, **k: {'canon_key':'fixture'})
    monkeypatch.setattr(ems_db, 'remove_link', remove)
    monkeypatch.setattr(ems_db, 'set_link', link)
    monkeypatch.setattr(trello_client, 'get_card_lite', lambda _: {'id':'contents-card','idBoard':'contents'})
    monkeypatch.setattr(trello_client, 'list_boards', lambda: [{'id':'contents','name':'CONTENTS'}])
    with pytest.raises(ValueError, match='CONTENTS'):
        persistence.set_trello_card_ids('Fixture', ['contents-card'])
    save.assert_not_called(); remove.assert_not_called(); link.assert_not_called()


def test_multiple_unmarked_links_do_not_choose_oldest(monkeypatch):
    monkeypatch.setattr(ems_db, 'find_job_by_name', lambda _: {'canon_key':'fixture'})
    monkeypatch.setattr(ems_db, 'get_links', lambda key, kind: [
        {'link_value':'old'}, {'link_value':'new'}] if kind=='trello_card' else [])
    result = audit_web.Api().crm_division_trello_cards('Fixture')
    ems = next(c for c in result['cards'] if c['division']=='EMS')
    assert ems['card_id']==''
    assert ems['ambiguous'] is True


def test_valid_pin_preserves_secondary_placement(monkeypatch):
    writes, removed = [], []
    monkeypatch.setattr('division_cards.validate_pin', lambda card, division: card)
    monkeypatch.setattr(persistence, '_load', lambda: {})
    monkeypatch.setattr(persistence, '_save', lambda _: None)
    monkeypatch.setattr(ems_db, 'resolve_and_link', lambda *a, **k: {'canon_key':'fixture'})
    monkeypatch.setattr(ems_db, 'get_links', lambda *a: [
        {'link_value':'old-primary'}, {'link_value':'estimating-copy','metadata':{'primary':False,'purpose':'temporary'}}])
    monkeypatch.setattr(ems_db, 'remove_link', lambda *a: removed.append(a))
    monkeypatch.setattr(ems_db, 'set_link', lambda *a, **k: writes.append((a,k)))
    persistence.set_trello_card_ids('Fixture', ['new-primary'])
    assert removed == [('fixture','trello_card','old-primary')]
    assert writes[0][1]['metadata']['primary'] is True


def test_unverifiable_pin_leaves_state_unchanged(monkeypatch):
    save = Mock()
    monkeypatch.setattr(persistence, '_save', save)
    monkeypatch.setattr('division_cards.validate_pin', Mock(side_effect=ValueError('Cannot verify')))
    with pytest.raises(ValueError):
        persistence.set_trello_card_ids('Fixture', ['offline'])
    save.assert_not_called()


def test_explicit_primary_wins_over_unmarked_legacy_link(monkeypatch):
    monkeypatch.setattr(ems_db, 'find_job_by_name', lambda _: {'canon_key':'fixture'})
    monkeypatch.setattr(ems_db, 'get_links', lambda key, kind: [
        {'link_value':'old'}, {'link_value':'chosen','metadata':{'primary':True}}] if kind=='trello_card' else [])
    result = audit_web.Api().crm_division_trello_cards('Fixture')
    ems = next(c for c in result['cards'] if c['division']=='EMS')
    assert ems['card_id'] == 'chosen' and not ems['ambiguous']
