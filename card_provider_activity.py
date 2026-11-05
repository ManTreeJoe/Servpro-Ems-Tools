"""Read exact-card Trello activity without changing cards or importing history."""
import re
import config
import supabase_client as sb
import trello_client as tc


def describe(action, label_names=None):
    kind, data = action.get('type', ''), action.get('data') or {}
    card, old = data.get('card') or {}, data.get('old') or {}
    if kind == 'updateCard':
        if 'listAfter' in data:
            return f"Moved from {(data.get('listBefore') or {}).get('name', 'another lane')} to {(data.get('listAfter') or {}).get('name', 'another lane')}"
        if 'closed' in old: return 'Archived this card' if card.get('closed') else 'Restored this card'
        changes = []
        for key, before in old.items():
            if key == 'pos':
                changes.append('Changed card order')
            elif key == 'idLabels':
                if not isinstance(before, list) or not isinstance(card.get(key), list):
                    changes.append('Updated labels')
                    continue
                after = card[key]
                names = label_names or {}
                for label_id in after:
                    if label_id not in before:
                        changes.append('Added label: ' + names.get(label_id, 'name unavailable'))
                for label_id in before:
                    if label_id not in after:
                        changes.append('Removed label: ' + names.get(label_id, 'name unavailable'))
                if before == after:
                    changes.append('Updated labels')
            elif key == 'desc':
                changes.append('Edited card description')
            elif key == 'dueComplete':
                changes.append('Marked due date complete' if card.get(key) else 'Marked due date incomplete')
            elif key in ('name', 'due', 'start') and key in card:
                after = card[key]
                field = {'name':'Title', 'due':'Due date', 'start':'Start date'}[key]
                changes.append(f"{field}: {before if before is not None else '(empty)'} → {after if after is not None else '(empty)'}")
            else:
                changes.append({'idMembers':'Updated assigned members', 'idList':'Changed lane',
                                'idBoard':'Changed board', 'cover':'Updated card cover'}.get(key, 'Updated card details'))
        return '; '.join(dict.fromkeys(changes)) or 'Updated card details'
    if kind == 'updateCheckItemStateOnCard':
        item = data.get('checkItem') or {}
        return f"Checklist: {item.get('name', 'Item')} — {item.get('state', 'updated')}"
    labels = {'createCard':'Created this card', 'moveCardToBoard':'Moved this card to another board',
              'moveCardFromBoard':'Moved this card from another board',
              'addMemberToCard':'Assigned a member', 'removeMemberFromCard':'Removed a member',
              'addAttachmentToCard':'Added attachment', 'deleteAttachmentFromCard':'Removed attachment',
              'addChecklistToCard':'Added checklist', 'removeChecklistFromCard':'Removed checklist',
              'addLabelToCard':'Added label', 'removeLabelFromCard':'Removed label'}
    label = labels.get(kind, 'Updated card details')
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
    label_names = None
    rows, seen, before = [], set(), None
    for _ in range(10):
        params = {'filter':'all', 'limit':'100'}
        if before: params['before'] = before
        page = tc._call('/cards/'+card_id+'/actions', params=params) or []
        for action in page:
            identity = action.get('id')
            if not identity or identity in seen: continue
            seen.add(identity)
            # Discussion belongs in the comments panel, not the card-change audit.
            # Still count it and advance the raw-page cursor so older changes load.
            if 'comment' in str(action.get('type') or '').lower(): continue
            if label_names is None and 'idLabels' in ((action.get('data') or {}).get('old') or {}):
                # Names are best-effort: deleted labels must never surface as raw IDs.
                label_names = {}
                try:
                    catalog = tc._call('/boards/'+board+'/labels', params={'fields':'name,color', 'limit':'1000'}) or []
                    label_names = {label['id']: label.get('name') or (label.get('color') or 'Unnamed') + ' label'
                                   for label in catalog if isinstance(label, dict) and label.get('id')}
                except Exception:
                    pass
            member = action.get('memberCreator') or {}
            rows.append({'id':'trello:'+identity, 'at':action.get('date') or '',
                         'actor':member.get('fullName') or member.get('username') or 'Unknown user',
                         'actor_id':member.get('id') or '', 'source':'Trello', 'action':describe(action, label_names)})
        if len(page) < 100: break
        cursor = page[-1].get('id')
        if not cursor or cursor == before: break
        before = cursor
    if (verify() != board or config.active_department() != department
            or str(config.load().get('trello_workspace_id') or '') != workspace
            or (sb.current_user() or {}).get('id') != user):
        raise ValueError('Card or account changed. Reopen history.')
    return {'ok':True, 'rows':rows, 'note': 'Trello history limited to the latest 1,000 events.' if len(seen) >= 1000 else ''}
