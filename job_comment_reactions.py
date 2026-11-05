"""Explicit, online Trello reactions. No comment import or background polling."""
import re
import threading
from comment_emoji import CHOICES, CODES

_WRITE_LOCK = threading.Lock()
_OPTIONS = {'_max_retries': 0, '_timeout': 5}
PIN_CODE = '1F4CC'


def pin_state(card_id):
    """Read provider pins in pages; never interpret a partial/failed read as unpinned."""
    try:
        import trello_client as tc
        if not re.fullmatch(r'(?:[0-9a-fA-F]{24}|[A-Za-z0-9]{8})', str(card_id)):
            raise ValueError('Invalid card')
        me = tc._call('/members/me', params={'fields': 'id'}, **_OPTIONS)
        if not me.get('id'):
            raise ValueError('Unknown account')
        states, before = {}, None
        for _ in range(20):
            params = {'filter': 'commentCard', 'limit': 200, 'reactions': 'true', 'reactions_emoji': 'true'}
            if before:
                params['before'] = before
            rows = tc._call(f'/cards/{card_id}/actions', params=params, **_OPTIONS)
            if not isinstance(rows, list):
                raise ValueError('Invalid response')
            for row in rows:
                if not isinstance(row.get('reactions'), list):
                    raise ValueError('Missing reaction state')
                pins = [r for r in row['reactions'] if _code(r) == PIN_CODE]
                states[row['id']] = {'pinned': bool(pins), 'mine': any(r.get('idMember') == me['id'] for r in pins)}
            if len(rows) < 200:
                return {'ok': True, 'pins': states}
            cursor = rows[-1].get('id')
            if not cursor or cursor == before:
                break
            before = cursor
        raise ValueError('Incomplete history')
    except Exception:
        return {'ok': False, 'error': 'Trello pins could not refresh. Previous pin markers are kept.'}


def _snapshot(tc, card_id, action_id):
    if not re.fullmatch(r'(?:[0-9a-fA-F]{24}|[A-Za-z0-9]{8})', str(card_id)) or not re.fullmatch(r'[0-9a-fA-F]{24}', str(action_id)):
        raise ValueError('A verified Trello comment is required.')
    action = tc._call(f'/actions/{action_id}', params={
        'reactions': 'true', 'reactions_member': 'true', 'reactions_emoji': 'true'}, **_OPTIONS)
    card = (action.get('data') or {}).get('card') or {}
    if action.get('type') != 'commentCard' or card_id not in (card.get('id'), card.get('shortLink')):
        raise ValueError('This comment does not belong to this card.')
    me = tc._call('/members/me', params={'fields': 'id,fullName,username'}, **_OPTIONS)
    if not me.get('id') or not isinstance(action.get('reactions'), list):
        raise ValueError('Trello reaction details could not be verified.')
    return action['reactions'], me


def _code(row):
    return str((row.get('emoji') or {}).get('unified') or row.get('idEmoji') or '').upper()


def _result(rows, me):
    groups = {}
    for row in rows:
        code = _code(row)
        emoji = row.get('emoji') or {}
        group = groups.setdefault(code, {'code': code, 'emoji': emoji.get('native') or '',
                                        'count': 0, 'mine': False, 'people': []})
        group['count'] += 1
        group['mine'] |= row.get('idMember') == me['id']
        member = row.get('member') or {}
        group['people'].append(member.get('fullName') or member.get('username') or 'Trello member')
    return {'ok': True, 'reactions': list(groups.values()), 'choices': CHOICES,
            'account': me.get('fullName') or me.get('username') or 'Connected Trello account'}


def reactions(card_id, action_id, code=None, active=None):
    """Desired-state write; fresh ownership check before every mutation."""
    writing = code is not None
    if writing and (not isinstance(active, bool) or not re.fullmatch(r'[0-9A-F]{4,6}(?:-[0-9A-F]{4,6}){0,9}', str(code))):
        return {'ok': False, 'error': 'Choose a supported reaction.'}
    if writing and not _WRITE_LOCK.acquire(blocking=False):
        return {'ok': False, 'error': 'Another reaction is saving. Wait, then refresh reactions.'}
    try:
        import trello_client as tc
        rows, me = _snapshot(tc, card_id, action_id)
        if writing:
            owned = [row for row in rows if row.get('idMember') == me['id'] and _code(row) == code]
            if active and not owned:
                if code not in CODES and not any(_code(row) == code for row in rows):
                    return {'ok': False, 'error': 'Choose a supported reaction.'}
                tc._call(f'/actions/{action_id}/reactions', method='POST', json_data={'unified': code}, **_OPTIONS)
            elif not active:
                for row in owned:
                    reaction_id = str(row.get('id') or '')
                    if not re.fullmatch(r'[0-9a-fA-F]{24}', reaction_id):
                        raise ValueError('Invalid reaction identity')
                    tc._call(f'/actions/{action_id}/reactions/{reaction_id}', method='DELETE', **_OPTIONS)
            # Only show confirmed provider state, including after uncertain previous writes.
            rows = tc._call(f'/actions/{action_id}/reactions', params={'member': 'true', 'emoji': 'true'}, **_OPTIONS)
            if not isinstance(rows, list):
                raise ValueError('Invalid reaction response')
        return _result(rows, me)
    except Exception:
        # Provider exceptions may include credentials. Never expose raw errors.
        return {'ok': False, 'error': ('Trello could not confirm the reaction. Refresh reactions before trying again.'
                                    if writing else 'Reactions could not be loaded from Trello. Try again.')}
    finally:
        if writing:
            _WRITE_LOCK.release()
