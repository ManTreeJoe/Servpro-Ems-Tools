from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_shared_theme_uses_graphite_restoration_palette():
    css = _read("web_shared/theme.css")
    for token in ("#0E1112", "#2F7750", "#647FCD", "#E8A64B", "--green-soft"):
        assert token in css


def test_shell_and_jobs_board_share_the_same_visual_language():
    shell = _read("home_web_assets/theme.css").lower()
    jobs = _read("pipeline_web_assets/app.css")
    assert "--bg:#0e1112" in shell
    assert "var(--cobalt)" in jobs
    assert "#111512" not in jobs
    assert "#181e1a" not in jobs


def test_solid_green_actions_use_explicit_contrast_text():
    for relative_path in (
        "web_shared/theme.css",
        "home_web_assets/theme.css",
        "pipeline_web_assets/app.css",
        "snapshot_web_assets/theme.css",
    ):
        css = _read(relative_path)
        assert "--on-accent" in css or "#FFFFFF" in css
