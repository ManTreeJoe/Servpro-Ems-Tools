from pathlib import Path

from PIL import Image

import pipeline_web


def test_pipeline_offers_per_board_presets_and_custom_photo():
    root = Path(__file__).parents[1]
    html = (root / "pipeline_web_assets" / "index.html").read_text(encoding="utf-8")
    js = (root / "pipeline_web_assets" / "app.js").read_text(encoding="utf-8")
    css = (root / "pipeline_web_assets" / "app.css").read_text(encoding="utf-8")
    for marker in ("customize-board-btn", "board-customize-dialog",
                   "custom-background-btn", "data-board-look=\"water\"",
                   "data-board-look=\"contents\"", "data-board-look=\"recon\""):
        assert marker in html
    for marker in ("boardLooks", "hydrateCustomBoardLooks",
                   "choose_board_background", "applyBoardLook"):
        assert marker in js
    for marker in ("has-custom-background", "--board-custom-image",
                   "board-customize-dialog", "preset-blueprint"):
        assert marker in css


def test_custom_board_photo_is_resized_and_returned_without_database_write(tmp_path):
    source = tmp_path / "jobsite.png"
    Image.new("RGB", (3000, 1800), (34, 82, 61)).save(source)
    result = pipeline_web.Api().load_board_background(str(source))
    assert result["ok"] is True
    assert result["path"] == str(source)
    assert result["data_url"].startswith("data:image/jpeg;base64,")
    assert len(result["data_url"]) < 250_000
