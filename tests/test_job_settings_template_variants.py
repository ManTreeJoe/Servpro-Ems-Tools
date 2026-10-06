"""Regression fixtures for the updated residential template (no live data)."""
import job_settings as js
import pytest


@pytest.mark.parametrize('heading', ['Scope', 'Scope:', 'Scope of Work', 'Scope of Work:'])
def test_freeform_scope_heading_roundtrip(heading):
    card = f'**{heading}**\nKitchen:\nRemove material\n\n**NOTES**\nOffice Notes: keep'
    assert js.from_card(card)['scope_initial'] == 'Kitchen:\nRemove material'
    out = js.render_desc(card, {'scope_initial': 'Bath:\nProtect floor'}, ['scope_initial'])
    assert js.from_card(out)['scope_initial'] == 'Bath:\nProtect floor'
    assert 'Remove material' not in out
    assert '**NOTES**\nOffice Notes: keep' in out
    assert f'**{heading}**' in out
    cleared = js.render_desc(out, {'scope_initial': ''}, ['scope_initial'])
    assert js.from_card(cleared)['scope_initial'] == ''


def test_scope_editor_schema_is_multiline_and_visible():
    fields = {f['id']: f for f in js.schema()}
    for key in ('scope_initial', 'scope_additional'):
        assert fields[key]['multiline'] and fields[key]['core']


CARD = """**LINKS**
Initial Docusketch Link: [Tour](https://example.com/tour)
Unknown Link: preserve me

**Scope of Work:**
Initial :

Downstairs:
Kitchen - remove damaged material
Upstairs:
Bath - protect flooring

Additional:
Extra work

---

**NOTES**
Office Notes: keep these
"""


def test_updated_template_imports_multiline_scope_and_link():
    values = js.from_card(CARD)
    assert values['scope_initial'] == 'Downstairs:\nKitchen - remove damaged material\nUpstairs:\nBath - protect flooring'
    assert values['scope_additional'] == 'Extra work'
    assert values['link_docusketch'] == 'https://example.com/tour'


def test_scope_edit_replaces_old_body_without_duplication():
    out = js.render_desc(CARD, {'scope_initial': 'New room:\nNew work'}, ['scope_initial'])
    assert js.from_card(out)['scope_initial'] == 'New room:\nNew work'
    assert 'Kitchen - remove damaged material' not in out
    assert 'Additional:\nExtra work' in out
    assert '**NOTES**\nOffice Notes: keep these' in out
    assert '---' in out


def test_scope_clear_stays_empty_after_reread():
    out = js.render_desc(CARD, {'scope_initial': ''}, ['scope_initial'])
    assert js.from_card(out)['scope_initial'] == ''
    assert 'Downstairs:' not in out
    assert js.from_card(out)['scope_additional'] == 'Extra work'


def test_alias_write_and_clear_use_existing_label():
    for value in ['https://example.com/new', '']:
        out = js.render_desc(CARD, {'link_docusketch': value}, ['link_docusketch'])
        assert js.from_card(out)['link_docusketch'] == value
        assert 'Initial Docusketch Link:' in out
        assert '\nDocusketch Link:' not in out
        assert 'Unknown Link: preserve me' in out


def test_no_change_preserves_full_template():
    assert js.render_desc(CARD, js.from_card(CARD), []) == CARD


def test_scope_header_without_colon_does_not_duplicate_section():
    original = CARD.replace('**Scope of Work:**', '**Scope of Work**')
    out = js.render_desc(original, {'scope_initial': 'Replacement'}, ['scope_initial'])
    assert js.from_card(out)['scope_initial'] == 'Replacement'
    assert out.count('**Scope of Work') == 1


def test_canonical_link_explicit_blank_beats_older_alias():
    original = '**LINKS**\nDocusketch Link:\nInitial Docusketch Link: https://example.com/old'
    assert js.from_card(original)['link_docusketch'] == ''
    out = js.render_desc(original, {'link_docusketch': ''}, ['link_docusketch'])
    assert 'https://example.com/old' not in out
