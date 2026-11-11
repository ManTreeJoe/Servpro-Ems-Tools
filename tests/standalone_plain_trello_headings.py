"""Offline checks for reading and editing plain Trello section headings."""
import ast
import pathlib
import re
import runpy
import sys
import types

root = pathlib.Path(__file__).resolve().parents[1]
tree = ast.parse((root / 'trello_client.py').read_text(encoding='utf8'))
names = {'_SECTION_RE', '_KV_RE', '_PLAIN_CARD_SECTIONS',
         'description_section_header', 'adjuster_name_continuation',
         'adjuster_continuation_lines', 'parse_card_desc'}
nodes = [node for node in tree.body if
         (isinstance(node, ast.FunctionDef) and node.name in names) or
         (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in node.targets))]
fake = types.ModuleType('trello_client')
fake.__dict__['_re'] = re
exec(compile(ast.Module(body=nodes, type_ignores=[]), 'synthetic', 'exec'), fake.__dict__)
sys.modules['trello_client'] = fake
settings = runpy.run_path(str(root / 'job_settings.py'))
card = '''Lock Box:

CUSTOMER INFORMATION
Customer Name: Fictional Person
Address: 100 Example Street
Phone Number: 555-0100
Email: [test@example.invalid](mailto:test@example.invalid "label")

TENANT INFORMATION
Name: Fictional Tenant
Phone Number: 555-0101

INSURANCE INFORMATION
Insurance Company: Example Carrier
Claim Number: TEST-1
Adjuster Name:

Jordan Example
555-0112 x123
**Claim Supervisor**
Other information
PROPERTY DETAILS
Year Built: 2002
Cause of Loss: Example
**LINKS**
Initial Video Link:
https://example.invalid/video
NOTES
Office Notes: Keep this text
'''
values = settings['from_card'](card)
assert values['customer_name'] == 'Fictional Person'
assert values['phone'] == '555-0100' and values['email'] == 'test@example.invalid'
assert values['tenant_name'] == 'Fictional Tenant' and values['tenant_phone'] == '555-0101'
assert values['carrier'] == 'Example Carrier' and values['year_built'] == '2002'
assert values['adjuster_name'] == 'Jordan Example'
assert values['link_video'] == 'https://example.invalid/video'
assert values['office_notes'] == 'Keep this text'
assert settings['render_desc'](card, values, []) == card
edited = settings['render_desc'](card, {'phone':'555-0199'}, ['phone'])
assert edited.count('Phone Number: 555-0199') == 1 and 'Phone Number: 555-0101' in edited
assert settings['from_card'](edited)['phone'] == '555-0199'
cleared = settings['render_desc'](edited, {'phone':''}, ['phone'])
assert settings['from_card'](cleared)['phone'] == '' and 'Phone Number: 555-0101' in cleared
changed_adjuster = settings['render_desc'](card, {'adjuster_name':'Morgan Example'}, ['adjuster_name'])
assert 'Jordan Example' not in changed_adjuster and '555-0112 x123' in changed_adjuster
assert settings['from_card'](changed_adjuster)['adjuster_name'] == 'Morgan Example'
cleared_adjuster = settings['render_desc'](card, {'adjuster_name':''}, ['adjuster_name'])
assert 'Jordan Example' not in cleared_adjuster and '555-0112 x123' in cleared_adjuster
assert settings['from_card'](cleared_adjuster)['adjuster_name'] == ''
for continuation in ('555-0112', 'Not Assigned', 'None At This Time', 'Adjuster Email: test@example.invalid'):
    assert not fake.adjuster_name_continuation(continuation)
added = settings['render_desc'](card, {'deductible':'500'}, ['deductible'])
assert added.index('Deductible: 500') < added.index('**Claim Supervisor**')
assert fake.parse_card_desc('**NOTES**\nCustomer information\nOffice Notes: Keep') == {'NOTES': {'OFFICE NOTES': 'Keep'}}
record = {'metadata': {'settings': {'customer_name':'', 'phone':'', 'email':'', 'tenant_phone':''},
                       'trello_base': {'customer_name':'', 'phone':'', 'email':'', 'tenant_phone':''}}}
preview = settings['display_values'](record, card)
assert preview['customer_name'] == 'Fictional Person' and preview['phone'] == '555-0100'
assert preview['tenant_phone'] == '555-0101'
record['metadata']['trello_base']['phone'] = 'Old value'
assert settings['display_values'](record, card)['phone'] == '', 'intentional clear must stay blank'
namespace = settings['load'].__globals__
namespace['_record'] = lambda *args: record
fake.get_card_lite = lambda cid: {'id':cid, 'desc':card}
sys.modules['card_insurance'] = types.SimpleNamespace(enabled=lambda:False)
editor = settings['load']('synthetic', refresh=False, exact_card_id='test-card', initialize_missing=True)
assert editor['values']['customer_name'] == 'Fictional Person'
assert editor['values']['phone'] == '' and any(row['id'] == 'phone' for row in editor['conflicts'])
assert editor['values']['tenant_phone'] == '555-0101'
assert editor['values']['carrier'] == 'Example Carrier' and editor['values']['year_built'] == '2002'
complete = {key: '' for key in namespace['BY_ID']}
complete.update({key: 'Present' for key in namespace['_ACCOUNT_FIELDS']})
record = {'metadata': {'settings': complete.copy(), 'trello_base': complete.copy()}}
namespace['_record'] = lambda *args: record
seen = []
def get_card(card_id):
    seen.append(card_id)
    name = {'ems-card': 'Jordan Example', 'contents-card': 'Morgan Example'}[card_id]
    return {'id': card_id, 'desc': card.replace('Jordan Example', name)}
fake.get_card_lite = get_card
for card_id, expected in [('ems-card', 'Jordan Example'), ('contents-card', 'Morgan Example')]:
    editor = settings['load']('synthetic', refresh=False, exact_card_id=card_id, initialize_missing=True)
    assert editor['values']['adjuster_name'] == expected
assert seen == ['ems-card', 'contents-card']
record['metadata']['trello_base']['adjuster_name'] = 'Previous Adjuster'
editor = settings['load']('synthetic', refresh=False, exact_card_id='ems-card', initialize_missing=True)
assert editor['values']['adjuster_name'] == ''
assert any(c['id'] == 'adjuster_name' for c in editor['conflicts'])
def unavailable(_card_id):
    raise OSError('offline')
fake.get_card_lite = unavailable
editor = settings['load']('synthetic', refresh=False, exact_card_id='ems-card', initialize_missing=True)
assert editor['values']['adjuster_name'] == '' and editor['values']['customer_name'] == 'Present'
assert editor['error']
print('PASS: plain headings read, edit, clear, and add without mixing tenant or insurance')
