"""Navigation query regression tests with no application/provider initialization."""
import importlib.util
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def lookup(monkeypatch):
    calls = []
    rows = [{'card_id': 'a' * 24, 'payload': {}}]

    def rest(method, table, **kwargs):
        assert method == 'GET'
        assert table == 'hub_trello_mirror_cards'
        calls.append(kwargs['params'])
        return rows

    monkeypatch.setitem(__import__('sys').modules, 'supabase_client',
                        SimpleNamespace(rest=rest, interactive_requests=lambda **kw: nullcontext()))
    spec = importlib.util.spec_from_file_location('isolated_notification_navigation',
        Path(__file__).resolve().parents[1] / 'notification_navigation.py')
    nav = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(nav)
    return nav, calls, rows


def test_full_id_avoids_payload_or_scan(lookup):
    nav, calls, rows = lookup
    assert nav._authorized_card('a' * 24) == rows[0]
    assert calls == [{'select': 'card_id,board_id,payload',
                      'card_id': 'eq.' + 'a' * 24, 'limit': '2'}]


def test_short_link_keeps_alias_lookup(lookup):
    nav, calls, _ = lookup
    nav._authorized_card('Abcd1234')
    assert 'payload->>shortLink.eq.Abcd1234' in calls[0]['or']
    assert 'payload->>shortUrl.eq.https://trello.com/c/Abcd1234' in calls[0]['or']


@pytest.mark.parametrize('count', [0, 2])
def test_unavailable_or_ambiguous_card_stays_blocked(lookup, count):
    nav, _, rows = lookup
    rows[:] = [{'card_id': 'a' * 24}] * count
    with pytest.raises(ValueError, match='not available'):
        nav._authorized_card('a' * 24)


def test_invalid_id_never_reads(lookup):
    nav, calls, _ = lookup
    with pytest.raises(ValueError):
        nav._authorized_card('../invalid')
    assert calls == []
