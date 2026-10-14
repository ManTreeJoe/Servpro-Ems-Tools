"""Main placement hydration, isolated projections and no external requests."""
import sqlite3

import pytest

import job_log_projection as projection
from pipeline_web import _job_log_placement_scope, _job_log_for_placement

FULL = 'a' * 24
SHORT = 'AbCd1234'


@pytest.fixture
def conn():
    with sqlite3.connect(':memory:') as database:
        yield database


def scope(primary, placements=(), provider=None):
    return _job_log_placement_scope(FULL, primary, placements, 'EMS', provider)


def merge(conn, rows, placement_scope=None, **other):
    return projection.merge(conn, 'user:office', FULL, 'EMS', {
        'ok': True, 'canon_key': 'job', 'job_log': rows,
        'job_log_scope': placement_scope or {}, **other})


@pytest.mark.parametrize('reference', [SHORT, 'https://trello.com/c/' + SHORT + '/job',
                                      'https://trello.com/c/' + FULL])
def test_proven_provider_aliases_keep_primary_history(conn, reference):
    decision = scope({'card_id': reference}, provider={'id': FULL, 'shortLink': SHORT})
    assert decision['include_legacy'] is True
    rows = [{'entry_id': 'legacy'}, {'entry_id': 'owned', 'placement_card_id': reference}]
    filtered = _job_log_for_placement(rows, FULL, reference, include_legacy=True,
                                      card_aliases=decision['card_aliases'])
    assert merge(conn, filtered, decision)['job_log'] == rows


def test_url_syntax_needs_no_provider_mapping():
    decision = _job_log_placement_scope(SHORT, {'card_id': 'https://trello.com/c/' + SHORT}, [], 'EMS')
    assert decision['include_legacy'] is True
    assert _job_log_for_placement([{'entry_id': 'owned', 'placement_card_id':
        'https://trello.com/c/' + SHORT}], SHORT)


def test_unresolved_refresh_preserves_cached_rows_without_importing_legacy(conn):
    rows = [{'entry_id': 'already-scoped'}]
    merge(conn, rows, {'include_legacy': True})
    decision = scope({'card_id': SHORT})  # No proof that short ID is this full ID.
    assert 'include_legacy' not in decision
    newly_read = _job_log_for_placement([{'entry_id': 'unverified-shared'}], FULL,
        SHORT, include_legacy=decision.get('include_legacy', False))
    assert newly_read == []
    assert merge(conn, newly_read, decision)['job_log'] == rows


def test_verified_auxiliary_excludes_primary_legacy_and_wrong_division(conn):
    decision = scope({'card_id': 'b' * 24}, [{'card_id': FULL, 'division': 'EMS', 'primary': False}])
    assert decision['include_legacy'] is False
    merge(conn, [{'entry_id': 'legacy'}, {'entry_id': 'exact', 'placement_card_id': FULL}])
    assert [r['entry_id'] for r in merge(conn, [], decision)['job_log']] == ['exact']
    assert 'include_legacy' not in scope({'card_id': 'b' * 24},
        [{'card_id': FULL, 'division': 'CONTENTS', 'primary': False}])


def test_unknown_refresh_cannot_reopen_auxiliary_legacy(conn):
    merge(conn, [{'entry_id': 'legacy'}], {'include_legacy': False})
    assert merge(conn, [], scope({'card_id': ''}))['job_log'] == []


def test_provider_outage_retains_previously_proven_owned_alias(conn):
    row = {'entry_id': 'owned', 'placement_card_id': SHORT}
    merge(conn, [row], scope({'card_id': SHORT}, provider={'id': FULL, 'shortLink': SHORT}))
    assert merge(conn, [], scope({'card_id': SHORT}))['job_log'] == [row]


def test_proven_primary_repairs_prior_hidden_history_but_not_tombstones(conn):
    rows = [{'entry_id': 'legacy'}, {'entry_id': 'deleted'}]
    assert merge(conn, rows, {'include_legacy': False},
                 job_log_deleted_ids=['deleted'])['job_log'] == []
    unresolved = scope({'card_id': SHORT})
    assert merge(conn, [], unresolved)['job_log'] == []
    proven = scope({'card_id': SHORT}, provider={'id': FULL, 'shortLink': SHORT})
    assert merge(conn, rows, proven)['job_log'] == [{'entry_id': 'legacy'}]


def test_tombstone_and_account_card_division_boundaries(conn):
    rows = [{'entry_id': 'deleted'}, {'entry_id': 'foreign', 'placement_card_id': 'b' * 24}]
    merge(conn, rows, {'include_legacy': True}, job_log_deleted_ids=['deleted'])
    assert merge(conn, rows, scope({'card_id': SHORT}))['job_log'] == []
    assert projection._read(conn, 'other-user:office', FULL, 'EMS') is None
    assert projection._read(conn, 'user:other-office', FULL, 'EMS') is None
    assert projection._read(conn, 'user:office', 'b' * 24, 'EMS') is None
    assert projection._read(conn, 'user:office', FULL, 'CONTENTS') is None


def test_unrelated_provider_and_shortlink_case_do_not_prove_identity():
    assert 'include_legacy' not in scope({'card_id': SHORT}, provider={
        'id': 'b' * 24, 'shortLink': SHORT})
    decision = _job_log_placement_scope(SHORT.lower(), {'card_id': SHORT}, [], 'EMS')
    assert 'include_legacy' not in decision
