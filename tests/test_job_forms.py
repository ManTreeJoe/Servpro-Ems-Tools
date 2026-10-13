import io
import pytest
from pypdf import PdfReader
import job_forms


@pytest.mark.parametrize('form_id', job_forms.FORMS)
def test_unsigned_editable_clean_draft(form_id):
    source = job_forms.reader(form_id)
    result = PdfReader(io.BytesIO(job_forms.render(form_id, {'InsuredName': 'Test Customer'})))
    assert len(result.pages) == len(source.pages)
    fields = result.get_fields()
    assert fields.keys() == source.get_fields().keys()
    assert fields['InsuredName']['/V'] == 'Test Customer'
    for name, field in fields.items():
        if field.get('/FT') == '/Sig':
            assert not field.get('/V')
        elif field.get('/FT') == '/Tx' and name != 'InsuredName':
            assert not field.get('/V')
        elif field.get('/FT') == '/Btn':
            assert field.get('/V') in (None, '', '/Off')
    for page in result.pages:
        for ref in page.get('/Annots', []):
            widget = ref.get_object()
            if widget.get('/T') == 'InsuredName':
                assert '/N' in widget['/AP']


def test_no_signing_or_unknown_fields():
    with pytest.raises(ValueError):
        job_forms.render('atp', {'TodaysDate': '10/12/2026'})
    with pytest.raises(ValueError):
        job_forms.render('../atp', {})


def test_only_known_facts_prefilled():
    forms = job_forms.catalog({'customer_name': 'Test', 'date_of_loss': '10/11/2026'})
    for form in forms:
        fields = {f['id']: f['value'] for f in form['fields']}
        assert fields['InsuredName'] == 'Test'
        assert fields['LossOccuredDate'] == '10/11/2026'
        assert 'TodaysDate' not in fields
        assert fields.get('FranchiseName', '') == ''


def test_save_cancel_has_no_file_write(monkeypatch):
    import types
    class Window:
        def create_file_dialog(self, *args, **kwargs):
            return None
    api = job_forms.JobFormsApi()
    api._window = Window()
    assert api.job_forms_export('atp', {}) == {'ok': True, 'cancelled': True}


def test_signed_template_is_rejected(monkeypatch):
    import pypdf
    class SignedReader:
        def get_fields(self):
            return {'Signature': {'/FT': '/Sig', '/V': {'/Contents': 'signature'}}}
    monkeypatch.setattr(pypdf, 'PdfReader', lambda path: SignedReader())
    with pytest.raises(ValueError, match='Signed'):
        job_forms.reader('atp')


def test_in_memory_preview():
    import base64
    result = job_forms.JobFormsApi().job_forms_preview('atp', {'InsuredName': 'Preview Customer'})
    assert result['ok'], result
    assert len(result['pages']) == 2
    assert base64.b64decode(result['pages'][0]).startswith(b'\x89PNG')


def test_load_uses_exact_card_details(monkeypatch):
    import sys
    import types
    import job_settings
    monkeypatch.setitem(sys.modules, 'job_saved_data', types.SimpleNamespace(resolve=lambda *_: ({'canon_key': 'exact-job'}, 'EMS')))
    calls = []
    def load(key, **kwargs):
        calls.append((key, kwargs))
        return {'ok': True, 'values': {'customer_name': 'Saved Customer', 'carrier': 'Saved Carrier', 'date_of_loss': '10/11/2026'}}
    monkeypatch.setattr(job_settings, 'load', load)
    result = job_forms.JobFormsApi().job_forms_load('Display title', 'exact-card')
    assert result['ok'], result
    fields = {f['id']: f['value'] for f in result['forms'][1]['fields']}
    assert fields['InsuredName'] == 'Saved Customer'
    assert fields['InsuranceCompany'] == 'Saved Carrier'
    assert calls[0][0] == 'exact-job'
    assert calls[0][1] == {'refresh': True, 'exact_card_id': 'exact-card', 'initialize_missing': False}


def test_unimported_card_prefills_without_writes(monkeypatch):
    import sys
    import types
    import job_settings
    import config
    monkeypatch.setitem(sys.modules, 'job_saved_data', types.SimpleNamespace(resolve=lambda *_: ({'canon_key': 'exact'}, 'EMS')))
    monkeypatch.setattr(job_settings, '_record', lambda *_: {'canon_key': 'exact'})
    def card(card_id):
        assert card_id == 'exact-card'
        return {'desc': '**CUSTOMER INFORMATION**\nCUSTOMER NAME: Sample Insured\n**INSURANCE INFORMATION**\nINSURANCE COMPANY: Sample Carrier\nDEDUCTIBLE: $1,000\n**PROPERTY DETAILS**\nDATE OF LOSS: 10/11/2026'}
    import trello_client
    monkeypatch.setattr(trello_client, 'get_card_lite', card)
    monkeypatch.setattr(config, 'load', lambda: {'franchise_name': 'Example LLC d/b/a SERVPRO of Example', 'office_phone': '555-0100'})
    result = job_forms.JobFormsApi().job_forms_load('Do not name-match', 'exact-card')
    assert result['ok'], result
    fields = {f['id']: f['value'] for f in result['forms'][1]['fields']}
    assert fields['InsuredName'] == 'Sample Insured'
    assert fields['InsuranceCompany'] == 'Sample Carrier'
    assert fields['LossOccuredDate'] == '10/11/2026'
    assert fields['Enter Deductible Amount'] == '$1,000'
    assert fields['FranchiseName'] == 'SERVPRO of Example'
    assert fields['OperatingEntityFranchiseLegalName'] == 'Example LLC'
