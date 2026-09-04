from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PANELS = tuple(sorted(ROOT.glob("*_web_assets/index.html")))


def test_every_workspace_loads_the_shared_control_layer():
    assert len(PANELS) >= 20
    for path in PANELS:
        html = path.read_text(encoding="utf-8")
        assert "web_shared/workspace_controls.css" in html, path.parent.name
        assert html.index("web_shared/workspace_controls.css") < html.index(
            "web_shared/responsive.css"
        ), path.parent.name


def test_shared_controls_define_the_canonical_workspace_shell():
    css = (ROOT / "web_shared" / "workspace_controls.css").read_text(
        encoding="utf-8"
    )
    for marker in (
        ".responsive-ui .topbar",
        ".responsive-ui .topbar-actions",
        ".responsive-ui .topbar .btn",
        ".responsive-ui .topbar .btn-primary",
        "flex-wrap: wrap",
        "white-space: nowrap",
        "z-index: 120",
        "min-height: 34px",
        "overscroll-behavior: contain",
    ):
        assert marker in css


def test_workspace_control_contract_is_documented():
    guide = (ROOT / "UI_UX_GUIDELINES.md").read_text(encoding="utf-8")
    for heading in (
        "### Workspace header",
        "### Job workspace",
        "### Modal footer",
    ):
        assert heading in guide
