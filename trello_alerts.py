"""Bounded connected-account feed for alerts; never turn failures into empty feeds."""
import hashlib


def account_key():
    import trello_client as tc
    key, token = tc._creds()
    return hashlib.sha256((key + ':' + token).encode()).hexdigest()


def fetch():
    import trello_client as tc
    from notifications_web import _shape
    raw = tc._call('/members/me/notifications', params={
        'limit': '80', 'filter': 'commentCard,mentionedOnCard',
        'memberCreator': 'true', 'memberCreator_fields': 'fullName,username',
    }, _timeout=8, _max_retries=0)
    if not isinstance(raw, list):
        raise ValueError('Trello feed unavailable')
    unique = {}
    for row in raw:
        value = _shape(row)
        if not value['id'] or value['type'] not in ('commentCard', 'mentionedOnCard'):
            continue
        event = value['comment_id'] or value['id']
        item = dict(id=event, notification_id=value['id'], source='trello',
                    card_id=value['card_id'], comment_id=value['comment_id'],
                    kind='mention' if value['type']=='mentionedOnCard' else 'comment',
                    client=value['card_name'], actor=value['by'], body=value['snippet'],
                    created_at=value['date'], read_at=None if value['unread'] else 'read')
        if event not in unique or item['kind']=='mention':
            unique[event] = item
    return list(unique.values())
