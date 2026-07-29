"""Minimal Outlook `.msg` body extractor.

OC's daily-run docs are Outlook message files (`.msg`) rather than the
`.docx` the IE department uses. A `.msg` is an OLE compound file; the
plain-text body lives in a single stream, so we read just that stream
with `olefile` (tiny, pure-Python) instead of pulling a heavyweight
mail-parsing dependency.

Body property tag is PR_BODY (0x1000): stream `__substg1.0_1000001F`
is the Unicode (UTF-16LE) form; `__substg1.0_1000001E` is the ANSI
fallback for older messages.
"""
import olefile

_BODY_STREAMS = (
    ("__substg1.0_1000001F", "utf-16-le"),   # Unicode body (typical)
    ("__substg1.0_1000001E", "latin-1"),     # ANSI body (fallback)
)


def read_msg_text(path: str) -> str:
    """Return the plain-text body of a `.msg` file, or "" if it can't be
    read. Never raises — a malformed/locked message just yields ""."""
    try:
        if not olefile.isOleFile(path):
            return ""
        with olefile.OleFileIO(path) as ole:
            for stream, enc in _BODY_STREAMS:
                if ole.exists(stream):
                    return ole.openstream(stream).read().decode(enc, "ignore")
    except Exception:
        return ""
    return ""
