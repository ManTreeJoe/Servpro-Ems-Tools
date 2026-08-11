"""Cheat Sheet — Pywebview spike (markdown viewer)."""
from __future__ import annotations
import os, sys
import webview

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path: sys.path.insert(0, _HERE)

import cheat_sheet_logic as cs   # pure parser; NOT the Tk panel
import paths

ASSETS_DIR = os.path.join(_HERE, "cheat_sheet_web_assets")
INDEX_HTML = os.path.join(ASSETS_DIR, "index.html")


class Api:
    def __init__(self): self._window = None
    def attach(self, w): self._window = w

    def sections(self):
        try:
            md_path = paths.resource("EMS_Admin_Cheat_Sheet.md")
            return cs.parse_markdown(md_path)
        except Exception:
            return []

    def export_pdf(self) -> dict:
        """Render the cheat sheet to a printable PDF. Uses reportlab —
        same library audit_export uses — for consistency."""
        try:
            md_path = paths.resource("EMS_Admin_Cheat_Sheet.md")
            sections = cs.parse_markdown(md_path) or []
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        if not sections:
            return {"ok": False, "error": "Cheat sheet is empty"}
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import inch
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
            from reportlab.lib.enums import TA_LEFT
        except Exception as ex:
            return {"ok": False, "error": f"reportlab unavailable: {ex}"}
        try:
            import datetime as _dt
            out_dir = os.path.join(paths.DATA_DIR, "cheat_sheet_exports")
            os.makedirs(out_dir, exist_ok=True)
            today = _dt.date.today().strftime("%Y-%m-%d")
            out_path = os.path.join(out_dir, f"cheat_sheet_{today}.pdf")
            doc = SimpleDocTemplate(out_path, pagesize=letter,
                                     leftMargin=0.6 * inch,
                                     rightMargin=0.6 * inch,
                                     topMargin=0.6 * inch,
                                     bottomMargin=0.6 * inch)
            styles = getSampleStyleSheet()
            h1 = ParagraphStyle("H1", parent=styles["Heading1"],
                                 fontSize=14, spaceAfter=6,
                                 textColor=colors.HexColor("#2E8B57"))
            body = ParagraphStyle("B", parent=styles["Normal"],
                                   fontSize=10, spaceAfter=4, leading=14)
            story = [Paragraph("EMS Admin Cheat Sheet", h1)]
            for sec in sections:
                story.append(Paragraph(sec.get("title") or "—", h1))
                content = sec.get("content") or ""
                for ln in content.split("\n"):
                    if ln.strip():
                        story.append(Paragraph(ln.replace("&", "&amp;"), body))
                story.append(Spacer(1, 0.1 * inch))
            doc.build(story)
            try: os.startfile(out_path)
            except Exception: pass
            return {"ok": True, "path": out_path,
                    "sections": len(sections)}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}


def main(argv=None):
    api = Api()
    win = webview.create_window(
        title="EMS Cheat Sheet — Linguar Hub (web)",
        url=INDEX_HTML, js_api=api,
        width=1100, height=820, min_size=(720, 500))
    api.attach(win)
    webview.start(debug=False)


if __name__ == "__main__":
    main()
