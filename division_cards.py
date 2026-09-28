"""Division boundaries use board evidence, never customer or lane names."""
import re


def board_division(name):
    words = set(re.findall(r'[a-z]+', str(name or '').casefold()))
    if words & {'contents', 'content'}:
        return 'CONTENTS'
    if words & {'recon', 'reconstruction', 'repair', 'repairs'}:
        return 'RECON'
    if re.search(r'\bwork\s+in\s+progress\b', str(name or ''), re.I):
        return 'EMS'
    if words & {'ems', 'wip', 'estimating', 'estimation', 'mitigation'}:
        return 'EMS'
    return ''


def validate_pin(card_id, division):
    """Validate exact board before any write, resolving short links too."""
    import trello_client as tc
    card = tc.get_card_lite(card_id) or {}
    board_id = card.get('idBoard')
    board = next((b for b in tc.list_boards() if b.get('id') == board_id), {}) if board_id else {}
    actual = board_division(board.get('name'))
    if not actual:
        raise ValueError('Cannot verify this card’s division from its board. The existing pin was not changed.')
    if actual != division:
        raise ValueError(f'This is a {actual} card, not {division}. The existing pin was not changed.')
    return str(card.get('id') or card_id)
