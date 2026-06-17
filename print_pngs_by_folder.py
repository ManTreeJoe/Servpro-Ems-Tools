"""Combine every PNG across a tree of subfolders into a single
print-ready PDF, with a blank page inserted between folders.

Usage:
    python print_pngs_by_folder.py <root>
    python print_pngs_by_folder.py <root1> <root2> ...
    python print_pngs_by_folder.py <root> --out <output.pdf>
    python print_pngs_by_folder.py <root> --print     # auto-send to default printer
    python print_pngs_by_folder.py <root> --open      # open in default PDF viewer

Multiple roots: each positional path is either a parent folder
(subfolders are walked) OR a direct PNG-bearing folder (becomes a
single batch). The two modes auto-detect from each path's contents,
so you can mix-and-match in one command, e.g.:

    python print_pngs_by_folder.py "X:\\parent_with_subfolders" \\
                                    "X:\\standalone_png_folder"

Page layout: Letter (8.5 x 11), portrait. Each PNG scales to fit the
printable area while preserving aspect ratio + centered. Blank pages
between folders are pure-white pages so the print operator can flip
to find the next folder's batch visually.

Default output: `<first root>\\_print.pdf` (or `--out` to override).
"""
from __future__ import annotations
import argparse
import os
import sys

from PIL import Image
try:
    from reportlab.lib.pagesizes import letter, landscape, portrait
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import inch
except ImportError:
    print("reportlab is required: pip install reportlab", file=sys.stderr)
    sys.exit(1)


# Default page = portrait letter (8.5 x 11). landscape() is exposed
# via --landscape; nothing else flips orientation. Tuple form is
# `(width_pts, height_pts)` — portrait has height > width.
PORTRAIT_SIZE  = portrait(letter)     # (612, 792) — w<h
LANDSCAPE_SIZE = landscape(letter)    # (792, 612) — w>h
MARGIN_PT      = 0.35 * inch          # tight margin — maximize image area
PNG_EXTS       = {".png", ".PNG"}


def _subfolders(root: str) -> list[str]:
    """Direct child subfolders of `root`, sorted by name. Skips
    hidden / underscore-prefixed names so a `_print.pdf` won't loop
    into itself on re-runs."""
    out = []
    try:
        for name in sorted(os.listdir(root)):
            p = os.path.join(root, name)
            if not os.path.isdir(p):
                continue
            if name.startswith(".") or name.startswith("_"):
                continue
            out.append(p)
    except OSError as ex:
        print(f"Can't read {root!r}: {ex}", file=sys.stderr)
    return out


def _pngs_in(folder: str) -> list[str]:
    """PNG files in `folder`, sorted by name (case-insensitive)."""
    try:
        files = [os.path.join(folder, f)
                 for f in os.listdir(folder)
                 if os.path.splitext(f)[1] in PNG_EXTS
                 and os.path.isfile(os.path.join(folder, f))]
    except OSError:
        return []
    files.sort(key=lambda p: os.path.basename(p).lower())
    return files


def _draw_title_page(c: canvas.Canvas, title: str, page_size,
                       subtitle: str = "") -> None:
    """Render a title page: folder name centered in big bold text,
    optional subtitle line below. Replaces the previous blank
    separator so the print operator sees the section heading instead
    of an unmarked blank page."""
    page_w, page_h = page_size
    # Slightly smaller font for very long titles so they don't wrap
    # off the page. Cap at 60pt for short names; shrink to 32pt for
    # 30+ char names. Linear interp.
    n = len(title or "")
    title_size = max(32, 60 - max(0, n - 18) * 1)
    title_size = min(60, title_size)
    c.setFont("Helvetica-Bold", title_size)
    # Center vertically slightly above middle so the title visually
    # feels balanced (humans read titles as centered when the optical
    # center is a touch above geometric center).
    tx = page_w / 2
    ty = page_h * 0.55
    c.drawCentredString(tx, ty, title or "(untitled section)")
    if subtitle:
        c.setFont("Helvetica", 14)
        c.setFillGray(0.4)
        c.drawCentredString(tx, ty - title_size - 18, subtitle)
        c.setFillGray(0)


def _draw_image(c: canvas.Canvas, img_path: str, page_size) -> None:
    """Draw a single PNG centered on the current page, scaled to fit
    within the page margins while preserving aspect ratio. Takes the
    page size explicitly so the same routine works for both portrait
    and landscape pages."""
    page_w, page_h = page_size
    try:
        im = Image.open(img_path)
        iw, ih = im.size
    except Exception as ex:
        c.setFont("Helvetica", 10)
        c.drawString(MARGIN_PT, page_h / 2,
                     f"[Could not load {os.path.basename(img_path)}: {ex}]")
        return
    available_w = page_w - 2 * MARGIN_PT
    available_h = page_h - 2 * MARGIN_PT
    scale = min(available_w / iw, available_h / ih)
    draw_w = iw * scale
    draw_h = ih * scale
    x = (page_w - draw_w) / 2
    y = (page_h - draw_h) / 2
    c.drawImage(img_path, x, y, width=draw_w, height=draw_h,
                preserveAspectRatio=True, mask="auto")


