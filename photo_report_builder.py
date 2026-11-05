"""Four-up reports: temporary preview first, explicit collision-safe filing second."""
import datetime as dt
import math
from io import BytesIO
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import time
import uuid
from html import escape

_drafts = {}
_lock = threading.RLock()
TTL = 3600


def _text(value, limit=200):
    value = str(value or '').strip()
    if len(value) > limit:
        raise ValueError(f'Text must be at most {limit} characters.')
    # Built-in PDF fonts support western-language text, not emoji.
    try:
        value.encode('cp1252')
    except UnicodeEncodeError:
        raise ValueError('Remove unsupported symbols or emoji from report text.') from None
    return value


def render(output, photos, *, title, client, address='', office='', phone='',
           report_date='', cover_id='', notes='', logo=''):
    """Pure layout: all photos must already exist; never silently omit one."""
    from PIL import Image, ImageOps
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.lib.utils import ImageReader
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph
    if not photos:
        raise ValueError('Select at least one photo.')
    cover = next((p for p in photos if p['id'] == cover_id), photos[0])
    if cover_id and cover['id'] != cover_id:
        raise ValueError('The cover must be one of the selected photos.')
    title, client, address = _text(title, 120), _text(client), _text(address)
    office, phone, report_date = _text(office), _text(phone, 60), _text(report_date, 60)
    notes = _text(notes, 2500)
    pages = 1 + math.ceil(len(photos) / 4) + bool(notes)
    canvas = Canvas(str(output), pagesize=(612, 792), pageCompression=1)
    canvas.setTitle(title)
    canvas.setAuthor(office or 'OneLoss')

    def text(value, x, top, width, size=11, bold=False, center=False, max_height=55):
        style = ParagraphStyle('report', fontName='Helvetica-Bold' if bold else 'Helvetica',
                               fontSize=size, leading=size*1.35, textColor='#172a3b',
                               alignment=1 if center else 0)
        p = Paragraph(escape(value).replace('\n', '<br/>'), style)
        _, height = p.wrap(width, max_height)
        if height > max_height:
            raise ValueError('Report text is too long for the layout. Shorten the title, address or caption.')
        p.drawOn(canvas, x, 792-top-height)
        return height

    def picture(row, x, top, width, height):
        with Image.open(row['path']) as original:
            pic = ImageOps.exif_transpose(original).convert('RGB')
            pic.thumbnail((1400, 1400), Image.Resampling.LANCZOS)
            encoded = BytesIO()
            pic.save(encoded, format='JPEG', quality=83, optimize=True)
            encoded.seek(0)
            # Fit, never crop away damage/equipment visible in the source.
            canvas.drawImage(ImageReader(encoded), x, 792-top-height, width, height,
                             preserveAspectRatio=True, anchor='c', mask='auto')

    def header(number):
        if logo and Path(logo).is_file():
            canvas.drawImage(logo, 42, 742, 64, 36, preserveAspectRatio=True, mask='auto')
        else:
            text(office or 'Photo report', 42, 26, 410, 9, max_height=28)
        canvas.setFont('Helvetica', 9)
        canvas.drawRightString(570, 765, f'{number} of {pages}')

    header(1)
    picture(cover, 138, 130, 336, 252)
    text(title, 72, 408, 468, 18, True, True, 55)
    text(client, 72, 470, 468, 11, center=True, max_height=36)
    text(address, 72, 511, 468, 11, center=True, max_height=36)
    text(report_date, 72, 553, 468, 10, center=True)
    canvas.setStrokeColorRGB(.8, .83, .85)
    canvas.line(138, 205, 474, 205)
    if logo and Path(logo).is_file():
        canvas.drawImage(logo, 268, 140, 76, 43, preserveAspectRatio=True, mask='auto')
    text(office, 72, 660, 468, 11, True, True, 32)
    text(phone, 72, 698, 468, 10, center=True)
    canvas.showPage()
    for offset in range(0, len(photos), 4):
        header(2 + offset // 4)
        for slot, row in enumerate(photos[offset:offset+4]):
            x, top = 54 + (slot % 2)*258, 72 + (slot // 2)*335
            picture(row, x, top, 246, 246)
            canvas.setFillColorRGB(.08, .1, .1)
            canvas.roundRect(x+5, 792-top-241, 28, 21, 3, fill=1, stroke=0)
            canvas.setFillColorRGB(1, 1, 1)
            canvas.setFont('Helvetica-Bold', 9)
            canvas.drawCentredString(x+19, 792-top-234, str(offset+slot+1))
            text(_text(row.get('date'), 80), x, top+253, 246, 8, max_height=24)
            text(_text(row.get('description'), 400), x, top+279, 246, 9, max_height=48)
        canvas.showPage()
    if notes:
        header(pages)
        text('Final notes', 54, 80, 504, 18, True)
        text(notes, 54, 120, 504, 11, max_height=600)
        canvas.showPage()
    canvas.save()
    return pages


def _expire():
    for token, draft in list(_drafts.items()):
        if time.monotonic() - draft['created'] > TTL:
            shutil.rmtree(draft['temp'], ignore_errors=True)
            del _drafts[token]


def preview(context, photo_ids, options, *, scope):
    import companycam_api as cc
    import companycam_report
    import paths
    options = dict(options or {})
    ids = list(dict.fromkeys(str(p) for p in (photo_ids or []) if str(p)))
    if not ids or len(ids) > 1000:
        raise ValueError('Select between 1 and 1,000 photos for one report.')
    if str(options.get('project_id') or '') != str(context['project_id']):
        raise ValueError('The linked project changed. Find photos again before building.')
    identity = scope()
    result = companycam_report.plan(context['project_id'], limit=5000)
    if not result.get('ok'):
        raise ValueError(result.get('error') or 'Could not load photos.')
    by_id = {p['id']: p for p in result['photos']}
    if any(i not in by_id for i in ids):
        raise ValueError('A selected photo is no longer available. Reload the picker.')
    title = _text(options.get('title') or 'Photo Report', 120)
    cover = str(options.get('cover_id') or ids[0])
    if cover not in ids:
        raise ValueError('Select a cover from the included photos.')
    captions = options.get('captions') or {}
    temp = tempfile.mkdtemp(prefix='oneloss-report-preview-')
    try:
        photos = []
        for index, photo_id in enumerate(ids):
            if scope() != identity:
                raise ValueError('Account or office changed. Reopen the report.')
            row = dict(by_id[photo_id])
            row['path'] = str(Path(temp) / f'{index}.img')
            cc._download(row['url'], row['path'])
            row['description'] = _text(captions.get(photo_id, row.get('description', '')), 400)
            photos.append(row)
        pdf = Path(temp) / 'preview.pdf'
        pages = render(pdf, photos, title=title, client=context['client'],
                       address=options.get('address', context.get('address', '')),
                       office=context.get('office', ''), phone=context.get('phone', ''),
                       report_date=options.get('date') or dt.date.today().strftime('%m/%d/%Y'),
                       cover_id=cover, notes=options.get('notes', ''),
                       logo=paths.resource('web_shared/report_brand.jpg'))
        if scope() != identity:
            raise ValueError('Account or office changed. Reopen the report.')
        filename = re.sub(r'[^\w .()-]', '_', title).strip(' .')[:100] or 'Photo Report'
        if re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])', filename):
            filename = 'Report ' + filename
        filename = f'{filename} - {dt.date.today():%m.%d.%Y}.pdf'
        token = uuid.uuid4().hex
        with _lock:
            _expire()
            if len(_drafts) >= 10:
                raise ValueError('Too many open report previews. Finish an existing report first.')
            _drafts[token] = dict(temp=temp, path=str(pdf), created=time.monotonic(),
                                  scope=identity, project=str(context['project_id']),
                                  client=context['client'], docs=os.path.realpath(context['docs_folder']),
                                  filename=filename, saved='')
        return dict(ok=True, token=token, path=str(pdf), filename=filename, photos=len(photos), pages=pages)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise


