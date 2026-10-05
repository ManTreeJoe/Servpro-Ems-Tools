"""Read-only day review; mutations belong to the atomic confirmation RPC."""
import re

import schedule_records


def active_lanes(board):
    return [lane for lane in board.get('lists', [])
            if not lane.get('closed') and not re.search('recon', lane.get('name', ''), re.I)]


def suggestion(visit, card):
    """Conservative hints, never authority. User sees/corrects every destination."""
    current = card['list_id']
    if card['board_name'].strip().upper() != 'WORK IN PROGRESS':
        return current
    labels = {a['label'].strip().lower() for a in visit['activities']}
    if visit['group'] == 'Monitor':
        target = 'MONITOR'
    elif labels == {'initial inspection'}:
        target = 'INITIAL INSPECTIONS/RE-INSPECTIONS'
    elif 'monitor' in labels:
        return current  # A side Monitor must never itself change placement.
    else:
        target = 'WORK IN PROGRESS'
    matches = [x['id'] for x in card['lanes'] if x['name'].strip().upper() == target]
    return matches[0] if len(matches) == 1 else current


def _cards(store, ids, table, select):
    result = {}
    for start in range(0, len(ids), 50):
        rows = store.request(table, params={'card_id': 'in.(' + ','.join(ids[start:start+50]) + ')',
                                           'select': select})
        result.update({r['card_id']: r for r in rows})
    return result


def preview(store, day):
    day = schedule_records.day(day)
    visits = [row for row in store.load() if row['queue'] == 'scheduled' and row['date'] == day]
    if len(visits) > 500:
        raise ValueError('This day has more than 500 visits; confirmation is unavailable.')
    boards = {b['board_id']: b for b in store.request('app_job_boards', params={
        'department': 'eq.' + store.department, 'enabled': 'eq.true',
        'select': 'board_id,name,lists,workspace'})}
    ids = sorted({cid for v in visits for cid in v.get('trello_cards', [])
                  if re.fullmatch('[a-fA-F0-9]{24}', cid)})
    placements = _cards(store, ids, 'app_card_placements', 'card_id,board_id,list_id,state,version,title')
    mirrors = _cards(store, [cid for cid in ids if cid not in placements],
                     'hub_trello_mirror_cards', 'card_id,board_id,payload,present')
    entries = []
    for v in visits:
        candidates = []
        for cid in sorted(set(v.get('trello_cards', []))):
            p = placements.get(cid)
            if p is None:
                m = mirrors.get(cid, {})
                payload = m.get('payload') or {}
                if not m.get('present') or payload.get('closed'):
                    continue
                p = dict(card_id=cid, board_id=m['board_id'], list_id=payload.get('idList'),
                         version=0, title=payload.get('name'), state='active')
            b = boards.get(p['board_id'])
            if p['state'] != 'active' or not b or b['name'].strip().upper() not in ('WORK IN PROGRESS', 'CONTENTS'):
                continue
            lanes = active_lanes(b)
            lane = next((x for x in lanes if x['id'] == p['list_id']), None)
            if lane is None:
                continue
            card = {**p, 'board_name': b['name'], 'lane_name': lane['name'],
                    'lanes': [{'id': x['id'], 'name': x['name']} for x in lanes]}
            card['suggested_list'] = suggestion(v, card)
            candidates.append(card)
        entries.append({'id': v['id'], 'revision': v['revision'], 'title': v['title'],
                        'group': v['group'], 'activities': v['activities'], 'cards': candidates,
                        'confirmed': v.get('confirmed', False),
                        'note': ('Link this entry to a job to enable board moves.' if not v['job_id'] else
                                 'No eligible linked WIP/Contents card. Placement will stay unchanged.' if not candidates else
                                 'Choose the card to move; no card is selected automatically.' if len(candidates) > 1 else '')})
    return {'date': day, 'department': store.department, 'entries': entries}


def confirm(store, command):
    if not isinstance(command, dict) or command.get('department') != store.department:
        raise ValueError('Office changed. Reopen Schedule.')
    schedule_records.day(command.get('date'))
    schedule_records.identifier(command.get('operation_id'))
    return store.request('rpc/confirm_schedule_day', body={'p_command': command})
