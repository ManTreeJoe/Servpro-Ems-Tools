"""Local, versioned blank-PDF templates with factual text-field mappings."""
import io
import json
import math
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from pypdf import PdfReader, PdfWriter
import paths

DB_PATH = Path(paths.DATA_DIR) / 'form_builder.sqlite3'
SOURCES = {
    'customer_name':'Customer name', 'address':'Property address', 'phone':'Customer phone',
    'email':'Customer email', 'date_of_loss':'Date of loss', 'claim_number':'Claim number',
    'carrier':'Insurance carrier', 'adjuster_name':'Adjuster name', 'adjuster_email':'Adjuster email',
    'adjuster_phone':'Adjuster phone', 'poc_name':'Point of contact name', 'poc_phone':'Point of contact phone',
    'poc_email':'Point of contact email', 'franchise_name':'Franchise name',
    'office_phone':'Office phone', 'manual':'Manual entry (blank until reviewed)',
}


@contextmanager
def connection():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS templates (id TEXT PRIMARY KEY, title TEXT NOT NULL, pdf BLOB NOT NULL, fields TEXT NOT NULL, revision INTEGER NOT NULL)')
    try:
        with db:
            yield db
    finally:
        db.close()


def inspect(data):
    if len(data) > 20 * 1024 * 1024:
        raise ValueError('Use a PDF smaller than 20 MB.')
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted or not 1 <= len(reader.pages) <= 20:
        raise ValueError('Use an unencrypted PDF with 1–20 pages.')
    root = reader.trailer['/Root']
    if root.get('/OpenAction') or root.get('/AA') or root.get('/Names'):
        raise ValueError('This PDF contains document actions or named content that is not supported yet.')
    from existing_pdf_fields import inspect_fields
    inspect_fields(reader)
    sizes = []
    for p in reader.pages:
        if p.get('/AA') or p.rotation or list(p.cropbox) != list(p.mediabox) or tuple(p.mediabox.lower_left) != (0, 0):
            raise ValueError('Use a plain, unrotated PDF without annotations or cropped pages.')
        sizes.append([float(p.mediabox.width), float(p.mediabox.height)])
    return sizes


def get(template_id):
    template_id, sep, expected = str(template_id).partition('@')
    with connection() as db:
        row = db.execute('SELECT * FROM templates WHERE id=?', (template_id,)).fetchone()
    if not row:
        raise ValueError('Template not found on this computer.')
    result = dict(row)
    if sep and str(result['revision']) != expected:
        raise ValueError('This field map changed. Reopen Forms to refresh the job values before downloading.')
    result['fields'] = json.loads(result['fields'])
    return result


def listing():
    with connection() as db:
        return [dict(r) for r in db.execute('SELECT id,title,revision FROM templates ORDER BY title')]


def upload(data, title):
    inspect(data)
    title = str(title).strip()
    if not title or len(title) > 120:
        raise ValueError('Give the template a name of 1–120 characters.')
    key = 'custom_' + uuid.uuid4().hex
    from existing_pdf_fields import inspect_fields
    fields = inspect_fields(PdfReader(io.BytesIO(data)))
    with connection() as db:
        db.execute('INSERT INTO templates VALUES (?,?,?,?,1)', (key, title, data, json.dumps(fields)))
    return key


def validate(fields, sizes):
    import re
    if not isinstance(fields, list) or len(fields) > 100:
        raise ValueError('Use at most 100 mapped fields.')
    seen = set()
    for f in fields:
        if not isinstance(f, dict) or not re.fullmatch(r'f_[a-z0-9]+', str(f.get('id',''))) or f['id'] in seen:
            raise ValueError('Each field needs a unique identifier.')
        seen.add(f['id'])
        if f.get('source') not in SOURCES or type(f.get('page')) is not int or not 0 <= f['page'] < len(sizes):
            raise ValueError('Choose a supported information source and page.')
        for key in ('x','y','width','height','font_size'):
            if not isinstance(f.get(key), (int,float)) or not math.isfinite(f[key]):
                raise ValueError('Field position and size must be valid numbers.')
        w,h = sizes[f['page']]
        if not (0 <= f['x'] and 0 <= f['y'] and f['width'] >= 24 and f['height'] >= 14 and
                f['x']+f['width'] <= w and f['y']+f['height'] <= h and 6 <= f['font_size'] <= 24):
            raise ValueError('Keep fields inside the page; text size must be 6–24 points.')
        if type(f.get('multiline',False)) is not bool:
            raise ValueError('Invalid multiline setting.')
    return fields


