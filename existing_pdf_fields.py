"""Inspect and map existing AcroForm text fields without flattening originals."""
import hashlib
import re


def field_owner(widget):
    owner = widget
    seen = set()
    while '/T' not in owner and owner.get('/Parent'):
        ref = owner['/Parent']
        if id(ref) in seen:
            raise ValueError('The PDF has a circular field tree.')
        seen.add(id(ref)); owner = ref.get_object()
    return owner


def inspect_fields(reader):
    root = reader.trailer['/Root']
    form = root.get('/AcroForm')
    if form and form.get_object().get('/XFA'):
        raise ValueError('XFA forms are not supported yet. Use a standard fillable PDF.')
    fields = reader.get_fields() or {}
    for field in fields.values():
        if field.get('/FT') == '/Sig' and field.get('/V'):
            raise ValueError('This PDF is digitally signed. Upload the unsigned original.')
        if field.get('/AA') or field.get('/A'):
            raise ValueError('This PDF contains field actions that are not supported.')
    found = {}
    for page_index, page in enumerate(reader.pages):
        refs = page.get('/Annots')
        for ref in refs.get_object() if refs else []:
            widget = ref.get_object()
            if widget.get('/Subtype') != '/Widget' or widget.get('/A') or widget.get('/AA'):
                raise ValueError('This PDF contains annotations or actions that are not supported.')
            owner = field_owner(widget)
            name = str(owner.get('/T', ''))
            canonical = fields.get(name)
            if canonical is None or canonical.indirect_reference != owner.indirect_reference:
                raise ValueError('This PDF has ambiguous or unregistered fields; its field tree needs repair.')
            if owner.get('/FT') != '/Tx' or int(owner.get('/Ff', 0)) & 1:
                continue
            # Signing-related text fields must not receive automatic job values.
            if re.search(r'sign|initial|today|consent', name, re.I):
                continue
            rect = [float(x) for x in widget['/Rect']]
            x, y, right, top = rect
            if name not in found:
                found[name] = dict(id='f_'+hashlib.sha256(name.encode()).hexdigest()[:24],
                    source='manual', page=page_index, x=x, y=float(page.mediabox.height)-top,
                    width=right-x, height=top-y, font_size=10,
                    multiline=bool(int(owner.get('/Ff',0)) & 4096), existing_name=name)
    return list(found.values())


def validate_existing(fields, reader):
    originals = {f['existing_name']: f for f in inspect_fields(reader)}
    used = set()
    for f in fields:
        name = f.get('existing_name')
        if name is None:
            continue
        original = originals.get(name)
        if not original or name in used:
            raise ValueError('Choose a supported existing text field only once.')
        used.add(name)
        for key in ('id','page','x','y','width','height','font_size','multiline'):
            if f.get(key) != original[key]:
                raise ValueError('Existing PDF field positions cannot be changed. Change its information source instead.')
