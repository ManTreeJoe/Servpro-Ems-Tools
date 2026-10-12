"""Read exact-card Trello activity without changing cards or importing history."""
import re
import config
import supabase_client as sb
import trello_client as tc


def describe(action):
    kind, data = action.get('type', ''), action.get('data') or {}
    card, old = data.get('card') or {}, data.get('old') or {}
    if kind == 'commentCard': return 'Comment: ' + str(data.get('text') or '')
    if kind == 'updateCard':
        if 'listAfter' in data:
            return f"Moved from {(data.get('listBefore') or {}).get('name', 'another lane')} to {(data.get('listAfter') or {}).get('name', 'another lane')}"
        if 'closed' in old: return 'Archived this card' if card.get('closed') else 'Restored this card'
        return 'Updated card: ' + ', '.join(old.keys())
    if kind == 'updateCheckItemStateOnCard':
        item = data.get('checkItem') or {}
        return f"Checklist: {item.get('name', 'Item')} — {item.get('state', 'updated')}"
    labels = {'createCard':'Created this card', 'moveCardToBoard':'Moved this card to another board',
              'moveCardFromBoard':'Moved this card from another board',
              'addMemberToCard':'Assigned a member', 'removeMemberFromCard':'Removed a member',
              'addAttachmentToCard':'Added attachment', 'deleteAttachmentFromCard':'Removed attachment',
              'addChecklistToCard':'Added checklist', 'removeChecklistFromCard':'Removed checklist',
              'addLabelToCard':'Added label', 'removeLabelFromCard':'Removed label'}
    label = labels.get(kind, 'Trello activity: ' + kind)
    detail = next((data[k].get('name') or data[k].get('fullName') for k in
                   ('attachment', 'checklist', 'label', 'member') if isinstance(data.get(k), dict)), '')
    return label + (': ' + detail if detail else '')


def history(card_id):
    if not re.fullmatch(r'[0-9a-fA-F]{24}', str(card_id or '')):
        raise ValueError('An exact card is required.')
    workspace = str(config.load().get('trello_workspace_id') or '')
    department = config.active_department()
    user = (sb.current_user() or {}).get('id')
    if not user or not workspace: raise ValueError('Sign in first.')
    sources = sb.rest('GET', 'hub_trello_sync_sources', params={
        'select':'board_id', 'reader_department':'eq.'+department,
        'reader_workspace':'eq.'+workspace, 'enabled':'eq.true'}) or []
    allowed = {s['board_id'] for s in sources}
    def verify():
        card = tc._call('/cards/'+card_id, params={'fields':'id,idBoard,closed'}) or {}
        if card.get('id') != card_id or card.get('idBoard') not in allowed:
            raise ValueError('Card is not on an authorized board.')
        return card['idBoard']
    board = verify()
    rows, seen, before = [], set(), None
    for _ in range(10):
        params = {'filter':'all', 'limit':'100'}
        if before: params['before'] = before
        page = tc._call('/cards/'+card_id+'/actions', params=params) or []
        for action in page:
            identity = action.get('id')
            if not identity or identity in seen: continue
            seen.add(identity)
            member = action.get('memberCreator') or {}
            rows.append({'id':'trello:'+identity, 'at':action.get('date') or '',
                         'actor':member.get('fullName') or member.get('username') or 'Unknown user',
                         'actor_id':member.get('id') or '', 'source':'Trello', 'action':describe(action)})
        if len(page) < 100: break
        cursor = page[-1].get('id')
        if not cursor or cursor == before: break
        before = cursor
    if (verify() != board or config.active_department() != department
            or str(config.load().get('trello_workspace_id') or '') != workspace
            or (sb.current_user() or {}).get('id') != user):
        raise ValueError('Card or account changed. Reopen history.')
    return {'ok':True, 'rows':rows, 'note': 'Trello history limited to the latest 1,000 events.' if len(rows) >= 1000 else ''}
