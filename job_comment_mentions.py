"""Read-only Trello mention candidates for an exact posting card."""
import re


def members(card_id):
    card_id = str(card_id or '').strip()
    if not re.fullmatch(r'(?:[0-9a-fA-F]{24}|[A-Za-z0-9]{8})', card_id):
        return {'ok': False, 'members': [], 'error': 'Choose a verified Trello destination first.'}
    try:
        import trello_client as tc
        options = {'_max_retries': 0, '_timeout': 5}
        card = tc._call(f'/cards/{card_id}', params={'fields': 'idBoard'}, **options) or {}
        board_id = card.get('idBoard') or ''
        if not re.fullmatch(r'[0-9a-fA-F]{24}', board_id):
            return {'ok': False, 'members': [], 'error': 'The destination board could not be verified.'}
        rows = tc._call(f'/boards/{board_id}/members',
                        params={'fields': 'fullName,username'}, **options) or []
        candidates = {}
        for row in rows:
            username = str(row.get('username') or '')
            if re.fullmatch(r'[A-Za-z0-9_.-]+', username):
                candidates[username.casefold()] = {
                    'id': str(row.get('id') or ''), 'username': username,
                    'name': str(row.get('fullName') or username)}
        return {'ok': True, 'members': sorted(candidates.values(), key=lambda row: row['name'].casefold())}
    except Exception:
        # Provider exceptions can contain credential-bearing URLs.
        return {'ok': False, 'members': [], 'error': 'Trello people could not be loaded. Retry when connected.'}
