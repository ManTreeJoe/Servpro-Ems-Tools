"""Read-only queue analytics. Never substitute last activity for lane entry."""
from datetime import datetime, timezone
import re

# Verified IE provider IDs, not guessed person-name matches. Shared lanes stay
# shared; these are assignment queues, not proof of individual labor hours.
IE_ESTIMATOR_LANES = {
    '5d8b9003b6ebf5687ffa3dd2', '5eb064e256106711859dece9',
    '6489dbcd50c6e8683f09aa84', '6aa86247c7aa36071338185e',
    '63c182785a9e3400bbc5f146', '63979bb8c64f9302ce1dd9a7',
    '623b55dbc474d601544b5e56', '667337f459cae6d401197afe',
    '6aa03820e55edb39a4b80c17', '5d8b8fff58781106242d842c',
}
IE_LOGS_BOARD = '67bcf63154947b17268a18bb'
IE_EST_BOARD = '5d8b8fec49d37b1456a3f63b'
IE_SNAPSHOT = '63a384193d3ec900984ab584'


def cycles(periods, current, now):
    results, start = [], None
    for p in periods:
        if p['board_id'] == IE_EST_BOARD and p['lane_id'] in IE_ESTIMATOR_LANES and start is None:
            start = p
        if p['board_id'] == IE_LOGS_BOARD and start:
            results.append(dict(started=start['entered'], ended=p['entered'],
                first_lane=start['lane'], seconds=(instant(p['entered'])-instant(start['entered'])).total_seconds()))
            start = None
    if start:
        # Outside estimating without a recorded Logs arrival is unresolved,
        # not a completed cycle or an indefinitely running estimator clock.
        running = current.get('idBoard') == IE_EST_BOARD and not current.get('closed')
        results.append(dict(started=start['entered'], ended=None, first_lane=start['lane'],
                            seconds=(now-instant(start['entered'])).total_seconds() if running else None))
    return results


def instant(value):
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result if result.tzinfo else None
    except (ValueError, TypeError):
        return None


def queues(payload):
    lanes = []
    for board in payload.get('boards', []):
        if board.get('key') == 'recon':
            continue  # Recon analytics remains deferred.
        for lane in board.get('lanes', []):
            lanes.append(dict(board_id=board['board_id'], board=board['name'],
                board_key=board['key'], id=lane['list_id'], name=lane['name'],
                cards=[dict(id=c['card_id'], name=c['name']) for c in lane.get('cards', [])]))
    return dict(ok=True, lanes=lanes, source=payload.get('source') or 'Saved Jobs data',
                saved_at=payload.get('saved_at') or '', stale=bool(payload.get('stale_cache')))


def timeline(actions, current, now=None):
    """Exact-card intervals from explicit placement events; earliest prior time unknown.

    Cross-board events lacking a destination list close the previous lane but
    leave the new lane unknown. They must never extend the old lane's clock.
    """
    now = now or datetime.now(timezone.utc)
    events, seen = [], set()
    for action in actions:
        identity = action.get('id')
        at = instant(action.get('date'))
        if not identity or identity in seen or not at or at > now:
            continue
        seen.add(identity)
        data = action.get('data') or {}
        kind = action.get('type')
        board = data.get('board') or {}
        lane = data.get('listAfter') or data.get('list') or {}
        if kind == 'updateCard' and not data.get('listAfter'):
            continue
        if kind == 'moveCardFromBoard':
            board = data.get('boardTarget') or {}
            lane = {}  # list, if present, describes the source on this event.
        elif kind not in ('updateCard', 'moveCardToBoard', 'createCard', 'copyCard'):
            continue
        if not board.get('id'):
            continue
        events.append(dict(id=identity, at=at, board_id=board['id'],
            board=board.get('name') or board['id'], lane_id=lane.get('id') or '',
            lane=lane.get('name') or 'Destination lane not recorded',
            actor=(action.get('memberCreator') or {}).get('fullName') or 'Not recorded'))
    events.sort(key=lambda e: (e['at'], bool(e['lane_id']), e['id']))
    compact = []
    for event in events:
        if compact and (event['board_id'], event['lane_id']) == (compact[-1]['board_id'], compact[-1]['lane_id']):
            continue
        if compact and event['at'] == compact[-1]['at'] and event['board_id'] == compact[-1]['board_id'] and not compact[-1]['lane_id']:
            compact[-1] = event
        else:
            compact.append(event)
    periods = []
    for i, event in enumerate(compact):
        end = compact[i+1]['at'] if i+1 < len(compact) else None
        matches = event['board_id'] == current.get('idBoard') and event['lane_id'] == current.get('idList') and not current.get('closed')
        # No precise endpoint if the final event disagrees with the live card.
        seconds = ((end or now) - event['at']).total_seconds() if end or matches else None
        periods.append({**{k:v for k,v in event.items() if k != 'at'},
            'entered':event['at'].isoformat(), 'exited':end.isoformat() if end else None,
            'seconds':seconds, 'current':bool(not end and matches)})
    totals = {}
    for period in periods:
        key = (period['board_id'], period['lane_id'])
        if period['lane_id'] and period['seconds'] is not None:
            item = totals.setdefault(key, dict(board=period['board'],lane=period['lane'],seconds=0,visits=0))
            item['seconds'] += period['seconds']
            item['visits'] += 1
    return dict(periods=periods, totals=list(totals.values()), estimator_cycles=cycles(periods,current,now),
                current_seconds=periods[-1]['seconds'] if periods and periods[-1]['current'] else None)


def read_history(card_id, allowed_ids):
    if card_id not in allowed_ids or not re.fullmatch(r'[a-f0-9]{24}', card_id):
        return {'ok':False, 'error':'Refresh the queues before inspecting this card.'}
    import trello_client as tc
    actions, before, complete = [], None, False
    for _ in range(10):
        params = {'filter':'updateCard:idList,moveCardToBoard,moveCardFromBoard,createCard,copyCard', 'limit':'1000'}
        if before:
            params['before'] = before
        page = tc._call(f'/cards/{card_id}/actions', params=params)
        if not isinstance(page, list):
            raise ValueError('Movement history unavailable')
        actions.extend(page)
        if len(page) < 1000:
            complete = True
            break
        cursor = page[-1].get('id')
        if not cursor or cursor == before:
            break
        before = cursor
    current = tc.get_card_lite(card_id, fields='name,idBoard,idList,closed')
    if not current:
        return {'ok':False, 'error':'Card is no longer available.'}
    return dict(ok=True, name=current.get('name') or '', complete=complete,
                **timeline(actions, current))
