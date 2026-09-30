"""Create the second EMS board representation without moving the source.

The shared, permanent reservation precedes the external POST. A lost response
is reconciled by its exact operation marker; it is never blindly retried.
"""
import ems_card_copies as copies
import ems_db
import supabase_client as sb
import trello_client as tc


def _context(client, source_id):
    source_id = tc.parse_card_identifier(source_id)
    job = ems_db.find_job_by_name(client)
    source = tc.get_card_lite(source_id, fields='name,desc,idBoard,idList,closed,shortLink') or {}
    if not job or source.get('closed') is not False or source.get('idBoard') not in copies.MAIN_BOARDS:
        raise ValueError('Choose an open EMS card on main WIP or Estimating.')
    aliases = {source_id, source.get('id'), source.get('shortLink')} - {None, ''}
    links = ems_db.get_links(job['canon_key'], 'trello_card') or []
    if not any(link['link_value'] in aliases for link in links):
        raise ValueError('The source must already be linked to this EMS job.')
    for alias in aliases:
        for kind in ('trello_card_contents', 'trello_card_recon'):
            if ems_db.find_job_by_link(kind, alias):
                raise ValueError('Contents and Recon cards cannot be copied as EMS.')
    target = next(board for board in copies.MAIN_BOARDS if board != source['idBoard'])
    existing = []
    for link in links:
        if link['link_value'] in aliases:
            continue
        card = tc.get_card_lite(link['link_value'], fields='idBoard,closed,shortUrl') or {}
        if card.get('idBoard') == target and card.get('closed') is False:
            existing.append(card)
    if len(existing) > 1:
        raise ValueError('Multiple linked copies exist. Review their links before copying.')
    lists = tc._call(f'/boards/{target}/lists', params={'filter':'open', 'fields':'name,closed'}) or []
    return job, source, target, existing, lists


def preview(client, source_id):
    _, source, target, existing, lists = _context(client, source_id)
    return {'ok': True, 'source_id': source['id'], 'target_board': target,
            'target_name': 'Estimating' if copies.MAIN_BOARDS[target] == 'estimating' else 'Work in Progress',
            'name': source.get('name', ''), 'lists': lists,
            'existing': existing[0] if existing else None}


def create(client, source_id, list_id):
    job, source, target, existing, lists = _context(client, source_id)
    if existing:
        return {'ok': True, 'existing': True, 'card_id': existing[0]['id'],
                'url': existing[0].get('shortUrl') or f"https://trello.com/c/{existing[0]['id']}"}
    if not any(row['id'] == list_id and not row.get('closed') for row in lists):
        raise ValueError('Choose an open section on the destination board.')
    # Direct authenticated shared write, never the offline queue/fallback.
    params = {'canon_key': 'eq.' + job['canon_key'], 'target_board': 'eq.' + target}
    claimed = sb.rest('POST', 'ems_copy_reservations',
        params={'on_conflict':'canon_key,target_board'},
        body={'canon_key':job['canon_key'], 'target_board':target, 'source_card':source['id']},
        prefer='resolution=ignore-duplicates,return=representation')
    rows = claimed or sb.rest('GET', 'ems_copy_reservations', params=params)
    if not rows:
        raise ValueError('Copy safety reservation unavailable. No card was created.')
    marker = f"[OneLoss EMS copy {rows[0]['operation_id']}]"
    if not claimed:
        candidates = tc._call(f'/boards/{target}/cards', params={'filter':'all','fields':'desc,closed,shortUrl'})
        matches = [card for card in candidates or [] if marker in (card.get('desc') or '')]
        if len(matches) != 1 or matches[0].get('closed'):
            return {'ok':False, 'uncertain':True, 'error':
                    'A copy was already requested. No second card was created. Check the destination board and use Link existing copy if needed.'}
        copied = matches[0]
    else:
        description = (source.get('desc') or '').rstrip() + '\n\n' + marker
        try:
            copied = tc.create_card(list_id, source.get('name') or client, desc=description)
            if not copied or not copied.get('id'):
                raise ValueError('No card ID returned')
        except Exception:
            return {'ok':False, 'uncertain':True, 'error':
                    'Trello did not confirm the copy. Check again to recover it; this app will not send another create request.'}
    try:
        return copies.link_copy(client, source['id'], copied['id'])
    except Exception:
        return {'ok':False, 'card_id':copied['id'],
                'url':copied.get('shortUrl') or f"https://trello.com/c/{copied['id']}",
                'error':'The card exists, but its job link could not be saved. Check again to finish linking; do not create another copy.'}
