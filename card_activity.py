"""Read existing OneLoss placement audit events; never infer provider activity."""
import re

import config
import supabase_client as sb


def shape(events, boards, user):
    catalog = {b['board_id']: b for b in boards}

    def location(board_id, list_id):
        board = catalog.get(board_id, {})
        lane = next((r.get('name') for r in board.get('lists', []) if r.get('id') == list_id), None)
        return ' / '.join([board.get('name') or 'Unavailable board', lane or 'Unavailable lane'])

    rows = []
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            continue
        actor_id = str(event.get('actor') or '')
        actor = (user.get('display_name') or user.get('email') or 'You') if actor_id and actor_id == user.get('id') else (
            'User ' + actor_id[:8] if actor_id else 'Unknown user')
        state, previous = event.get('state'), event.get('from_state')
        if state == 'archived' and previous != state:
            action = 'Archived this card'
        elif state == 'deleted' and previous != state:
            action = 'Retired this card'
        elif state == 'active' and previous == 'archived':
            action = 'Restored this card to ' + location(event.get('board'), event.get('list'))
        elif 'from_board' in event:
            action = 'Moved from ' + location(event.get('from_board'), event.get('from_list')) + ' to ' + location(event.get('board'), event.get('list'))
        elif 'position' in event:
            action = 'Changed this card’s order in its lane'
        else:
            action = 'Updated this card'
        rows.append({'id': str(index), 'at': event.get('at') or '', 'actor': actor,
                     'actor_id': actor_id, 'action': action, 'source': 'OneLoss'})
    return sorted(rows, key=lambda r: (r['at'], int(r['id'])), reverse=True)


def history(card_id):
    if not re.fullmatch(r'[0-9a-fA-F]{24}', str(card_id or '')):
        raise ValueError('Open a linked card to view its saved activity.')
    workspace = str(config.load().get('trello_workspace_id') or '').strip()
    user = sb.current_user() or {}
    if not workspace or not user.get('id'):
        raise ValueError('Sign in and select a workspace first.')
    with sb.interactive_requests(seconds=12):
        placements = sb.rest('GET', 'app_card_placements', params={
            'card_id': 'eq.' + card_id, 'workspace': 'eq.' + workspace,
            'select': 'card_id,events', 'limit': '1'}) or []
        boards = sb.rest('GET', 'app_job_boards', params={
            'workspace': 'eq.' + workspace, 'select': 'board_id,name,lists'}) or []
    if workspace != str(config.load().get('trello_workspace_id') or '').strip() or user.get('id') != (sb.current_user() or {}).get('id'):
        raise ValueError('Account or workspace changed. Reopen the card.')
    return {'ok': True, 'rows': shape(placements[0].get('events') or [], boards, user) if placements else [],
            'note': 'Saved OneLoss movement history for this card. Checklist and field-edit history are not included yet.'}