def save(token, context, *, scope):
    with _lock:
        _expire()
        draft = _drafts.get(token)
        if not draft:
            raise ValueError('Preview expired. Build it again before saving.')
        if (draft['scope'] != scope() or draft['client'] != context['client'] or
                draft['project'] != str(context['project_id']) or
                draft['docs'] != os.path.realpath(context['docs_folder'])):
            raise ValueError('Job, project or office changed. Build a new preview.')
        if draft['saved']:
            return dict(ok=True, path=draft['saved'], filename=Path(draft['saved']).name)
        folder = Path(draft['docs'])
        if not folder.is_dir():
            raise ValueError('The DOCS folder is unavailable. Nothing saved.')
        # Publish a complete PDF without ever overwriting an existing report.
        fd, staging = tempfile.mkstemp(prefix='.report-', suffix='.tmp', dir=folder)
        os.close(fd)
        try:
            shutil.copyfile(draft['path'], staging)
            if draft['scope'] != scope():
                raise ValueError('Account or office changed. Nothing saved.')
            for n in range(1, 10000):
                name = Path(draft['filename'])
                target = folder / (name.name if n == 1 else f'{name.stem} ({n}){name.suffix}')
                try:
                    if os.name == 'nt':
                        os.rename(staging, target)
                    else:
                        os.link(staging, target)
                    draft['saved'] = str(target)
                    return dict(ok=True, path=str(target), filename=target.name)
                except FileExistsError:
                    continue
            raise ValueError('Could not choose a unique report filename.')
        finally:
            if os.path.exists(staging):
                os.unlink(staging)
