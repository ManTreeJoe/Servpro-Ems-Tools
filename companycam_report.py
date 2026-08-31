"""Generate a compact, branded photo-report PDF from CompanyCam photos.

CompanyCam remains the photo system of record.  This module only reads the
chosen project, builds a PDF, and files that PDF in the job's existing DOCS
folder.  It deliberately contains no Trello or UI code.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import tempfile
from html import escape


def _epoch(value: str, *, end: bool = False):
    value = str(value or "").strip()
    if not value:
        return None
    parsed = dt.datetime.strptime(value, "%Y-%m-%d")
    if end:
        parsed += dt.timedelta(days=1, seconds=-1)
    return int(parsed.timestamp())


def _description(raw: dict) -> str:
    value = raw.get("description") or ""
    if isinstance(value, dict):
        value = value.get("plain_text_content") or value.get("text") or ""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _preview_uri(raw: dict) -> str:
    """Prefer a lightweight CompanyCam rendition for the contact sheet."""
    by_type = {}
    for item in raw.get("uris") or []:
        if isinstance(item, dict):
            by_type[str(item.get("type") or "").casefold()] = item.get("uri") or item.get("url") or ""
    return (by_type.get("thumbnail") or by_type.get("web") or
            by_type.get("original") or "")


def plan(project_id: str, *, start_date: str = "", end_date: str = "",
         tag: str = "", offset: int = 0, limit: int = 120) -> dict:
    import companycam_api as cc
    try:
        after, before = _epoch(start_date), _epoch(end_date, end=True)
    except ValueError:
        return {"ok": False, "error": "Dates must use YYYY-MM-DD."}
    try:
        photos = cc.list_project_photos(project_id)
    except Exception as ex:
        return {"ok": False, "error": f"Could not read CompanyCam photos: {ex}"}
    rows = []
    wanted = str(tag or "").strip().casefold()
    for raw in photos:
        try:
            captured = int(raw.get("captured_at") or raw.get("created_at") or 0)
        except (TypeError, ValueError):
            captured = 0
        if after is not None and captured < after:
            continue
        if before is not None and captured > before:
            continue
        tags = cc.photo_tags(raw.get("id"), raw.get("updated_at") or "") if wanted else []
        if wanted and not any(wanted in str(item).casefold() for item in tags):
            continue
        url = cc._original_uri(raw)
        if not url:
            continue
        stamp = dt.datetime.fromtimestamp(captured) if captured else None
        rows.append({
            "id": str(raw.get("id") or ""), "url": url,
            "preview_url": _preview_uri(raw) or url,
            "date": stamp.strftime("%m/%d/%Y %I:%M %p") if stamp else "",
            "captured_at": captured, "creator": raw.get("creator_name") or "",
            "description": _description(raw), "tags": tags,
        })
    start = max(0, int(offset or 0))
    page_size = max(1, min(int(limit or 120), 5000))
    page = rows[start:start + page_size]
    return {"ok": True, "project_id": str(project_id), "photos": page,
            "count": len(page), "total": len(rows), "offset": start,
            "has_more": start + len(page) < len(rows)}


def generate(project_id: str, client: str, docs_folder: str, report_type: str,
             photo_ids: list[str], *, start_date: str = "", end_date: str = "",
             tag: str = "") -> dict:
    chosen = {str(value) for value in (photo_ids or []) if str(value)}
    result = plan(project_id, start_date=start_date, end_date=end_date,
                  tag=tag, offset=0, limit=5000)
    if not result.get("ok"):
        return result
    photos = [row for row in result["photos"] if not chosen or row["id"] in chosen]
    if not photos:
        return {"ok": False, "error": "No CompanyCam photos match this report."}
    if not docs_folder or not os.path.isdir(docs_folder):
        return {"ok": False, "error": "This job does not have an accessible DOCS folder."}

    safe_client = re.sub(r"[^A-Za-z0-9 _.-]+", "", client).strip() or "Job"
    kind = str(report_type or "Photo Report").strip() or "Photo Report"
    filename = f"{safe_client} - {kind} - {dt.date.today():%Y-%m-%d}.pdf"
    output = os.path.join(docs_folder, filename)

    from PIL import Image as PILImage, ImageOps
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    import companycam_api as cc

    styles = getSampleStyleSheet()
    title = ParagraphStyle("ReportTitle", parent=styles["Title"], fontName="Helvetica-Bold",
                           fontSize=18, leading=21, textColor=colors.HexColor("#176b3a"))
    meta = ParagraphStyle("ReportMeta", parent=styles["Normal"], fontSize=8.5,
                          leading=11, textColor=colors.HexColor("#555555"))
    caption = ParagraphStyle("Caption", parent=styles["Normal"], fontSize=9,
                             leading=12, textColor=colors.HexColor("#222222"))
    doc = SimpleDocTemplate(output, pagesize=letter, leftMargin=.55*inch,
                            rightMargin=.55*inch, topMargin=.5*inch, bottomMargin=.5*inch)
    story = [Paragraph(escape(kind), title),
             Paragraph(f"{escape(client)} · Generated {dt.datetime.now():%B %d, %Y at %I:%M %p} · {len(photos)} photos", meta),
             Spacer(1, .18*inch)]
    with tempfile.TemporaryDirectory(prefix="linguar-photo-report-") as temp_dir:
        for index, row in enumerate(photos, 1):
            raw_path = os.path.join(temp_dir, f"{index:03d}.img")
            jpeg_path = os.path.join(temp_dir, f"{index:03d}.jpg")
            try:
                cc._download(row["url"], raw_path)
                with PILImage.open(raw_path) as source:
                    image = ImageOps.exif_transpose(source).convert("RGB")
                    image.thumbnail((1600, 1200), PILImage.Resampling.LANCZOS)
                    image.save(jpeg_path, "JPEG", quality=86, optimize=True)
                pic = Image(jpeg_path, width=6.8*inch, height=4.55*inch, kind="proportional")
            except Exception as ex:
                story.append(Paragraph(f"Photo {index} could not be downloaded: {escape(str(ex))}", caption))
                continue
            detail = " · ".join(filter(None, [row.get("date"), row.get("creator"), ", ".join(row.get("tags") or [])]))
            text = row.get("description") or "Jobsite photo"
            block = Table([[pic], [Paragraph(escape(text), caption)], [Paragraph(escape(detail), meta)]],
                          colWidths=[6.9*inch])
            block.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), .5, colors.HexColor("#c8d2cc")),
                                       ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f4f7f5")),
                                       ("LEFTPADDING", (0, 0), (-1, -1), 5),
                                       ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                                       ("TOPPADDING", (0, 0), (-1, -1), 5),
                                       ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
            story.append(block)
            if index < len(photos):
                story.append(PageBreak())
        doc.build(story)
    return {"ok": True, "path": output, "filename": filename,
            "photos": len(photos), "docs_folder": docs_folder}
