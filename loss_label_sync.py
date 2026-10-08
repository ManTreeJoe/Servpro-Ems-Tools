"""Exact-card loss labels: bounded writes, durable intent, explicit retries.

Never replace a card's entire label list. Trello has no compare-and-set; check
before each individual mutation and verify afterwards. Pending snapshots include
the next possible result so a timeout after an accepted write is retryable.
"""
from copy import deepcopy
from threading import RLock
from uuid import uuid4

import job_settings as js
import trello_client as tc

_LOCK = RLock()
META_KEY = 'loss_label_sync'


class Conflict(ValueError):
    pass


def state(job, card_id):
    return deepcopy((js._meta_of(job).get(META_KEY) or {}).get(card_id) or {})


def snapshot(card):
    return {'card_id': card['id'], 'board_id': card['idBoard'],
            'labels': sorted([[label['id'], label.get('name') or '']
                              for label in card.get('labels') or []
                              if tc.card_loss_type({'labels': [label]})])}


def read_card(card_id):
    card = tc.get_card_lite(card_id, fields='id,idBoard,labels') or {}
    if card.get('id') != card_id or not card.get('idBoard') or 'labels' not in card:
        raise ValueError('Could not verify this exact Trello card and its labels.')
    return card


def projected(job, card):
    """Pending intent wins; enrolled, settled cards follow provider changes."""
    current = state(job, card.get('id', ''))
    if current.get('status') == 'pending':
        return current['desired']
    if current.get('status') in ('synced', 'conflict'):
        return tc.card_loss_type(card)
    settings = js._meta_of(job).get('settings') or {}
    return settings.get('loss_categories', tc.card_loss_type(card))


def context(job, card_id):
    card = read_card(card_id)
    saved = state(job, card_id)
    observed = snapshot(card)
    pending = saved.get('status') == 'pending'
    conflict = saved.get('status') == 'conflict' or (pending and observed not in saved.get('allowed', []))
    value = tc.card_loss_type(card) if conflict else projected(job, card)
    legacy = not saved and 'loss_categories' in (js._meta_of(job).get('settings') or {})
    return {'value': value, 'pending': (pending or legacy) and not conflict,
            'notice': ('Trello labels changed. Showing current Trello tags; review before saving. '
                       'Previous unsynced choice: ' + (saved.get('desired') or '(none)')) if conflict else
                      ('This saved loss-type choice has not been connected to Trello labels yet. Save to sync it.' if legacy else ''),
            'context': {'snapshot': observed, 'revision': saved.get('revision', ''),
                        'reviewed_conflict': conflict}}


def _persist(key, card_id, intent, *, expected_revision=None):
    # Re-read metadata to retain other field updates between provider calls.
    rec = js._record(key)
    if not rec:
        raise ValueError('Job no longer exists.')
    expected_revision = intent['revision'] if expected_revision is None else expected_revision
    if state(rec, card_id).get('revision', '') != expected_revision:
        raise Conflict('A newer OneLoss loss-type change exists. Reopen Job info to review it.')
    meta = js._meta_of(rec)
    meta.setdefault(META_KEY, {})[card_id] = deepcopy(intent)
    # Loss types are placement-scoped here, not copied into other divisions.
    js._persist(key, '', {}, meta)


def _plan(card, desired):
    requested = {v.strip() for v in desired.split(',') if v.strip()}
    supported = set(tc._LOSS_LABEL_NAMES.values())
    if requested - supported:
        raise ValueError('Unsupported loss types: ' + ', '.join(sorted(requested - supported)))
    board_labels = tc._call(f"/boards/{card['idBoard']}/labels", params={'limit': 1000}) or []
    available = {}
    for label in sorted(board_labels, key=lambda label: label['id']):
        category = tc.card_loss_type({'labels': [label]})
        if category:
            available.setdefault(category, label)
    attached = card.get('labels') or []
    existing = {tc.card_loss_type({'labels': [label]}) for label in attached}
    missing = requested - existing - available.keys()
    if missing:
        raise ValueError('This Trello board has no matching label for: ' + ', '.join(sorted(missing)))
    operations = [('POST', available[c]) for c in sorted(requested - existing)]
    operations += [('DELETE', label) for label in attached
                   if tc.card_loss_type({'labels': [label]})
                   and tc.card_loss_type({'labels': [label]}) not in requested]
    canonical = ', '.join(v for v in tc._LOSS_LABEL_NAMES.values() if v in requested)
    return canonical, operations


def save(key, card_id, desired, expected):
    with _LOCK:
        return _save(key, card_id, desired, expected)


def _save(key, card_id, desired, expected):
    intent = None
    persisted = False
    try:
        if not card_id or not isinstance(expected, dict) or not expected.get('snapshot'):
            raise Conflict('Reload Job info before changing loss types.')
        rec = js._record(key)
        old = state(rec, card_id)
        if old.get('revision', '') != expected.get('revision', ''):
            raise Conflict('Loss types changed in OneLoss. Reopen Job info to review them.')
        card = read_card(card_id)
        observed = snapshot(card)
        retry = old.get('status') == 'pending' and desired == old.get('desired') and not expected.get('reviewed_conflict')
        if (retry and observed not in old.get('allowed', [])) or (not retry and observed != expected['snapshot']):
            raise Conflict('Trello labels changed. Reopen Job info to review the current tags; no labels were overwritten.')
        desired, operations = _plan(card, desired)
        intent = {'desired': desired, 'status': 'pending', 'revision': str(uuid4()),
                  'allowed': [observed]}
        _persist(key, card_id, intent, expected_revision=old.get('revision', ''))
        persisted = True
        for method, label in operations:
            live = snapshot(read_card(card_id))
            if live != observed:
                raise Conflict('Trello labels changed during saving. Reopen Job info to review them.')
            next_snapshot = deepcopy(observed)
            pair = [label['id'], label.get('name') or '']
            if method == 'POST':
                next_snapshot['labels'].append(pair)
            else:
                next_snapshot['labels'].remove(pair)
            next_snapshot['labels'].sort()
            intent['allowed'] = [observed, next_snapshot]
            _persist(key, card_id, intent)
            if method == 'POST':
                tc._call(f'/cards/{card_id}/idLabels', method='POST', data={'value': label['id']}, _max_retries=0)
            else:
                tc._call(f"/cards/{card_id}/idLabels/{label['id']}", method='DELETE', _max_retries=0)
            observed = next_snapshot
        if snapshot(read_card(card_id)) != observed:
            raise Conflict('Trello labels changed during saving. Reopen Job info to review them.')
        intent.update(status='synced', allowed=[observed])
        _persist(key, card_id, intent)
        return {'ok': True, 'pending_push': False, 'loss_labels_pending': False,
                'loss_label_context': {'snapshot': observed, 'revision': intent['revision']}}
    except Conflict as ex:
        if persisted:
            intent['status'] = 'conflict'
            try:
                _persist(key, card_id, intent)
            except Conflict:
                pass  # A newer writer owns the intent; never overwrite it.
        return {'ok': False, 'error': str(ex), 'loss_label_conflict': True}
    except Exception as ex:
        if not persisted:
            return {'ok': False, 'error': str(ex)}
        return {'ok': True, 'pending_push': True, 'loss_labels_pending': True,
                'loss_label_context': {'snapshot': intent['allowed'][0], 'revision': intent['revision']},
                'error': 'Loss types saved; Trello sync pending. Retry from Job info.'}
