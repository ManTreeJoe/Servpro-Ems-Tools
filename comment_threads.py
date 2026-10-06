"""Shared comment annotations and durable replies. Never fall back to an unlinked post."""
import supabase_client as sb
import re


def prepare_parent(card_id, parent_id):
    try:
        return sb.invoke_function('comment-parent', {'card_id': card_id, 'parent_id': parent_id})
    except Exception:
        return {'ok': False, 'error': 'Could not verify the original comment. Your draft is kept; retry.'}


def reply_mentions(body, parent, username):
    """Reply-all usernames; preserve spelling but deduplicate case-insensitively."""
    pattern = r'(?<![\w@])@([A-Za-z0-9_]+)'
    seen = {username.casefold()} | {u.casefold() for u in re.findall(pattern, body)}
    recipients = [parent.get('author_username', '')] + re.findall(pattern, parent.get('body', ''))
    tags = []
    for name in recipients:
        if re.fullmatch(r'[A-Za-z0-9_]+', name) and name.casefold() not in seen:
            seen.add(name.casefold())
            tags.append('@' + name)
    return (' '.join(tags) + '\n\n' if tags else '') + body


def pin(card_id, comment_id, pinned, expected):
    result = call('pin', card_id, {'id': comment_id, 'pinned': pinned, 'expected': expected})
    if result.get('ok') or result.get('code') != 'parent_missing':
        return result
    parent = prepare_parent(card_id, comment_id)
    if not parent.get('ok'):
        return parent
    return call('pin', card_id, {'id': parent['parent_id'], 'pinned': pinned, 'expected': expected})


def call(action, card_id, data=None):
    try:
        with sb.interactive_requests(seconds=12):
            return sb.rpc('job_comment_threads', {'p_action': action,
                          'p_card': card_id, 'p_data': data or {}})
    except Exception as error:
        message = str(error)
        if 'Comment is not in the shared snapshot yet' in message:
            return {'ok': False, 'code': 'parent_missing', 'error': 'This comment has not reached the shared snapshot yet. Give it a moment, then retry.'}
        if 'Card access required' in message:
            return {'ok': False, 'error': 'This card is not available to your signed-in OneLoss account.'}
        if 'Pin changed' in message:
            return {'ok': False, 'error': 'Another user changed this pin. Wait for the refresh, then retry.'}
        return {'ok': False, 'error': 'Shared comments could not be confirmed. Keep your draft and retry.'}


def reply(card_id, parent_id, body, operation_id):
    import trello_client as tc
    parent_context = prepare_parent(card_id, parent_id)
    if not parent_context.get('ok'):
        return parent_context
    me = tc.get_member_me() or {}
    if not me.get('username'):
        return {'ok': False, 'error': 'Reconnect Trello before replying. Your draft is kept.'}
    body = reply_mentions(body, parent_context, me['username'])
    parent_id = parent_context['parent_id']
    result = call('reply', card_id, {'parent': parent_id, 'body': body,
                                   'operation_id': operation_id})
    if not result.get('ok'):
        return result
    row = result['comment']
    # Claim is durable. A timeout after claiming never permits a second POST.
    claim = call('claim', card_id, {'id': row['id']})
    if claim.get('claimed'):
        # Relationships and operation IDs belong in shared storage, not in the
        # user-visible Trello message. Uncertain delivery is never auto-reposted.
        posted = tc.post_comment(card_id, body)
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
