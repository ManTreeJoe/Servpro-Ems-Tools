"""Read-only, exact-column review population. Never matches customer names."""
from datetime import datetime, timezone

BOARD = 'THE LOGS - EMS'
LISTS = {'EMS': 'TO BE PRESERVED', 'CONTENTS': 'CONTENTS CARDS'}

def _one(rows, name):
    matches = [r for r in rows if not r.get('closed') and str(r.get('name', '')).strip().casefold() == name.casefold()]
    if len(matches) != 1:
        raise ValueError(f'Expected one {name} source; found {len(matches)}. Check the connected Trello workspace.')
    return matches[0]

def load_graph(location, client=None):
    if client is None:
        import trello_client as client
    board = _one(client.list_boards(), BOARD)
    lists = client._call(f"/boards/{board['id']}/lists", params={'fields':'id,name,closed','filter':'open'})
    if not isinstance(lists, list):
        raise ValueError('Review columns could not be read.')
    observed = datetime.now(timezone.utc).isoformat(timespec='seconds')
    jobs, membership = {}, {}
    for division, name in LISTS.items():
        lane = _one(lists, name)
        # Do not use cards_in_list: its error fallback is indistinguishable from empty.
        cards = client._call(f"/lists/{lane['id']}/cards", params={'fields':'id,name,idBoard,idList,closed,shortUrl','filter':'open'})
        if not isinstance(cards, list):
            raise ValueError('Review cards could not be read.')
        for card in cards:
            if card.get('closed'):
                continue
            if not card.get('id') or card.get('idBoard') != board['id'] or card.get('idList') != lane['id']:
                raise ValueError('A review card changed columns while loading. Refresh and try again.')
            key = 'trello:' + card['id']
            if key in jobs:
                raise ValueError('A review card appeared twice. Refresh and try again.')
            jobs[key] = {'job_id':key,'canon_key':key,'display_name':card.get('name') or 'Untitled card',
                'department':location,'lifecycle_stage':'legacy_unclassified',
                '_division_states':[{'division':division,'stage':'unknown'}]}
            membership[key] = {'card_id':card['id'],'board_id':board['id'],'board_name':board['name'],
                'list_id':lane['id'],'list_name':lane['name'],'observed_at':observed,'division':division}
    return {'ok':True,'_jobs_by_key':jobs,'review_membership':membership,
        'state':{'source':'Trello Logs columns — current membership'},
        'warnings':['This queue counts Trello cards, not unique Losses. Column membership is observed now, not reconstructed for the selected dates. Save a review snapshot to preserve this population.']}
