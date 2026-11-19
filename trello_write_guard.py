"""Single desktop Trello write policy. Reads remain available by default.

Only an operator's exact ONELOSS_TRELLO_WRITES_ENABLED=true opt-in permits
mutations. Saved tokens and the server's legacy mirror flag are not permission.
"""
import os


class TrelloWritesDisabled(RuntimeError):
    pass


def require_write_enabled(method):
    method = str(method or '').upper()
    if method in {'GET', 'HEAD'}:
        return
    if (method not in {'POST', 'PUT', 'PATCH', 'DELETE'}
            or os.environ.get('ONELOSS_TRELLO_WRITES_ENABLED') != 'true'
            or os.environ.get('LINGUAR_CHANNEL', '').lower() == 'dev'):
        raise TrelloWritesDisabled('Trello writes are disabled. No Trello change was sent.')