def save(template_id, fields, revision):
    row = get(template_id)
    validate(fields, inspect(row['pdf']))
    from existing_pdf_fields import validate_existing
    validate_existing(fields, PdfReader(io.BytesIO(row['pdf'])))
    with connection() as db:
        count = db.execute('UPDATE templates SET fields=?,revision=revision+1 WHERE id=? AND revision=?',
                           (json.dumps(fields), template_id, revision)).rowcount
    if count != 1:
        raise ValueError('This template changed. Close and reopen the builder before saving.')
    return revision+1


def render(row, values):
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.lib.colors import black
    from reportlab.lib.utils import simpleSplit
    from reportlab.pdfbase.pdfmetrics import stringWidth
    sizes = inspect(row['pdf'])
    fields = validate(row['fields'], sizes)
    from existing_pdf_fields import validate_existing
    original_reader = PdfReader(io.BytesIO(row['pdf']))
    validate_existing(fields, original_reader)
    if not isinstance(values, dict) or set(values)-{f['id'] for f in fields}:
        raise ValueError('Unknown mapped field.')
    if not fields:
        return row['pdf']
    if original_reader.get_fields():
        return render_existing(row, values, original_reader)
    output = io.BytesIO()
    canvas = Canvas(output)
    for page,(w,h) in enumerate(sizes):
        canvas.setPageSize((w,h))
        for f in fields:
            if f['page'] != page: continue
            value = values.get(f['id'], '')
            if not isinstance(value,str) or len(value)>2000:
                raise ValueError('Use text of at most 2,000 characters per field.')
            try: value.encode('cp1252')
            except UnicodeEncodeError: raise ValueError('This font cannot display a character in the entered text. Revise before downloading.')
            lines = simpleSplit(value, 'Helvetica', f['font_size'], f['width']-6)
            widest_word=max((stringWidth(word,'Helvetica',f['font_size']) for word in value.split()),default=0)
            if widest_word>f['width']-6 or (not f.get('multiline') and (len(lines)>1 or '\n' in value)) or len(lines)*(f['font_size']*1.2)>f['height']-4:
                raise ValueError(f"Text does not fit {SOURCES[f['source']]}. Enlarge its box or shorten the draft value.")
            canvas.acroForm.textfield(name=f['id'], x=f['x'], y=h-f['y']-f['height'],
                width=f['width'], height=f['height'], fontSize=f['font_size'], value=value,
                borderWidth=0, fillColor=None, textColor=black, forceBorder=False,
                fieldFlags='multiline' if f.get('multiline') else '')
        canvas.showPage()
    canvas.save()
    writer = PdfWriter()
    writer.clone_document_from_reader(PdfReader(io.BytesIO(output.getvalue())))
    original = PdfReader(io.BytesIO(row['pdf']))
    for i,page in enumerate(writer.pages):
        page.merge_page(original.pages[i], over=False)
    out = io.BytesIO(); writer.write(out)
    check = PdfReader(io.BytesIO(out.getvalue())).get_fields() or {}
    for f in fields:
        if str(check.get(f['id'],{}).get('/V','')) != values.get(f['id'],''):
            raise ValueError('PDF field verification failed.')
    return out.getvalue()