def _resolve_folders(roots: list[str]) -> list[str]:
    """Expand `roots` into the final ordered list of folders to
    render. Each root is either:
      • A parent folder whose direct subfolders contain PNGs → its
        subfolders get appended (sorted by name).
      • A folder that directly contains PNGs → appended as a single
        batch.

    Auto-detection: if the root has any PNGs directly inside it AND
    no subfolders with PNGs, treat as standalone. Otherwise walk
    subfolders. Mixed-mode (root has both direct PNGs AND PNG
    subfolders) defaults to walking subfolders, since that's the
    common case the caller meant.

    Roots that resolve to zero folders are silently skipped (with a
    one-line warning).
    """
    out = []
    for root in roots:
        root = os.path.abspath(root)
        if not os.path.isdir(root):
            print(f"  skipping (not a folder): {root!r}")
            continue
        subs = _subfolders(root)
        sub_pngs = sum(len(_pngs_in(s)) for s in subs)
        if sub_pngs > 0:
            out.extend(subs)
        elif _pngs_in(root):
            out.append(root)
        else:
            print(f"  skipping (no PNGs found): {root!r}")
    return out


def build_pdf(roots: list[str], output_path: str,
              page_size=PORTRAIT_SIZE,
              reverse: bool = False) -> tuple[int, int]:
    """Walk one or more `roots`, render every PNG into a multi-page
    PDF at `output_path`. Each folder's content is preceded by a
    title page showing the folder's name.

    `reverse=True` builds the PDF in reverse page order — last
    section's last image first, 1st Grade title last. Use when your
    printer outputs face-up so the finished stack still ends up with
    1st Grade on top.

    Folder order = argument order, subfolders sorted by name within
    each root. Default page orientation is PORTRAIT (8.5 x 11) —
    pass LANDSCAPE_SIZE to flip. Returns `(page_count, image_count)`.
    """
    folders = _resolve_folders(roots)
    if not folders:
        raise SystemExit("No PNG-bearing folders found.")
    non_empty = [f for f in folders if _pngs_in(f)]
    total_sections = len(non_empty)

    # Build the FULL page sequence first, then reverse if requested,
    # then write to the canvas in final order. Each entry is either
    # ("title", title_str, subtitle_str) or ("image", png_path).
    seq = []
    section_idx = 0
    log_lines = []
    for folder in folders:
        pngs = _pngs_in(folder)
        if not pngs:
            continue
        section_idx += 1
        title = os.path.basename(folder.rstrip(os.sep))
        subtitle = (f"Section {section_idx} of {total_sections}  ·  "
                    f"{len(pngs)} label{'s' if len(pngs) != 1 else ''}")
        seq.append(("title", title, subtitle))
        for png in pngs:
            seq.append(("image", png, None))
        rel = os.sep.join(
            folder.replace("\\", "/").split("/")[-2:])
        log_lines.append(f"  added {len(pngs):3d} PNG(s) from {rel!r}  "
                         f"(title page: {title!r})")
    if reverse:
        seq.reverse()
        log_lines.append("  → page order reversed (last section first)")

    c = canvas.Canvas(output_path, pagesize=page_size)
    pages = 0
    images = 0
    for kind, a, b in seq:
        if kind == "title":
            _draw_title_page(c, a, page_size, subtitle=b)
        else:
            _draw_image(c, a, page_size)
            images += 1
        c.showPage()
        pages += 1
    for line in log_lines:
        print(line)
    c.save()
    return pages, images


def _send_to_printer(pdf_path: str) -> bool:
    """Best-effort send to default printer via the OS shell verb."""
    try:
        os.startfile(pdf_path, "print")
        return True
    except Exception as ex:
        print(f"  couldn't send to printer: {ex}")
        return False


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Build a print-ready PDF from PNGs across "
                    "subfolders, with blank pages between folders.")
    p.add_argument("roots", nargs="+",
                   help="One or more parent folders (subfolders walked) "
                        "OR direct PNG folders. Order is preserved.")
    p.add_argument("--out", default=None,
                   help="Output PDF path (default: <first root>/_print.pdf)")
    p.add_argument("--print", dest="do_print", action="store_true",
                   help="Send the resulting PDF to the default printer")
    p.add_argument("--open", dest="do_open", action="store_true",
                   help="Open the resulting PDF in your default viewer")
    p.add_argument("--landscape", action="store_true",
                   help="Use landscape orientation (default: portrait)")
    p.add_argument("--reverse", action="store_true",
                   help="Build the PDF in REVERSE page order (last "
                        "section first, 1st Grade title last). Use "
                        "this when your printer outputs face-up so "
                        "the finished stack still has 1st Grade on top.")
    args = p.parse_args(argv)

    roots = [os.path.abspath(r) for r in args.roots]
    out = (os.path.abspath(args.out) if args.out
           else os.path.join(roots[0], "_print.pdf"))
    page_size = LANDSCAPE_SIZE if args.landscape else PORTRAIT_SIZE
    orient = "landscape" if args.landscape else "portrait"

    print(f"Orientation: {orient}"
          + ("  (reversed)" if args.reverse else ""))
    print("Roots:")
    for r in roots:
        print(f"  {r}")
    print(f"Output: {out}\n")
    pages, images = build_pdf(roots, out, page_size=page_size,
                              reverse=args.reverse)
    print(f"\nBuilt {out!r}")
    print(f"  {images} image(s) across {pages} page(s) "
          f"(blank separators included).")

    if args.do_print:
        if _send_to_printer(out):
            print("  sent to default printer.")
    if args.do_open:
        try:
            os.startfile(out)
        except Exception as ex:
            print(f"  couldn't open viewer: {ex}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
