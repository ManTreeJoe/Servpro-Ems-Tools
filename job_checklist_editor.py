"""Explicit Trello checklist edits, verified against the selected card."""
import re


def edit(card_id, operation, name, checklist_id='', item_id=''):
    import trello_client as tc
    if not re.fullmatch(r'(?:[a-fA-F0-9]{24}|[A-Za-z0-9]{8})', str(card_id)):
        return {'ok': False, 'error': 'Open a linked Trello card first.'}
    name = str(name or '').strip()
    if operation in ('mark_na', 'restore_applicable'):
        name = re.sub(r'^\[N/A\]\s*', '', name, flags=re.I).strip()
        if operation == 'mark_na' and name:
            name = '[N/A] ' + name
    if operation not in ('create', 'add', 'rename', 'rename_item', 'mark_na', 'restore_applicable') or not name or len(name) > 500:
        return {'ok': False, 'error': 'Enter a name between 1 and 500 characters.'}
    options = {'_max_retries': 0, '_timeout': 15}
    wrote = False
    try:
        lists = tc._call(f'/cards/{card_id}/checklists', **options)
        group = next((cl for cl in lists if cl.get('id') == checklist_id), None)
        if operation != 'create' and group is None:
            return {'ok': False, 'error': 'This checklist is no longer on the selected card. Refresh it.'}
        if operation in ('rename_item', 'mark_na', 'restore_applicable') and not any(i.get('id') == item_id for i in group.get('checkItems', [])):
            return {'ok': False, 'error': 'This item is no longer in the selected checklist. Refresh it.'}
        if operation == 'create':
            created = tc._call(f'/cards/{card_id}/checklists', method='POST', data={'name': name, 'pos': 'bottom'}, **options)
            checklist_id = (created or {}).get('id', '')
        elif operation == 'add':
            tc._call(f'/checklists/{checklist_id}/checkItems', method='POST', data={'name': name, 'pos': 'bottom'}, **options)
        elif operation == 'rename':
            tc._call(f'/checklists/{checklist_id}', method='PUT', data={'name': name}, **options)
        else:
            payload = {'name': name}
            if operation in ('mark_na', 'restore_applicable'):
                payload['state'] = 'complete' if operation == 'mark_na' else 'incomplete'
            tc._call(f'/cards/{card_id}/checkItem/{item_id}', method='PUT', data=payload, **options)
        wrote = True
        lists = tc._call(f'/cards/{card_id}/checklists', **options)
        return {'ok': True, 'checklist_id': checklist_id, 'checklists': [
            {'id': cl['id'], 'name': cl.get('name', ''), 'items': [
                {'id': i['id'], 'name': i.get('name', ''), 'complete': i.get('state') == 'complete'}
                for i in sorted(cl.get('checkItems', []), key=lambda i: i.get('pos', 0))]}
            for cl in sorted(lists, key=lambda cl: cl.get('pos', 0))]}
    except Exception:
        return {'ok': False, 'uncertain': True, 'error':
                'Saved to Trello, but the updated list could not load. Reopen the card before retrying.' if wrote else
                'Trello could not confirm the change. Reopen the card to check before retrying.'}
