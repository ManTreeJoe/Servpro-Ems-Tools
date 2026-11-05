"""Offline replay of complete, ordered history for ONE (board_id, card_id).

Not a customer-facing API. Callers must supply the full stream, starting with a
snapshot. Observation times are not evidence of the actual time a card moved.
Format 1 rows are full snapshots; format 2 changes replace whole components.
Never prune a baseline or intervening delta without retaining a new checkpoint.
"""
from copy import deepcopy

COMPONENTS = frozenset(('card', 'details', 'comments', 'present'))


def apply_observation(state, row):
    """Return a new snapshot (or None for removal), rejecting incompatible data."""
    version = row.get('format_version', 1)
    kind = row.get('kind')
    before, after = row.get('before_data'), row.get('after_data')
    if version not in (1, 2):
        raise ValueError('Unsupported observation format')
    if kind not in ('baseline', 'changed', 'source_removed'):
        raise ValueError('Unsupported observation kind')
    if kind == 'source_removed':
        if not isinstance(before, dict) or set(before) != COMPONENTS or after is not None:
            raise ValueError('Invalid removal snapshot')
        if state is not None and state != before:
            raise ValueError('History does not match removal snapshot')
        return None
    if not isinstance(after, dict):
        raise ValueError('Missing observation payload')
    if kind == 'baseline' or version == 1:
        if set(after) != COMPONENTS:
            raise ValueError('Incomplete snapshot')
        if kind == 'changed' and state is not None and state != before:
            raise ValueError('History does not match previous snapshot')
        return deepcopy(after)
    if state is None or set(state) != COMPONENTS:
        raise ValueError('Delta requires a complete previous snapshot')
    if (not isinstance(before, dict) or not after or set(before) != set(after)
            or not set(after) <= COMPONENTS):
        raise ValueError('Invalid component delta')
    if any(state[key] != value for key, value in before.items()):
        raise ValueError('History does not match previous component')
    return deepcopy({**state, **after})
