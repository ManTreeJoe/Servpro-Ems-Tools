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
    'statefarm_atr': 'State Farm — Authorization to Repair',
    'statefarm_warranty': 'State Farm — Warranty Form',
    'selfpay_contract': 'Self-pay — Home Improvement Contract',
    'selfpay_cancel': 'Self-pay — Notice of Right to Cancel',
    'liability_release': 'Liability Release form',
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

# Office pickup hours approved for CER drafts. The template prints a.m./p.m.
# These are form-specific defaults, not customer responses or signing fields.
FORM_DEFAULTS = {
    'cer': {
        'The above equipment may be picked up between the hours of': '8',
        'am and': '5',
    },
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
        forms.append(dict(id=key, title=title, fields=fields, fillable=bool(available)))
    import form_builder
    for row in form_builder.listing():
        custom = form_builder.get(row['id'])
        forms.append(dict(id=row['id']+'@'+str(row['revision']), title=row['title']+' (mapped)', fillable=True,
            fields=[dict(id=f['id'], label=form_builder.SOURCES[f['source']],
                         multiline=bool(f.get('multiline')),
                         value=str(values.get(f['source']) or '') if f['source']!='manual' else '')
                    for f in custom['fields']]))
    return forms


def render(form_id, values):
    if str(form_id).startswith('custom_'):
        import form_builder
        return form_builder.render(form_builder.get(form_id), values)
    from pypdf import PdfWriter, PdfReader
    if not isinstance(values, dict):
        raise ValueError('Review the form details before saving.')
    source = reader(form_id)
    fields = source.get_fields() or {}
    allowed = set(FIELDS) & set(fields)
    if set(values) - allowed:
        raise ValueError('Signing and customer-response fields cannot be prefilled.')
    if not fields:
        # Reviewed blank, static originals: preserve every page byte-for-byte.
        return (TEMPLATES / (form_id + '.pdf')).read_bytes()
    writer = PdfWriter()
    writer.clone_document_from_reader(source)
    # Clear ALL text defaults, including date and template customer examples.
    updates = {name: '' for name, field in fields.items() if field.get('/FT') == '/Tx'}
    # New ATR template includes a preselected AM choice. No customer choice
    # or time-of-day selection should be carried into a fresh draft.
    updates.update({name: '/Off' for name, field in fields.items() if field.get('/FT') == '/Btn'})
    updates.update({name: value for name, value in FORM_DEFAULTS.get(form_id, {}).items()
                    if name in fields and fields[name].get('/FT') == '/Tx'})
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


def preview_bytes(data):
    import base64
    import pypdfium2 as pdfium
    pages=[]
    with pdfium.PdfDocument(data) as pdf:
        pdf.init_forms()
        for i in range(len(pdf)):
            page=pdf[i]
            try:
                bitmap=page.render(scale=1.2)
                try:
                    output=io.BytesIO(); bitmap.to_pil().save(output,format='PNG')
                    pages.append(base64.b64encode(output.getvalue()).decode('ascii'))
                finally: bitmap.close()
            finally: page.close()
    return pages


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
            if not job and card_id:
                # Forms need shared job facts, not a division destination.
                # A card with only the legacy/shared Trello link is still an
                # exact link; never fall back to a customer-name match.
                import ems_db
                job = ems_db.find_job_by_reference(ems_db.LINK_TRELLO, card_id)
            loaded = {}
            values = {}
            notices = []
            if job:
                loaded = job_settings.load(job['canon_key'], refresh=bool(card_id),
                                           exact_card_id=card_id, initialize_missing=False)
                if not loaded.get('ok'):
                    raise ValueError(loaded.get('error') or 'Job details could not load.')
                values = dict(loaded.get('values') or {})
            else:
                notices.append('No saved job is linked to this card. This is a blank draft; customer and loss details must be entered manually. Link the card to prefill them.')
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
            if loaded.get('error'):
                notices.append('Card details could not refresh; showing saved job details.')
            if loaded.get('conflicts'):
                notices.append('Saved job and card differ: ' + ', '.join(
                    field.get('label', field.get('id', 'field')) for field in loaded['conflicts'])
                    + '. Saved values were kept; review before sending.')
            forms = catalog(values)
            if any(f['id'].startswith('custom_') for f in forms):
                import form_builder
                custom_values = dict(values)
                scoped = ('claim_number','carrier','adjuster_name','adjuster_phone','adjuster_email')
                # Mapped forms must never borrow another division's insurance.
                custom_values.update({key:'' for key in scoped})
                if job:
                    try:
                        import card_insurance
                        source = card_insurance.source_card(card_id)
                        parsed = job_settings.from_card(source.get('desc') or '')
                        custom_values.update({key:parsed.get(key,'') for key in scoped})
                        if card_insurance.enabled():
                            record=card_insurance.read(job,card_id)
                            if record.get('revision'):
                                custom_values.update({key:record['values'].get(key,'') for key in scoped})
                    except Exception:
                        notices.append('Section insurance could not be verified; mapped claim/adjuster fields are blank.')
                for form in forms:
                    if form['id'].startswith('custom_'):
                        mapping=form_builder.get(form['id'])['fields']
                        for field,mapped in zip(form['fields'],mapping):
                            field['value']=str(custom_values.get(mapped['source']) or '') if mapped['source']!='manual' else ''
                notices.append('Mapped forms: blank fields need review. No signatures or signing dates are filled.')
            return {'ok': True, 'forms': forms, 'notice': ' '.join(notices)}
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
