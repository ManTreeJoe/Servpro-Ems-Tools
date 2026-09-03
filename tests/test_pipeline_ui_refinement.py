from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _asset(name):
    return (ROOT / "pipeline_web_assets" / name).read_text(encoding="utf-8")


def test_pipeline_cards_support_keyboard_and_named_actions():
    js = _asset("app.js")
    assert 'role="button" tabindex="0"' in js
    assert 'event.key !== "Enter" && event.key !== " "' in js
    assert 'aria-label="More actions for' in js


def test_card_role_does_not_suppress_its_own_click():
    js = _asset("app.js")
    assert "control && control !== cardEl" in js
    assert "onAuditCard(cardEl);" in js


def test_card_open_is_not_swallowed_by_horizontal_grab_scroll():
    js = _asset("app.js")
    assert 'draggable="false" data-no-drag' in js
    assert "ev.currentTarget.draggable = false" not in js
    assert "beginPointerCardDrag(cardEl, event)" in js
    assert "event.clientY >= window.innerHeight - 175" in js
    assert "openedOnPointerUp = true" in js
    assert "Open on pointerup" in js


def test_workspace_deep_load_survives_fast_lookup_failure():
    js = _asset("app.js")
    start = js.index("async function onAuditCard")
    end = js.index("function instantWorkspaceData", start)
    block = js[start:end]
    assert "const fullOutcome = await fullPromise" in block
    assert "workspace could not render" in block
    fast_failure = block[block.index("if (!fast?.ok)"):block.index("} else if", block.index("if (!fast?.ok)"))]
    assert "return;" not in fast_failure


def test_pipeline_comment_and_icon_controls_are_named():
    js = _asset("app.js")
    assert 'aria-label="Job comment"' in js
    assert 'aria-label="Close Stage for XA"' in js
    assert 'aria-label="Reset ${escapeAttr(s.label)} to default"' in js


def test_pipeline_authors_visible_focus_and_reduced_motion():
    css = _asset("app.css")
    assert ":focus-visible" in css
    assert "prefers-reduced-motion: reduce" in css
    assert "overscroll-behavior: contain" in css
    assert "content-visibility: auto" in css


def test_pipeline_keeps_primary_update_and_groups_shortcuts():
    js = _asset("app.js")
    modal_start = js.index('w.className = "modal-scrim audit-overlay";',
                           js.index("function openAuditModal"))
    header_start = js.index('<header class="modal-head">', modal_start)
    header_end = js.index('</header>\n      <div class="modal-body">',
                          header_start)
    header = js[header_start:header_end]
    for marker in ("card-quick-actions", "tool-quick-menu",
                   "data-copy-summary", "data-stage-xa",
                   "data-add-job-log", "data-open-docs-folder",
                   "data-open-trello"):
        assert marker in header
    assert "copy-quick-menu" not in header


def test_job_workspace_owns_the_audit_and_keeps_daily_actions_visible():
    js = _asset("app.js")
    header_start = js.index('<header class="modal-head">',
                            js.index("function openAuditModal"))
    header_end = js.index('</header>\n      <div class="modal-body">',
                          header_start)
    header = js[header_start:header_end]
    assert "Open full audit" not in js
    for marker in ("data-open-xa", "data-xa-note", "data-initial-notes",
                   "data-add-job-log", "data-open-trello",
                   "data-open-companycam"):
        assert marker in header


def test_add_update_reveals_and_focuses_the_job_log_editor():
    js = _asset("app.js")
    start = js.index("const openJobLogEditor")
    end = js.index('w.querySelectorAll("[data-add-job-log]")', start)
    editor = js[start:end]
    assert 'host.scrollIntoView({ behavior: "smooth", block: "start" })' in editor
    assert 'host.querySelector(\'[data-log-field="work_type"]\')?.focus()' in editor


