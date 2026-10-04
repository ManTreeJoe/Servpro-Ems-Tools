"""Read-only exact-card/comment navigation; never repair links or guess names."""
import re
from urllib.parse import urlsplit
import supabase_client as sb


def _card_aliases(card):
    """Identifiers from this authorized mirror only; never match job names."""
    payload = card.get('payload') or {}
    aliases = {card['card_id']}
    short = payload.get('shortLink')
    if re.fullmatch(r'[A-Za-z0-9]{8}', str(short or '')):
        aliases.add(short)
    for field in ('shortUrl', 'url'):
        try:
            url = urlsplit(str(payload.get(field) or ''))
        except ValueError:
            continue
        match = re.fullmatch(r'/c/([A-Za-z0-9]{8})(?:/[^/]*)?', url.path)
        if url.scheme == 'https' and url.netloc == 'trello.com' and match:
            aliases.add(match.group(1))
    return aliases


def resolve(card_id):
    if not re.fullmatch(r'[0-9a-fA-F]{24}|[A-Za-z0-9]{8}', str(card_id or '')):
        raise ValueError('This notification has no valid job card.')
    with sb.interactive_requests(seconds=8):
        filters = [f'card_id.eq.{card_id}', f'payload->>shortLink.eq.{card_id}']
        if len(card_id) == 8:
            filters.extend((f'payload->>shortUrl.eq.https://trello.com/c/{card_id}',
                            f'payload->>url.like.https://trello.com/c/{card_id}/*'))
        cards = sb.rest('GET', 'hub_trello_mirror_cards', params={
            'select':'card_id,payload', 'or':'(' + ','.join(filters) + ')', 'limit':'2'}) or []
        if len(cards) != 1:
            raise ValueError('This card is not available in your OneLoss workspace. Open it in Trello instead.')
        card=cards[0]; aliases=_card_aliases(card)
        links=sb.rest('GET','job_links',params={'select':'canon_key,link_type',
            'link_type':'in.(trello_card,trello_card_contents,trello_card_recon)',
            'link_value':'in.('+','.join(sorted(aliases))+')'}) or []
        matches={(row['canon_key'],row['link_type']) for row in links}
        if len(matches)!=1:
            raise ValueError('This card does not have one verified OneLoss job link. Open it in Trello instead.')
        canon,kind=next(iter(matches))
        jobs=sb.rest('GET','jobs',params={'select':'display_name','canon_key':'eq.'+canon,'limit':'1'}) or []
        if not jobs:
            raise ValueError('This job is unavailable to your OneLoss account.')
    return {'ok':True,'client':jobs[0]['display_name'],'cardId':card['card_id'],
            'division':{'trello_card_contents':'Contents','trello_card_recon':'Recon'}.get(kind,'EMS')}


def comment(card_id, comment_id):
    if not re.fullmatch(r'[0-9a-fA-F]{24}', str(comment_id or '')):
        return {'ok':False,'error':'The notification has no exact comment ID.'}
    context=resolve(card_id)
    import trello_client as tc
    action=tc._call('/actions/'+comment_id,params={'memberCreator':'true'},_timeout=8,_max_retries=0) or {}
    data=action.get('data') or {}
    if action.get('type')!='commentCard' or (data.get('card') or {}).get('id')!=context['cardId']:
        return {'ok':False,'error':'The exact comment is no longer available on this card.'}
    creator=action.get('memberCreator') or {}
    return {'ok':True,'comment':{'id':comment_id,'external_id':comment_id,'source':'trello',
        'actor':creator.get('fullName') or creator.get('username') or 'Trello',
        'text':data.get('text') or '', 'at':action.get('date') or '', 'can_manage':False}}
