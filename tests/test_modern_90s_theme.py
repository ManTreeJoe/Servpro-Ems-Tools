from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_shared_theme_uses_lops_restoration_palette():
    css = _read("web_shared/theme.css")
    for token in ("#F5F7F4", "#FFFFFF", "#164F3D", "#DFE5E0", "#EFB762"):
        assert token in css
    assert 'Georgia, "Times New Roman", serif' in css
    assert '"Aptos"' in css


def test_shell_and_jobs_board_share_the_same_visual_language():
    shell = _read("home_web_assets/app.css")
    jobs = _read("pipeline_web_assets/app.css")
    assert "background:#102F26" in shell
    assert "#1F5A47" in shell
    assert "#EFB762" in shell
    assert "var(--cobalt)" in jobs
    assert "--bg:#101613" in jobs
    assert "#0e1112" not in jobs


def test_shell_keeps_the_linguar_hub_logo():
    html = _read("home_web_assets/index.html")
    assert "../linguar_hub.png" in html


def test_shared_theme_cache_version_is_current_across_workspaces():
    for index_path in ROOT.glob("*_web_assets/index.html"):
        html = index_path.read_text(encoding="utf-8")
        if "web_shared/theme.css" in html:
            assert "web_shared/theme.css?v=20260910a" in html, index_path.parent.name
        assert "web_shared/workspace_controls.css?v=20260910a" in html, index_path.parent.name


def test_solid_green_actions_use_explicit_contrast_text():
    for relative_path in (
        "web_shared/theme.css",
        "home_web_assets/theme.css",
        "pipeline_web_assets/app.css",
        "snapshot_web_assets/theme.css",
    ):
        css = _read(relative_path)
        assert "--on-accent" in css or "#FFFFFF" in css


def test_visible_panels_do_not_restore_old_bright_green_palette():
    retired_tokens = ("#58b77d", "#69c98e", "#39a96b", "#36a66a")
    for css_path in ROOT.glob("*_web_assets/*.css"):
        css = css_path.read_text(encoding="utf-8").lower()
        for token in retired_tokens:
            assert token not in css, f"{css_path.name} restores retired accent {token}"


def test_clients_workspace_uses_shared_neutral_surfaces():
    css = _read("clients_web_assets/app.css")
    html = _read("clients_web_assets/index.html")
    assert "--client-green:var(--green)" in css
    assert "box-shadow:inset 2px 0 0 var(--green)" in css
    assert "radial-gradient" not in css
    assert '<span class="eyebrow">Client records</span>' not in html


def test_run_doc_uses_flat_operational_sections():
    css = _read("run_doc_editor_web_assets/app.css")
    assert "background-image:linear-gradient(var(--paper-line)" not in css
    assert ".monitor-column .section-head{box-shadow:inset 3px 0 0 var(--watch-amber)}" in css
