"""Shared comment annotations and durable replies. Never fall back to an unlinked post."""
import supabase_client as sb


def call(action, card_id, data=None):
    try:
        with sb.interactive_requests(seconds=12):
            return sb.rpc('job_comment_threads', {'p_action': action,
                          'p_card': card_id, 'p_data': data or {}})
    except Exception as error:
        message = str(error)
        if 'Comment is not in the shared snapshot yet' in message:
            return {'ok': False, 'error': 'This comment has not reached the shared snapshot yet. Give it a moment, then retry.'}
        if 'Card access required' in message:
            return {'ok': False, 'error': 'This card is not available to your signed-in OneLoss account.'}
        if 'Pin changed' in message:
            return {'ok': False, 'error': 'Another user changed this pin. Wait for the refresh, then retry.'}
        return {'ok': False, 'error': 'Shared comments could not be confirmed. Keep your draft and retry.'}


def reply(card_id, parent_id, body, operation_id):
    result = call('reply', card_id, {'parent': parent_id, 'body': body,
                                   'operation_id': operation_id})
    if not result.get('ok'):
        return result
    row = result['comment']
    # Claim is durable. A timeout after claiming never permits a second POST.
    claim = call('claim', card_id, {'id': row['id']})
    if claim.get('claimed'):
        import trello_client as tc
        parent = result.get('parent') or {}
        reference = parent.get('provider_id')
        link = (f'https://trello.com/c/{card_id}#comment-{reference}' if reference
                else f'OneLoss thread {parent.get("id", "")}')
        text = f'{body}\n\nReply to {parent.get("actor", "comment")} · {link}\n[OneLoss reply {operation_id}]'
        posted = tc.post_comment(card_id, text)
        external_id = str((posted or {}).get('id') or '')
        finished = call('finish', card_id, {'id': row['id'], 'provider_id': external_id})
        if finished.get('ok'):
            row = finished['comment']
        if external_id:
            from personal_notifications import enqueue
            enqueue(card_id, row['id'], body)
    result['comment'] = row
    result['warning'] = ('' if row.get('delivery') == 'sent' else
        'Reply saved in OneLoss. Trello delivery is unconfirmed; do not repost.')
    return result
