"""Exercise the card-read boundary with in-memory providers only."""
import ast
import pathlib
import sys
import types

tree = ast.parse((pathlib.Path(__file__).resolve().parents[1] / 'notifications_web.py').read_text(encoding='utf-8'))
api = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Api')
method = next(node for node in api.body if isinstance(node, ast.FunctionDef) and node.name == 'mark_card_read')
namespace = {}
exec(compile(ast.Module(body=[method], type_ignores=[]), 'synthetic', 'exec'), namespace)
mark = namespace['mark_card_read']
card = 'a' * 24
other = 'b' * 24
actions = []
trello = types.ModuleType('trello_client')
trello.list_all_unread_notifications = lambda: [
    {'id': 't1', 'data': {'card': {'id': card}}},
    {'id': 't2', 'data': {'card': {'id': other}}},
]
trello.mark_notification_read = lambda ident, read: actions.append(('trello', ident)) or True
personal = types.ModuleType('personal_notifications')
personal.sb = types.SimpleNamespace(current_user=lambda: {'id': 'actor'})
def call(action, **kwargs):
    if action == 'inbox':
        return {'ok': True, 'items': [{'id': 'p1', 'card_id': card}, {'id': 'p2', 'card_id': other}]}
    actions.append(('personal', kwargs['id']))
    return {'ok': True}
personal.call = call
sys.modules['trello_client'] = trello
sys.modules['personal_notifications'] = personal
assert mark(None, card)['ok']
assert actions == [('trello', 't1'), ('personal', 'p1')]
assert not mark(None, 'unverified')['ok']
actions.clear()
personal.call = lambda action, **kwargs: {'ok': True, 'items': [{'id': str(i), 'card_id': other} for i in range(100)]}
result = mark(None, card)
assert not result['ok'] and 'OneLoss' in result['error']
assert actions == [('trello', 't1')]
trello.mark_notification_read = lambda ident, read: False
personal.call = call
result = mark(None, card)
assert not result['ok'] and 'Trello' in result['error']
print('PASS: exact-card matching, both providers, partial failures and incomplete inbox')
