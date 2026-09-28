"""App-owned board placement lifecycle; Trello is an asynchronous adapter.

No job/file deletion, name matching, or provider fallback on save failure.
The durable desired-state row doubles as an idempotent sync outbox.
"""
from copy import deepcopy
import threading
import time
import uuid

import config
import pipeline_store
import supabase_client as sb

_worker_lock = threading.Lock()
_last_run = 0.0


def snapshot():
    workspace = str(config.load().get('trello_workspace_id') or '').strip()
    if not workspace:
        raise ValueError('Choose a workplace before managing cards')
    boards = sb.rest('GET', 'app_job_boards', params={
        'workspace': f'eq.{workspace}', 'select': '*', 'order': 'name.asc'})
    rows = sb.rest('GET', 'app_card_placements', params={
        'workspace': f'eq.{workspace}', 'select': '*', 'order': 'card_id.asc', 'limit': '1000'})
    # Never silently truncate a tombstone list: page until exhausted.
    all_rows = list(rows or [])
    offset = len(all_rows)
    while len(rows or []) == 1000:
        rows = sb.rest('GET', 'app_card_placements', params={
            'workspace': f'eq.{workspace}', 'select': '*', 'order': 'card_id.asc',
            'offset': str(offset), 'limit': '1000'})
        all_rows.extend(rows or [])
        offset += len(rows or [])
    return {'boards': boards or [], 'placements': all_rows}


def overlay(payload, saved):
    """Apply durable placement state without changing provider input objects."""
    result = deepcopy(payload)
    rows = {r['card_id']: r for r in saved.get('placements', [])}
    originals = {}
    destinations = {}
    for board in result.get('boards', []):
        for lane in board.get('lanes', []):
            destinations[(board.get('board_id'), lane.get('list_id'))] = lane
            keep = []
            for card in lane.get('cards', []):
                cid = card.get('card_id')
                if cid in rows:
                    originals[cid] = card
                else:
                    keep.append(card)
            lane['cards'] = keep
    for cid, row in rows.items():
        if row['state'] != 'active':
            continue
        lane = destinations.get((row['board_id'], row['list_id']))
        if lane is None:
            continue  # Another view owns this placement, not a lost card.
        raw = row.get('card_json') or {}
        card = originals.get(cid) or {'card_id': cid, 'name': row['title'],
            'client': row['title'], 'url': raw.get('url', ''), 'loss_types': [],
            'checklist': {}, 'stall': 'none', 'days_in_lane': 0}
        card.update(list_id=row['list_id'], lane=lane['name'], placement_version=row['version'],
                    sync_status='pending' if row['synced_version'] < row['version'] else 'synced')
        if row.get('position') is not None:
            card['pos'] = row['position']
        elif raw.get('pos') is not None and 'pos' not in card:
            card['pos'] = raw['pos']
        lane['cards'].append(card)
    for lane in destinations.values():
        lane['cards'].sort(key=lambda card: card.get('pos') or 0)
        lane['count'] = len(lane['cards'])
    result['placement_snapshot'] = saved
    return result


def merge_snapshots(incoming, saved):
    """Late reads cannot roll back an acknowledged placement mutation."""
    combined = {}
    for row in (saved or {}).get('placements', []) + (incoming or {}).get('placements', []):
        old = combined.get(row['card_id'])
        if old is None or (row['version'], row['synced_version']) >= (old['version'], old['synced_version']):
            combined[row['card_id']] = row
    return {'boards': (incoming or {}).get('boards') or (saved or {}).get('boards', []),
            'placements': list(combined.values())}


def decorate(payload):
    if not payload.get('ok'):
        return payload
    try:
        saved = snapshot()
    except Exception:
        saved = (payload.get('placement_snapshot') or
                 pipeline_store.load_board_cache().get('placement_snapshot'))
        if saved is None:
            # A successful provider read alone cannot prove a card is active.
            return {'ok': False, 'boards': [],
                    'error': 'Saved card locations are unavailable. Retry Jobs; no cards were changed.'}
        payload = {**payload, 'placement_warning': 'Showing saved card locations; shared refresh unavailable'}
    saved = merge_snapshots(saved, pipeline_store.load_board_cache().get('placement_snapshot'))
    return overlay(payload, saved)


