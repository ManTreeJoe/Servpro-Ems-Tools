"""Small conditional transfers; cached cards require fresh server confirmation.

No TTL-only authorization, disk persistence, or fallback to cached results on
failure. Versions cover content, not polling timestamps. Existing write/freshness
barriers remain the responsibility of trello_mirror_reader.
"""
from collections import OrderedDict
from copy import deepcopy
from threading import RLock

import supabase_client as sb

_lock = RLock()
_snapshots = OrderedDict()


def clear():
    with _lock:
        _snapshots.clear()


def read(scope, department, workspace, board_ids):
    ids = tuple(sorted(set(board_ids)))
    key = (scope, department, workspace, ids)
    # Serialize confirmation + replacement so concurrent responses cannot
    # overwrite a newer cache generation. No cache survives process restart.
    with _lock:
        previous = _snapshots.get(key, {})
        result = sb.rpc('hub_trello_boards', {
            'p_department': department, 'p_workspace': workspace,
            'p_board_ids': list(ids),
            'p_versions': {bid: row['version'] for bid, row in previous.items()},
        })
        if not isinstance(result, dict) or not isinstance(result.get('boards'), list):
            raise ValueError('Invalid board confirmation')
        fresh = {}
        result = deepcopy(result)
        for row in result['boards']:
            bid = row.get('board', {}).get('id')
            if bid not in ids or bid in fresh or not row.get('version'):
                raise ValueError('Unexpected board confirmation')
            if row.get('unchanged') is True:
                old = previous.get(bid)
                if not old or old['version'] != row['version']:
                    raise ValueError('No matching confirmed board')
                row['cards'] = deepcopy(old['cards'])
            if not isinstance(row.get('cards'), list):
                raise ValueError('Missing board cards')
            fresh[bid] = {'version': row['version'], 'cards': deepcopy(row['cards'])}
        # Missing/revoked boards are intentionally dropped, never reinserted.
        _snapshots[key] = fresh
        _snapshots.move_to_end(key)
        while len(_snapshots) > 8:
            _snapshots.popitem(last=False)
        return result
