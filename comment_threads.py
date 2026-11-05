"""Shared comment annotations and durable replies. Never fall back to an unlinked post."""
import supabase_client as sb
import re


def prepare_parent(card_id, parent_id):
    try:
        return sb.invoke_function('comment-parent', {'card_id': card_id, 'parent_id': parent_id})
    except Exception:
        return {'ok': False, 'error': 'Could not verify the original comment. Your draft is kept; retry.'}


def reply_mentions(body, parent, username, aliases=None):
    """Reply-all usernames; preserve spelling but deduplicate case-insensitively."""
    pattern = r'(?<![\w@])@([A-Za-z0-9_][A-Za-z0-9_.-]*)'
    aliases = aliases or {}
    def mapped(name):
        return aliases.get(name.casefold(), name)
    body = re.sub(pattern, lambda match: '@' + mapped(match[1]), body)
    seen = {mapped(username).casefold()} | {u.casefold() for u in re.findall(pattern, body)}
    recipients = [parent.get('author_username', '')] + re.findall(pattern, parent.get('body', ''))
    tags = []
    for name in recipients:
        name = mapped(name)
        if re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', name) and name.casefold() not in seen:
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
            result = sb.rpc('job_comment_threads', {'p_action': action,
                          'p_card': card_id, 'p_data': data or {}})
            who = str((sb.current_user() or {}).get('id') or '')
            for row in result.get('comments', []) + ([result['comment']] if result.get('comment') else []):
                row['can_edit'] = bool(who and row.get('native') and str(row.get('author_id') or '') == who
                                      and row.get('delivery') == 'sent' and row.get('provider_id'))
            return result
    except Exception as error:
        import app_error_reports
        app_error_reports.capture_failure('pipeline', 'comment_threads_' + action, error,
                                         {'card_id': str(card_id or '')})
        message = str(error)
        if 'Comment is not in the shared snapshot yet' in message:
            return {'ok': False, 'code': 'parent_missing', 'error': 'This comment has not reached the shared snapshot yet. Give it a moment, then retry.'}
        if 'Card access required' in message:
            return {'ok': False, 'error': 'This card is not available to your signed-in OneLoss account.'}
        if 'Pin changed' in message:
            return {'ok': False, 'error': 'Another user changed this pin. Wait for the refresh, then retry.'}
        return {'ok': False, 'error': 'Shared comments could not be confirmed. Keep your draft and retry.'}


def edit(card_id, comment_id, body, expected):
    """Update the shared reply, then its exact provider action; never repost."""
    body = str(body or '').strip()
    if not body or len(body) > 20000:
        return {'ok': False, 'error': 'Reply must contain 1–20,000 characters.'}
    try:
        result = sb.rpc('edit_job_reply', {'p_card': card_id, 'p_id': comment_id,
                        'p_body': body, 'p_expected': expected})
    except Exception as error:
        import app_error_reports
        app_error_reports.report('pipeline', 'edit_job_reply', error)
        return {'ok': False, 'error': 'Reply could not be saved. Refresh to check for changes; your draft is kept.'}
    if not result.get('ok'):
        return result
    row = result['comment']
    row['can_edit'] = True  # The RPC has checked author and exact-card access.
    import trello_client as tc
    synced = tc.update_comment(row['provider_id'], body)
    return {**result, 'text': body, 'warning': '' if synced else
            'Saved in OneLoss, but Trello did not update. Retry saving this edit when connected.'}


def reply(card_id, parent_id, body, operation_id):
    import trello_client as tc
    parent_context = prepare_parent(card_id, parent_id)
    if not parent_context.get('ok'):
        return parent_context
    me = tc.get_member_me() or {}
    if not me.get('username'):
        return {'ok': False, 'error': 'Reconnect Trello before replying. Your draft is kept.'}
    aliases = {}
    if '@ol.' in (body + ' ' + str(parent_context.get('body') or '') + ' @' + str(parent_context.get('author_username') or '')).lower():
        from personal_notifications import mention_members
        people = mention_members(card_id)
        if not people.get('ok'):
            return {'ok': False, 'error': 'Could not verify linked mention accounts. Your draft is kept; retry.'}
        for person in people.get('members', []):
            old, linked = str(person.get('username') or ''), str(person.get('trello_username') or '')
            if person.get('trello_member_id') and re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', linked):
                aliases[old.casefold()] = linked
    body = reply_mentions(body, parent_context, me['username'], aliases)
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
            from comment_delivery import notify
            result['notification_warning'] = notify(card_id, row['id'], body)
    result['comment'] = row
    result['warning'] = ('' if row.get('delivery') == 'sent' else
        'Reply saved in OneLoss. Trello delivery is unconfirmed; do not repost.')
    return result