def test_job_log_is_above_requirements_and_checklists():
    js = _asset("app.js")
    body_start = js.index('const body = `<div class="job-card-layout">')
    body_end = js.index('const w = document.createElement("div")', body_start)
    body = js[body_start:body_end]
    assert body.index('class="aud-section job-log-section"') < body.index(
        'class="aud-section progress-section"')
    assert body.index('class="aud-section job-log-section"') < body.index(
        'class="aud-section checklist-section"')


def test_cross_tool_job_links_target_jobs_not_removed_audit_panel():
    root = ROOT
    apa = (root / "apa_web_assets" / "app.js").read_text(encoding="utf-8")
    shared = (root / "web_shared" / "open_in.js").read_text(encoding="utf-8")
    assert 'Open in Audit' not in apa
    assert 'emsNavigateTo?.("audit"' not in apa
    assert '{ key: "pipeline", label: "▦ Jobs" }' in shared
    assert '{ key: "audit"' not in shared
    home = (root / "home_web_assets" / "app.js").read_text(encoding="utf-8")
    assert 'const key = d.key === "audit" ? "pipeline" : d.key;' in home


def test_pipeline_groups_companycam_actions_under_one_visible_menu():
    js = _asset("app.js")
    backend = (ROOT / "pipeline_web.py").read_text(encoding="utf-8")
    header_start = js.index('<div class="tool-quick-menu"><button type="button" class="action-btn destination tool-menu-trigger" aria-haspopup="menu" aria-expanded="false"><img src="../web_shared/companycam.png"')
    header_end = js.index('</div></div>', header_start)
    header = js[header_start:header_end]
    assert "tool-menu-panel" in header
    assert "data-open-companycam" in header
    assert "data-pull-companycam" in header
    assert "Pull photos" in header
    assert "data-companycam-report" in header
    assert "data-quick-photo-report" in header
    assert 'class="aud-section photo-report-section"' not in js
    assert "function openCompanyCamPullModal" in js
    assert "companycam_plan_pull" in backend
    assert "companycam_pull_assigned_bg" in backend


def test_pipeline_job_actions_match_the_audit_button_language():
    css = _asset("app.css")
    js = _asset("app.js")
    for marker in ("background:var(--surface-2)",
                   "border:1px solid var(--border)",
                   "padding:7px 11px", "border-radius:7px",
                   "font-size:12px", "font-weight:600",
                   "background:var(--green)",
                   "background:var(--green-hover)"):
        assert marker in css
    assert 'CompanyCam <small>⌄</small></button>' in js
    assert 'XA <small>⌄</small></button>' in js
    assert "quick-action-group" not in js


def test_tool_menus_stay_inside_card_and_job_info_is_click_to_copy():
    css = _asset("app.css")
    js = _asset("app.js")
    menu_rule = css[css.index(".tool-menu-panel"):
                    css.index(".more-quick-menu", css.index(".tool-menu-panel"))]
    assert "left:0" in menu_rule
    assert 'data-copy-job-field="${escapeAttr(field.value)}"' in js
    assert 'closest(".tool-quick-menu")' in js


def test_tool_menus_open_on_hover_and_do_not_latch_for_mouse_users():
    css = _asset("app.css")
    js = _asset("app.js")
    assert ".tool-quick-menu:hover>.tool-menu-panel" in css
    assert ".tool-quick-menu:focus-within>.tool-menu-panel" in css
    assert 'menu.addEventListener("pointerleave"' in js
    assert 'event.pointerType !== "touch"' in js
    assert 'setOpen(false)' in js


def test_autosaved_job_controls_do_not_trigger_discard_warning():
    js = _asset("app.js")
    assert 'w.addEventListener("input", () => { userDirty = true; });' not in js
    assert 'w.addEventListener("change", () => { userDirty = true; });' not in js
    assert 'markDraftDirty("job-log"' in js
    assert 'markDraftDirty("comment"' in js
    assert 'markDraftDirty(`work-owner-' in js
    assert "clearDraftDirty(ownerDraftKey)" in js


