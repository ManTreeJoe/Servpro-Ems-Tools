"""Comment delivery outcomes and best-effort notifications, independent of UI."""


def notify(card_id, comment_id, text):
    """Notifications must never turn a confirmed post into a failed post."""
    try:
        from personal_notifications import enqueue
        return enqueue(card_id, comment_id, text) or ''
    except Exception:
        return 'Comment saved, but notifications could not be confirmed. Do not repost.'


def send_many(card_ids, text, send):
    targets = list(dict.fromkeys(str(value or '').strip() for value in (card_ids or []) if str(value or '').strip()))
    if not targets or len(targets) > 8:
        return {'ok': False, 'error': 'Choose between one and eight linked cards.'}
    results = []
    for card in targets:
        try:
            result = send(card, text)
        except Exception:
            # A transport failure does not establish whether a write landed.
            result = {'ok': False, 'delivery': 'unconfirmed',
                      'error': 'Delivery could not be confirmed. Check the card before retrying.'}
        results.append({**result, 'card_id': card})
    failed = [row for row in results if not row.get('ok')]
    return {'ok': not failed, 'partial': bool(failed) and len(failed) < len(results),
            'results': results, 'posted': len(results) - len(failed), 'failed': failed,
            'unconfirmed': [row['card_id'] for row in failed if row.get('delivery') == 'unconfirmed'],
            'pending_sync': any(row.get('pending_sync') for row in results if row.get('ok')),
            'error': 'Some destinations were not confirmed. Your draft is kept.' if failed else ''}