def render_existing(row, values, reader):
    """Retain all original widgets; update only explicitly supplied text values."""
    from pypdf.generic import NameObject, ArrayObject
    from existing_pdf_fields import field_owner
    writer = PdfWriter(); writer.clone_document_from_reader(reader)
    updates = {}
    for f in row['fields']:
        if f.get('existing_name') and f['id'] in values and values[f['id']] != '':
            value = values[f['id']]
            if not isinstance(value, str) or len(value) > 2000:
                raise ValueError('Use text of at most 2,000 characters per field.')
            from reportlab.lib.utils import simpleSplit
            from reportlab.pdfbase.pdfmetrics import stringWidth
            lines = simpleSplit(value, 'Helvetica', f['font_size'], f['width']-6)
            if (max((stringWidth(word,'Helvetica',f['font_size']) for word in value.split()),default=0)>f['width']-6 or
                (not f['multiline'] and (len(lines)>1 or '\n' in value)) or
                len(lines)*f['font_size']*1.2 > f['height']-4):
                raise ValueError('Text does not fit existing field '+f['existing_name']+'. Shorten the value before downloading.')
            updates[f['existing_name']] = value
    if updates:
        writer.update_page_form_field_values(None, updates, auto_regenerate=False)
    added = [f for f in row['fields'] if not f.get('existing_name')]
    if added:
        blank = PdfWriter()
        for page in reader.pages:
            blank.add_blank_page(width=float(page.mediabox.width), height=float(page.mediabox.height))
        raw = io.BytesIO(); blank.write(raw)
        overlay = PdfReader(io.BytesIO(render({'pdf':raw.getvalue(),'fields':added},
            {f['id']:values[f['id']] for f in added if f['id'] in values})))
        names = set((reader.get_fields() or {}).keys())
        for f in added:
            if f['id'] in names: raise ValueError('New field identifier conflicts with an original field.')
        for i, page in enumerate(overlay.pages):
            widgets = list(page.get('/Annots', []))
            page.pop('/Annots', None)
            writer.pages[i].merge_page(page)
            for ref in widgets:
                cloned = ref.clone(writer)
                cloned.get_object()[NameObject('/P')] = writer.pages[i].indirect_reference
                writer.pages[i].setdefault(NameObject('/Annots'), ArrayObject()).append(cloned)
                writer.root_object['/AcroForm']['/Fields'].append(cloned)
    out = io.BytesIO(); writer.write(out)
    check = PdfReader(io.BytesIO(out.getvalue())); actual = check.get_fields() or {}
    for f in added:
        if actual.get(f['id'],{}).get('/V','') != values.get(f['id'],''):
            raise ValueError('Added PDF field verification failed.')
    for name, old in (reader.get_fields() or {}).items():
        expected = updates.get(name, old.get('/V'))
        if name not in actual or actual[name].get('/V') != expected:
            raise ValueError('Original PDF field verification failed.')
    for page in check.pages:
        refs = page.get('/Annots')
        for ref in refs.get_object() if refs else []:
            widget = ref.get_object(); owner = field_owner(widget); name = str(owner.get('/T',''))
            if name in updates and (owner.get('/V') != updates[name] or not widget.get('/AP',{}).get('/N')):
                raise ValueError('PDF field appearance verification failed.')
    return out.getvalue()


class FormBuilderApi:
    def form_builder_copy_builtin(self, form_id):
        try:
            import job_forms
            import hashlib
            if form_id not in ('selfpay_contract','selfpay_cancel'):
                raise ValueError('Only reviewed static blank originals can be mapped here.')
            data=(job_forms.TEMPLATES/(form_id+'.pdf')).read_bytes()
            inspect(data)
            key='custom_'+uuid.uuid5(uuid.NAMESPACE_URL,form_id+hashlib.sha256(data).hexdigest()).hex
            with connection() as db:
                db.execute('INSERT OR IGNORE INTO templates VALUES (?,?,?,?,1)',
                           (key,job_forms.FORMS[form_id]+' - mapped copy',data,'[]'))
            return {'ok':True,'id':key}
        except Exception as ex:return {'ok':False,'error':str(ex)}

    def form_builder_preview(self, template_id, fields):
        try:
            import job_forms
            row=get(template_id); row['fields']=fields
            values={f['id']:'Sample' for f in fields}
            return {'ok':True,'pages':job_forms.preview_bytes(render(row,values))}
        except Exception as ex: return {'ok':False,'error':str(ex)}

    def form_builder_upload(self, confirmed_blank=False):
        try:
            if confirmed_blank is not True: raise ValueError('Confirm the source is blank and unsigned.')
            import webview
            chosen = self._window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False, file_types=('PDF (*.pdf)',))
            if not chosen: return {'ok':True,'cancelled':True}
            path = Path(chosen[0] if isinstance(chosen,(tuple,list)) else chosen)
            if path.stat().st_size>20*1024*1024: raise ValueError('Use a PDF smaller than 20 MB.')
            key = upload(path.read_bytes(), path.stem)
            return {'ok':True,'id':key}
        except Exception as ex: return {'ok':False,'error':str(ex)}

    def form_builder_load(self, template_id):
        try:
            import job_forms
            row = get(template_id)
            return {'ok':True,'id':row['id'],'title':row['title'],'revision':row['revision'],
                    'fields':row['fields'],'sizes':inspect(row['pdf']), 'sources':SOURCES,
                    'pages':job_forms.preview_bytes(row['pdf'])}
        except Exception as ex: return {'ok':False,'error':str(ex)}

    def form_builder_save(self, template_id, fields, revision):
        try: return {'ok':True,'revision':save(template_id,fields,revision)}
        except Exception as ex: return {'ok':False,'error':str(ex)}