def context(card_id=''):
    try:
        data = snapshot()
        row = next((r for r in data['placements'] if r['card_id'] == card_id), None)
        if card_id and row is None:
            originals = sb.rest('GET', 'hub_trello_mirror_cards', params={
                'card_id': f'eq.{card_id}', 'present': 'eq.true', 'select': 'board_id,payload', 'limit': '1'})
            if not originals:
                return {'ok': False, 'error': 'Card is not in accessible saved board data yet. Refresh Jobs and try again.'}
            original = originals[0]
            row = {'card_id': card_id, 'board_id': original['board_id'],
                   'list_id': original['payload'].get('idList'), 'title': original['payload'].get('name'),
                   'state': 'active', 'version': 0}
        access = sb.rpc('my_app_access') or {}
        return {'ok': True, **data, 'placement': row, 'can_delete': bool(access.get('is_admin'))}
    except Exception:
        return {'ok': False, 'error': 'Shared card storage could not load. Retry; nothing was changed.'}


def change(card_id, action, version, board_id=None, list_id=None, position=None):
    try:
        scope = pipeline_store._cache_scope()
        params = {'p_card': card_id, 'p_action': action,
            'p_version': int(version), 'p_board': board_id, 'p_list': list_id}
        if position is not None:
            import math
            if action != 'move' or not math.isfinite(float(position)) or float(position) <= 0:
                raise ValueError('Invalid card position')
            params.pop('p_action')
            params['p_position'] = float(position)
        row = sb.rpc('app_placement_drop' if position is not None else 'app_placement_change', params)
        if scope != pipeline_store._cache_scope():
            return {'ok': False, 'error': 'Account changed during save. Reopen Jobs to verify the result.'}
        cached = pipeline_store.load_board_cache()
        saved = cached.get('placement_snapshot') or {'boards': [], 'placements': []}
        saved['placements'] = [r for r in saved['placements'] if r['card_id'] != card_id] + [row]
        updated = overlay(cached, saved)
        pipeline_store.save_board_cache(updated)
        start_sync(force=True)
        return {'ok': True, 'placement': row, 'pending_sync': row['synced_version'] < row['version'],
                'board': updated}
    except Exception as ex:
        # Supabase errors are surfaced without falling through to Trello.
        return {'ok': False, 'error': str(ex)}


def sync_pending():
    import trello_client as tc
    scope = pipeline_store._cache_scope()
    data = snapshot()
    for candidate in data['placements']:
        if candidate['synced_version'] >= candidate['version']:
            continue
        if scope != pipeline_store._cache_scope():
            return
        token = str(uuid.uuid4())
        row = sb.rpc('app_placement_claim', {'p_card': candidate['card_id'],
                     'p_version': candidate['version'], 'p_token': token})
        if not row:
            continue
        if scope != pipeline_store._cache_scope():
            return  # Lease expires; never sync using a different account.
        error = None
        try:
            # Deleted app placements remain archived in Trello. No DELETE call.
            tc._call('/cards/' + row['card_id'], method='PUT', params={
                'idBoard': row['board_id'], 'idList': row['list_id'],
                'closed': 'false' if row['state'] == 'active' else 'true',
                **({'pos': row['position']} if row.get('position') is not None else {})})
        except Exception:
            error = 'Trello sync failed; saved in OneLoss. Retry from Archived cards or refresh Jobs.'
        if scope != pipeline_store._cache_scope():
            return
        sb.rpc('app_placement_ack', {'p_card': row['card_id'], 'p_version': row['version'],
                                   'p_token': token, 'p_error': error})


def start_sync(force=False):
    global _last_run
    if not force and time.monotonic() - _last_run < 30:
        return
    if not _worker_lock.acquire(blocking=False):
        return
    _last_run = time.monotonic()
    def run():
        try:
            sync_pending()
        except Exception:
            pass  # Durable pending rows remain visible and are retried later.
        finally:
            _worker_lock.release()
    threading.Thread(target=run, name='placement-sync', daemon=True).start()
