"""Unsigned, editable WC documents. Never writes job facts or sends a form."""
from pathlib import Path
import io

TEMPLATES = Path(__file__).resolve().parent / 'form_templates'
FORMS = {
    'atp': 'ATP — Authorization to Perform',
    'cif': 'CIF — Customer Information (water damage)',
    'cos': 'COS — Certificate of Satisfaction',
    'cer': 'CER — Customer Equipment Responsibility',
    'statefarm_atp': 'State Farm — Authorization to Pay',
}
# Only factual text fields may be filled. Consent, survey, signatures and signing
# dates are intentionally excluded, including fields whose names vary by edition.
FIELDS = {
    'InsuredName': ('Customer / insured name', 'customer_name'),
    'LossOccuredDate': ('Date of loss', 'date_of_loss'),
    'LossAddress': ('Loss street address (review city/state below)', 'address'),
    'LossCity': ('City', ''), 'LossState': ('State', ''),
    'LossZipCode': ('ZIP code', ''),
    'ClaimNumber': ('Claim number', 'claim_number'),
    'InsuranceCompany': ('Insurance company', 'carrier'),
    'InsuredEmail': ('Insured email', 'email'),
    'Deductible': ('Deductible', 'deductible'),
    'Enter Deductible Amount': ('Deductible', 'deductible'),
    'PolicyNumber': ('Policy number', ''),
    'LossCause': ('Cause of loss', 'cause_of_loss'),
    'FranchiseName': ('Franchise name', 'franchise_name'),
    'FullFranchiseName': ('Full franchise name', 'full_franchise_name'),
    'OperatingEntityFranchiseLegalName': ('Operating entity / legal name', 'legal_name'),
    'ContractorLicense': ('Contractor license', ''),
    'FranchisePhoneNumber': ('Franchise phone', 'office_phone'),
    'Remarks': ('Remarks', ''),
}


def reader(form_id):
    from pypdf import PdfReader
    if form_id not in FORMS:
        raise ValueError('Choose a supported form.')
    result = PdfReader(TEMPLATES / (form_id + '.pdf'))
    for field in (result.get_fields() or {}).values():
        if field.get('/FT') == '/Sig' and field.get('/V'):
            raise ValueError('Signed templates cannot be used for new drafts.')
    return result


def catalog(values):
    forms = []
    for key, title in FORMS.items():
        available = reader(key).get_fields() or {}
        fields = [dict(id=name, label=label, value=str(values.get(source) or '') if source else '')
                  for name, (label, source) in FIELDS.items() if name in available]
        forms.append(dict(id=key, title=title, fields=fields))
    return forms


def render(form_id, values):
    from pypdf import PdfWriter, PdfReader
    if not isinstance(values, dict):
        raise ValueError('Review the form details before saving.')
    source = reader(form_id)
    fields = source.get_fields() or {}
    allowed = set(FIELDS) & set(fields)
    if set(values) - allowed:
        raise ValueError('Signing and customer-response fields cannot be prefilled.')
    writer = PdfWriter()
    writer.clone_document_from_reader(source)
    # Clear ALL text defaults, including date and template customer examples.
    updates = {name: '' for name, field in fields.items() if field.get('/FT') == '/Tx'}
    for name, value in values.items():
        if not isinstance(value, str) or len(value) > 2000:
            raise ValueError('Form values must be text of at most 2,000 characters.')
        updates[name] = value
    writer.update_page_form_field_values(None, updates, auto_regenerate=False)
    output = io.BytesIO()
    writer.write(output)
    data = output.getvalue()
    verified = PdfReader(io.BytesIO(data)).get_fields() or {}
    for name, value in updates.items():
        if str(verified[name].get('/V', '')) != value:
            raise ValueError('The PDF could not retain its editable values.')
    return data


class JobFormsApi:
    def job_forms_preview(self, form_id, values):
        """Render locally in memory; no shared storage or temporary client files."""
        try:
            import base64
            import pypdfium2 as pdfium
            pages = []
            with pdfium.PdfDocument(render(form_id, values)) as pdf:
                pdf.init_forms()
                for index in range(len(pdf)):
                    page = pdf[index]
                    try:
                        bitmap = page.render(scale=1.4)
                        try:
                            image = bitmap.to_pil()
                            output = io.BytesIO()
                            image.save(output, format='PNG')
                            pages.append(base64.b64encode(output.getvalue()).decode('ascii'))
                        finally:
                            bitmap.close()
                    finally:
                        page.close()
            return {'ok': True, 'pages': pages}
        except Exception as ex:
            return {'ok': False, 'error': str(ex)}

    def job_forms_load(self, client, card_id):
        try:
            import job_saved_data
            import job_settings
            job, _ = job_saved_data.resolve(client, card_id)
            if not job:
                raise ValueError('No saved job is linked to this card. Link it before preparing forms.')
            loaded = job_settings.load(job['canon_key'], refresh=bool(card_id),
                                       exact_card_id=card_id, initialize_missing=False)
            if not loaded.get('ok'):
                raise ValueError(loaded.get('error') or 'Job details could not load.')
            values = dict(loaded.get('values') or {})
            import config
            # Read configured identity, never infer the company from a customer
            # or copy another office's example template values.
            identity = config.load()
            full_name = str(identity.get('franchise_name') or '').strip()
            import re
            parts = re.split(r'\s+d/b/a\s+', full_name, maxsplit=1, flags=re.I)
            values.update(franchise_name=parts[-1], full_franchise_name=parts[-1],
                          legal_name=parts[0] if len(parts) == 2 else '',
                          office_phone=str(identity.get('office_phone') or '').strip())
            notices = []
            if loaded.get('error'):
                notices.append('Card details could not refresh; showing saved job details.')
            if loaded.get('conflicts'):
                notices.append('Saved job and card differ: ' + ', '.join(
                    field.get('label', field.get('id', 'field')) for field in loaded['conflicts'])
                    + '. Saved values were kept; review before sending.')
            return {'ok': True, 'forms': catalog(values), 'notice': ' '.join(notices)}
        except Exception as ex:
            return {'ok': False, 'error': str(ex)}

    def job_forms_export(self, form_id, values):
        try:
            import webview
            data = render(form_id, values)
            if self._window is None:
                raise ValueError('The job window is not ready.')
            result = self._window.create_file_dialog(
                webview.SAVE_DIALOG, save_filename=f'{form_id.upper()} - unsigned.pdf',
                file_types=('PDF (*.pdf)',))
            if not result:
                return {'ok': True, 'cancelled': True}
            path = Path(result[0] if isinstance(result, (tuple, list)) else result)
            if path.suffix.lower() != '.pdf':
                path = path.with_name(path.name + '.pdf')
            if path.resolve().is_relative_to(TEMPLATES.resolve()):
                raise ValueError('Save outside the template folder to preserve the originals.')
            path.write_bytes(data)
            return {'ok': True, 'path': str(path)}
        except Exception as ex:
            return {'ok': False, 'error': str(ex)}
