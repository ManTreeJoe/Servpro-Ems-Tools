"""Jobs must confirm mismatched folder links inside the WebView UI.

Native ``window.confirm`` is not dependable in pywebview/WebView2: it may
return ``undefined`` without displaying anything.  A mismatch is common for
commercial, unit, and differently-formatted customer folder names, so that
behavior makes the visible Link folder action appear to do nothing.
"""

from pathlib import Path


APP_JS = (Path(__file__).parents[1] / "pipeline_web_assets" / "app.js")


def _folder_link_modal_source() -> str:
    source = APP_JS.read_text(encoding="utf-8")
    start = source.index("async function openJobFolderLinkModal")
    end = source.index("\nfunction formatAppDate", start)
    return source[start:end]


def test_folder_link_mismatch_uses_in_app_confirmation():
    source = _folder_link_modal_source()

    assert "await confirmJobFolderLink(" in source
    assert "window.confirm(" not in source