def test_job_info_is_editable_with_one_explicit_save():
    js = _asset("app.js")
    py = (ROOT / "pipeline_web.py").read_text(encoding="utf-8")
    for marker in ("data-edit-job-info", "function openJobInfoEditor",
                   "data-job-info-input", "Save job info",
                   "job_settings_load", "job_settings_save"):
        assert marker in js
    assert "class Api(JobSettingsApi):" in py
    assert "from job_settings_api import JobSettingsApi" in py


def test_pipeline_checklists_use_daily_run_role_tabs_inside_division():
    js = _asset("app.js")
    css = _asset("app.css")
    for marker in ("checklist-division-tabs", "checklist-role-tabs",
                   "data-checklist-role", "data-checklist-pane",
                   '["intake", "Intake"]', '["field", "Field"]',
                   '["est", "Estimating"]'):
        assert marker in js
    assert ".checklist-role-tabs" in css
    assert ".checklist-role-pane[hidden]" in css


def test_current_audit_labels_missing_and_requirement_states_explicitly():
    js = _asset("app.js")
    css = _asset("app.css")
    for marker in ('missing item${issues.length === 1',
                   "Missing ${escapeHtml(i.kind.toLowerCase())}",
                   'item.status === "blocked" ? "Blocked"',
                   ': "Missing"', "audit-missing-count", "req-status"):
        assert marker in js
    assert ".aud-tag.aud-missing" in css
    assert ".req-status.status-completed" in css


def test_pipeline_status_and_search_are_accessible():
    html = _asset("index.html")
    assert 'aria-label="Search Jobs"' in html
    assert 'aria-live="polite"' in html
    assert 'class="skip-link"' in html


def test_restored_job_search_is_never_an_invisible_lane_filter():
    """A persisted search must appear in the input that is filtering lanes."""
    js = _asset("app.js")
    restored = 'state.search         = PanelState.get("search", "");'
    reflected = '$("#search-box").value = state.search;'
    assert restored in js
    assert reflected in js
    assert js.index(restored) < js.index(reflected) < js.index("const initialView")
def test_jobs_board_zoom_is_visible_persistent_and_board_scoped():
    html = _asset("index.html")
    js = _asset("app.js")
    css = _asset("app.css")
    for marker in ("board-zoom-out", "board-zoom-reset", "board-zoom-in"):
        assert marker in html
    for marker in ('PanelState.get("boardZoom", 1)',
                   "PanelState.set({ boardZoom: next })",
                   "function onBoardZoomShortcut", "Math.max(0.7",
                   "Math.min(1.4"):
        assert marker in js
    assert "zoom: var(--board-zoom, 1)" in css


def test_apa_vertical_wheel_stays_in_the_column():
    apa_html = (ROOT / "apa_web_assets" / "index.html").read_text(encoding="utf-8")
    assert '<main class="board" id="board" data-hdrag-nowheel>' in apa_html


def test_job_shelf_separates_star_shortcuts_from_held_cards():
    html = _asset("index.html")
    js = _asset("app.js")
    css = _asset("app.css")
    assert 'id="job-shelf"' in html and 'id="job-shelf-drop-hint"' in html
    for marker in ('mode = "starred"', 'item.mode === "held"',
                   'addToJobShelf(live ? shelfEntryFromCard(live)',
                   '}, "held")', 'data-act="star"',
                   'mode-${escapeAttr(item.mode || "starred")}'):
        assert marker in js
    assert ".job-shelf.drop-ready" in css
    assert ".shelf-card.mode-held" in css
    assert "--fan-angle:" in js and "--fan-drop:" in js
    assert "Trello stays in its current lane until you place it" in js
    assert ".card-drag-ghost" in css


def test_held_job_detects_trello_conflicts_and_moves_can_be_undone():
    js = _asset("app.js")
    css = _asset("app.css")
    for marker in ("reconcileJobShelfWithBoard();", "heldConflict",
                   "actualListId", "showMoveUndo(drag, toListId, toLane)",
                   'className = "requirement-undo move-undo"'):
        assert marker in js
    assert ".shelf-card.has-conflict" in css
