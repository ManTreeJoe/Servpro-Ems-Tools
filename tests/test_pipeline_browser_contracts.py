"""Browser-level contracts for Jobs interactions that static tests miss.

These tests use the same Chromium engine bundled for browser-backed tools and
assert rendered behavior.  They deliberately complement (not duplicate) the
fast source-contract tests in ``test_pipeline_ui_refinement``.
"""

from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).parents[1]


def test_board_zoom_changes_the_rendered_lane_width():
    """Changing board zoom must change pixels, not merely saved state."""
    css = (ROOT / "pipeline_web_assets" / "app.css").read_text(encoding="utf-8")
    markup = f"""
        <style>{css}</style>
        <main id="board-view" class="board-wrap" style="width:1400px;height:800px">
          <div class="lanes-row"><section class="lane"><div class="lane-cards"></div></section></div>
        </main>
    """
    with sync_playwright() as playwright:
        # Desktop Linguar Hub renders with Edge WebView2. Using the installed
        # Edge channel also keeps this contract independent of pytest's
        # deliberately isolated LOCALAPPDATA directory.
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.set_content(markup)
        lane = page.locator(".lane")
        normal = lane.evaluate("element => element.getBoundingClientRect().width")
        page.locator("#board-view").evaluate(
            "element => element.style.setProperty('--board-zoom', '0.8')")
        narrow = lane.evaluate("element => element.getBoundingClientRect().width")
        page.locator("#board-view").evaluate(
            "element => element.style.setProperty('--board-zoom', '1.4')")
        wide = lane.evaluate("element => element.getBoundingClientRect().width")
        browser.close()

    assert narrow < normal < wide, (narrow, normal, wide)
