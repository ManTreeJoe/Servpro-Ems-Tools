"""Workcenter (servpronet.io) read-only integration.

WC2.0 is an Angular SPA. This module drives it through Playwright with
a persistent profile so the user only logs in once. Read-only by design
— never clicks Delete, Import, or any state-changing button.

Public surface:
    ensure_logged_in(headless=False)
    search_jobs(query)         -> [JobMatch, ...]
    download_forms(project_id, dest_dir, carrier=None)
    download_attachments(project_id, dest_dir)
    close()

Selectors are anchored on stable user-visible text (button labels, tab
names, table headers) — never on Angular-generated class names, since
those are bundle-hash-suffixed and change on every Workcenter deploy.

Phase 1 implements: ensure_logged_in + search_jobs.
download_forms / download_attachments are stubs to be filled in Phase 2
once we've validated selectors against the live site.
"""
from __future__ import annotations

import os
import re
import sys
import threading
from dataclasses import dataclass, asdict
from typing import List, Optional

import paths

# Default Workcenter root URL. Overridable via config["workcenter_url"].
_DEFAULT_URL = "https://workcenter.servpronet.io/"

# Persistent profile dir — keeps cookies/localStorage across restarts so
# the user only types credentials once. Stored under DATA_DIR so it
# survives reinstalls and isn't OneDrive-synced.
_PROFILE_DIR = paths.data("workcenter_profile")

# Module-level singleton — Playwright is heavy to start, so we share one
# context across calls. Guard with a lock since callers may run from
# different threads (tkinter worker pool, CLI smoke test).
_lock = threading.Lock()
_state = {
    "playwright": None,
    "context":    None,
    "page":       None,
}


# Loss-type codes used in the trailing segment of a Workcenter Project ID
# (e.g., 2604-202129WTR → "WTR" → water). Audit/EMS owns the first set;
# Contents and Recon are explicitly NOT our work and must be filtered out
# so the audit doesn't pull files from those job shells. Codes here come
# from observed job IDs at this franchise — extend cautiously when new
# ones appear, since misclassifying a Contents job as EMS would land
# someone else's photos in our PICS folder.
EMS_LOSS_CODES = frozenset({
    "WTR",  # Water
    "FIR",  # Fire
    "MLD",  # Mold
    "SMK",  # Smoke
    "BIO",  # Biohazard
    "STO",  # Storm
    "STM",  # Storm (alt)
    "TRA",  # Trauma
    "ASB",  # Asbestos
    "LED",  # Lead
    "VAN",  # Vandalism
    "GEN",  # General
})
NON_EMS_LOSS_CODES = frozenset({
    "CON",  # Contents
    "CTS",  # Contents (alt)
    "REC",  # Reconstruction
    "RCN",  # Reconstruction (alt)
    "RST",  # Restoration build-back
})


def classify_loss_code(code: str) -> str:
    """Return 'ems', 'non_ems', or 'unknown' for a Project ID suffix.

    Unknown codes are surfaced (not silently dropped) so a new SERVPRO
    code that hasn't been added to the lists above doesn't disappear —
    the caller can decide whether to include it.
    """
    c = (code or "").upper()
    if c in EMS_LOSS_CODES:    return "ems"
    if c in NON_EMS_LOSS_CODES: return "non_ems"
    return "unknown"


@dataclass
class JobMatch:
    """One row from the WC2.0 Search Results dialog's Job Results table."""
    project_id:    str
    name:          str = ""
    address:       str = ""
    progress:      str = ""
    loss_type:     str = ""        # e.g. "Water" — from results column
    loss_code:     str = ""        # 3-letter suffix on the Project ID
    claim_number:  str = ""        # populated only after project-page visit
    date_received: str = ""
    date_completed: str = ""
    # Project pages live on the legacy workcenter-rm.servpronet.io
    # subdomain and are addressed by GUIDs, not the Project ID. We pull
    # the GUIDs out of the search row's title-link href at parse time so
    # downstream calls (claim#, downloads) don't need a second lookup.
    region_guid:   str = ""
    job_guid:      str = ""
    legacy_url:    str = ""

    @property
    def category(self) -> str:
        """'ems', 'non_ems', or 'unknown' — drives EMS-only filtering."""
        return classify_loss_code(self.loss_code)

    def to_dict(self):
        return asdict(self)


_LEGACY_BASE = "https://workcenter-rm.servpronet.io"


def _build_legacy_url(region_guid: str, job_guid: str) -> str:
    """Construct the legacy SERVPRONET project-page URL. Returns "" when
    either GUID is missing so downstream code can detect the failure."""
    if not region_guid or not job_guid:
        return ""
    return (f"{_LEGACY_BASE}/Jobs/JobDetail_RM"
            f"?signin=oidc&regionGuid={region_guid}&jobGuid={job_guid}")


def _extract_guids(href: str):
    """Pull (regionGuid, jobGuid) out of a Workcenter title-link href.
    Both come back lowercase; URL params are case-insensitive but the
    legacy app sometimes returns mixed case in different places."""
    if not href:
        return "", ""
    rm = re.search(r'regionGuid=([0-9a-fA-F-]+)', href)
    jm = re.search(r'jobGuid=([0-9a-fA-F-]+)',    href)
    return ((rm.group(1).lower() if rm else ""),
            (jm.group(1).lower() if jm else ""))


def _config_url() -> str:
    """Workcenter root URL from user config, falling back to default."""
    try:
        import config
        u = (config.load().get("workcenter_url") or "").strip()
        if u:
            # User's stored URL might point at a deep page (e.g. a saved
            # WIP Board view). Strip back to the host root so we land on
            # the dashboard / search bar consistently.
            from urllib.parse import urlparse
            p = urlparse(u)
            if p.scheme and p.netloc:
                return f"{p.scheme}://{p.netloc}/"
    except Exception:
        pass
    return _DEFAULT_URL


def _ensure_started():
    """Lazily start Playwright + open the persistent context. Cheap to
    call repeatedly — returns the cached page if already open."""
    if _state["page"] is not None:
        return _state["page"]
    _log("starting Playwright runtime…")
    from playwright.sync_api import sync_playwright
    os.makedirs(_PROFILE_DIR, exist_ok=True)
    pw  = sync_playwright().start()
    _log(f"launching Chromium with persistent profile: {_PROFILE_DIR}")
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=_PROFILE_DIR,
        headless=False,                       # visible by default — login flow
        viewport={"width": 1400, "height": 900},
        accept_downloads=True,                # needed for form download phase
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    _state.update(playwright=pw, context=ctx, page=page)
    _log("Chromium ready")
    return page


def close():
    """Tear down the browser and Playwright runtime. Called on app exit
    or when the user explicitly logs out via Settings."""
    with _lock:
        try:
            if _state["context"] is not None:
                _state["context"].close()
        except Exception:
            pass
        try:
            if _state["playwright"] is not None:
                _state["playwright"].stop()
        except Exception:
            pass
        _state.update(playwright=None, context=None, page=None)


# ── Login detection ───────────────────────────────────────────────────────────

# Anchored on the WC2.0 main-nav links — present on every authenticated
# page, absent on the login screen. `:has-text` does a partial match so
# trailing whitespace, icon prefixes, or bullet separators don't break
# detection. Logout is the most unique anchor since "Dashboard" /
# "Contacts" appear elsewhere on the page (column headers, etc.).
_LOGGED_IN_MARKERS = [
    'a:has-text("Logout"), button:has-text("Logout")',
    'a:has-text("Dashboard"), button:has-text("Dashboard")',
    ':has-text("Multiple Franchises")',  # user-name strip in the header
]


def _is_logged_in(page, timeout_ms=4000) -> bool:
    """True if any of the post-login chrome elements are visible.

    URL-based check first — the login page tends to have /login or
    /signin in its path; everything else is the authenticated app.
    """
    try:
        url = (page.url or "").lower()
        if url and "/login" not in url and "/signin" not in url \
                 and "/auth" not in url and "about:blank" not in url:
            # URL says we're past login, but verify by waiting briefly
            # for any one of the chrome markers to confirm the app
            # rendered (vs. landing on a blank page).
            for sel in _LOGGED_IN_MARKERS:
                try:
                    page.wait_for_selector(sel, state="visible",
                                            timeout=timeout_ms)
                    return True
                except Exception:
                    continue
    except Exception:
        pass
    return False


def ensure_logged_in(timeout_seconds: int = 600) -> bool:
    """Open Workcenter, return when the session is authenticated.

    On first run (or when cookies have expired) the user logs in
    interactively in the visible Chromium window. We then poll until
    the post-login chrome appears, or until `timeout_seconds` elapses.

    Returns True on success, False on timeout.
    """
    with _lock:
        page = _ensure_started()
        url  = _config_url()
        _log(f"navigating to {url}")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
        except Exception as ex:
            _log(f"first goto raced ({ex}); retrying with soft wait")
            page.goto(url, wait_until="commit", timeout=20000)

        # Fast path — already authenticated from a prior session
        _log("checking for an existing logged-in session…")
        if _is_logged_in(page, timeout_ms=3000):
            _log(f"already logged in — current url: {page.url}")
            return True

        # Slow path — poll until login completes (user-driven). 2s ticks
        # let the user take their time entering creds + auth key.
        _log("not logged in — please complete login in the Chromium window")
        import time
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if _is_logged_in(page, timeout_ms=2000):
                _log(f"login detected — current url: {page.url}")
                return True
            time.sleep(1)
        _log(f"login timed out after {timeout_seconds}s")
        return False


# ── Search ────────────────────────────────────────────────────────────────────

# The top-right search input on every WC2.0 page. The visible UI shows a
# "Business Name" dropdown + an unlabeled search box + a 🔍 icon. The
# input itself usually has no placeholder and no aria-label, so we cast
# wide net: anything inside a form-field/header that's near "Search"
# text, or any visible text input in the page header.
_SEARCH_INPUT_CANDIDATES = [
    # WC2.0 — the actual placeholder pulled from the live DOM. Anchor
    # on the prefix so a future copy tweak ("Search Projects/Contacts…"
    # without "for") still matches.
    'input[placeholder^="Search for Projects"]',
    'input[placeholder*="Projects/Contacts"]',
    'input[placeholder*="Search"]',
    'input[aria-label="Search"]',
    'input[type="search"]',
    # Generic fallbacks for the legacy SERVPRONET WIP Board UI.
    'mat-toolbar input[matInput]',
    'mat-toolbar input',
    'header input[type="text"]',
    'input.search',
    'input[name="search" i]',
    'input[name*="query" i]',
]

# The Search Results modal that pops on submit. Heading text is stable
# user-visible copy, used in both WC2.0 and the legacy SERVPRONET UI.
_RESULTS_HEADER = 'text="Search Results"'
_JOB_RESULTS_HEADER = 'text="Job Results"'

# Verbose flag flipped by the CLI's --debug switch — when set we print
# step-by-step progress and dump a screenshot on any failure so the
# user can pinpoint which step broke.
_DEBUG = False


def _log(msg):
    """Always-on progress narration. We used to gate this on --debug, but
    when the script hangs you can't tell what step it's stuck on, so
    everything prints unconditionally and forces flush so terminals
    that buffer stdout don't swallow it."""
    print(f"[workcenter] {msg}", flush=True)


def _dump_screenshot(page, tag):
    """Save a screenshot under DATA_DIR for debugging selector mismatches.
    Best-effort; never raises."""
    try:
        path = paths.data(f"workcenter_debug_{tag}.png")
        page.screenshot(path=path, full_page=True)
        _log(f"saved screenshot → {path}")
    except Exception as ex:
        _log(f"screenshot failed: {ex}")


# JS walker — runs INSIDE the browser, returns a structured inventory of
# every visible input/button. Letting the page tell us what's there is
# more robust than guessing CSS selectors against an Angular SPA whose
# class names change on every deploy.
_DISCOVER_JS = r"""
() => {
  const visible = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    const cs = window.getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden" ||
        parseFloat(cs.opacity) === 0) return false;
    return true;
  };
  const describe = (el) => ({
    tag: el.tagName.toLowerCase(),
    type: el.getAttribute("type") || "",
    id: el.id || "",
    name: el.getAttribute("name") || "",
    placeholder: el.getAttribute("placeholder") || "",
    ariaLabel: el.getAttribute("aria-label") || "",
    text: (el.innerText || el.textContent || "").trim().slice(0, 80),
    classes: (el.className || "").toString().slice(0, 120),
    rect: (() => {
      const r = el.getBoundingClientRect();
      return {x: Math.round(r.x), y: Math.round(r.y),
              w: Math.round(r.width), h: Math.round(r.height)};
    })(),
  });
  const inputs = [...document.querySelectorAll("input, textarea")]
    .filter(visible).map(describe);
  const buttons = [...document.querySelectorAll(
    "button, mat-icon, [role='button'], a.btn, .glyphicon-search")]
    .filter(visible).map(describe);
  return {inputs, buttons};
}
"""


def _walk_page(page):
    """Return a structured inventory of visible inputs+buttons."""
    try:
        return page.evaluate(_DISCOVER_JS)
    except Exception as ex:
        _log(f"page walk failed: {ex}")
        return {"inputs": [], "buttons": []}


def _score_search_input(info):
    """Higher score = more likely to be the search box."""
    score = 0
    blob = " ".join([
        info.get("placeholder", ""), info.get("ariaLabel", ""),
        info.get("name", ""),       info.get("id", ""),
    ]).lower()
    for kw, w in (("search", 5), ("project", 3), ("contact", 3),
                   ("query", 2)):
        if kw in blob:
            score += w
    if info.get("type") in ("search", "text"):
        score += 1
    # Prefer inputs in the top of the viewport (header bar territory).
    if info.get("rect", {}).get("y", 99999) < 120:
        score += 2
    return score


def _find_search_input(page):
    # Prefer Playwright's high-level get_by_placeholder API — it survives
    # minor placeholder copy changes and dom restructuring.
    try:
        loc = page.get_by_placeholder("Search for Projects",  exact=False)
        loc.first.wait_for(state="visible", timeout=2500)
        _log("found search input via get_by_placeholder('Search for Projects')")
        return loc.first
    except Exception:
        pass
    # Fall back to the static selector list (cheap, no network).
    for sel in _SEARCH_INPUT_CANDIDATES:
        try:
            el = page.wait_for_selector(sel, state="visible", timeout=1000)
            if el:
                _log(f"found search input via: {sel}")
                return el
        except Exception:
            continue
    # Last resort — walk the page and pick the highest-scoring input.
    inv = _walk_page(page)
    inputs = inv.get("inputs", [])
    if _DEBUG:
        _log(f"page walk: {len(inputs)} visible input(s), "
             f"{len(inv.get('buttons', []))} button(s)")
        for i, info in enumerate(inputs[:8]):
            _log(f"  input[{i}] score={_score_search_input(info)}  "
                 f"placeholder={info.get('placeholder')!r}  "
                 f"id={info.get('id')!r}  rect={info.get('rect')}")
    if inputs:
        ranked = sorted(inputs, key=_score_search_input, reverse=True)
        best = ranked[0]
        if _score_search_input(best) > 0:
            sel = (f'input#{best["id"]}' if best.get("id")
                   else 'input[placeholder*="' + best.get("placeholder", "")[:20] + '"]')
            try:
                el = page.wait_for_selector(sel, state="visible", timeout=1500)
                if el:
                    _log(f"found search input by walking page: {sel}")
                    return el
            except Exception:
                pass
    _dump_screenshot(page, "no_search_input")
    raise RuntimeError(
        "Could not locate the Workcenter search input. "
        "A screenshot was saved to %APPDATA%\\Linguar Hub\\"
        "workcenter_debug_no_search_input.png — share it so the "
        "selector list can be updated.")


def _submit_search(page):
    """Submit the search — try Enter, then click adjacent magnifier icons,
    then dispatch a synthetic 'submit' event on any wrapping <form>.
    Returns True once the Search Results modal appears.
    """
    page.keyboard.press("Enter")
    try:
        page.wait_for_selector(_RESULTS_HEADER, timeout=2500)
        _log("results modal appeared after Enter")
        return True
    except Exception:
        _log("Enter didn't trigger results — looking for a search button")

    # Tier 1 — well-known search-icon selectors.
    for sel in [
        'button[aria-label*="Search" i]',
        'button:has(mat-icon:has-text("search"))',
        'mat-icon[fontIcon="search"]',
        'mat-icon:has-text("search")',
        '.fa-search', '.glyphicon-search',
    ]:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                btn.click()
                _log(f"clicked search button via: {sel}")
                page.wait_for_selector(_RESULTS_HEADER, timeout=4000)
                return True
        except Exception:
            continue

    # Tier 2 — walk the page inventory and click any visible button whose
    # text/aria-label looks searchy. This catches non-standard Workcenter
    # markup we haven't seen yet without us hardcoding a new selector.
    inv = _walk_page(page)
    for info in inv.get("buttons", []):
        blob = " ".join([info.get("ariaLabel", ""),
                          info.get("text", ""),
                          info.get("classes", "")]).lower()
        if "search" in blob and info.get("rect", {}).get("y", 99999) < 200:
            sel_id = info.get("id")
            if sel_id:
                try:
                    page.click(f'#{sel_id}')
                    _log(f"clicked search button by walked id: {sel_id}")
                    page.wait_for_selector(_RESULTS_HEADER, timeout=4000)
                    return True
                except Exception:
                    pass

    # Tier 3 — last-ditch: dispatch a synthetic submit on the input's
    # nearest <form> ancestor. Some Angular components wire submission
    # through (ngSubmit) rather than a button click.
    try:
        page.evaluate("""
            () => {
                const inp = document.querySelector(
                    'input[placeholder*="Projects/Contacts"], '+
                    'input[placeholder*="Search"]');
                if (!inp) return false;
                const form = inp.closest('form');
                if (form) form.dispatchEvent(
                    new Event('submit', {bubbles: true, cancelable: true}));
                return !!form;
            }
        """)
        page.wait_for_selector(_RESULTS_HEADER, timeout=2500)
        _log("results modal appeared after synthetic form submit")
        return True
    except Exception:
        pass

    _dump_screenshot(page, "no_results_modal")
    return False


# Project IDs look like 2604-202129WTR (4-digit franchise + 6-digit job
# number + 3-letter loss code). The loss code is captured separately so
# we can classify EMS vs non-EMS without an extra page visit.
_PROJECT_ID_RE = re.compile(
    r'\b(\d{4}-\d{4,})([A-Z]{2,4})\b')


def _parse_results_table(page) -> List[JobMatch]:
    """Read rows out of the open Search Results modal.

    WC2.0 may render results as plain <table> rows OR as Angular
    Material <mat-table>/<mat-row>/<cdk-row>. We try both flavors and
    fall back to a JS-side regex sweep over the modal's text content.
    """
    # Wait for the dialog body. Some WC2.0 builds wrap it in <mat-dialog>;
    # falling back to broader selectors keeps this resilient.
    dialog = None
    for sel in ('mat-dialog-container', '[role="dialog"]', '.modal-content',
                '.cdk-overlay-pane'):
        try:
            dialog = page.wait_for_selector(sel, state="visible", timeout=3000)
            if dialog:
                _log(f"found dialog container via: {sel}")
                break
        except Exception:
            continue

    # WC2.0 renders a <mat-spinner> inside .loading-indicator while the
    # search AJAX is in flight, then detaches it on completion. If we
    # parse the dialog before the spinner clears we just see Angular's
    # placeholder comments and find zero rows. Wait it out — up to 12s,
    # which covers the slow query case but doesn't hang forever if the
    # spinner never detaches (corrupt session / network drop).
    try:
        page.wait_for_selector(
            'mat-dialog-container .loading-indicator mat-spinner, '
            'mat-dialog-container mat-spinner, '
            '[role="dialog"] mat-spinner',
            state="detached", timeout=12000)
        _log("results spinner cleared")
    except Exception:
        _log("spinner did not detach within 12s — parsing anyway")

    # Try every flavor of "row" we know about — plain <tr>, Material's
    # <mat-row>, CDK's <cdk-row>, ARIA role="row", and Kendo UI grid
    # markup (Workcenter renders search results as a Kendo grid: each
    # row carries `kendogridlogicalrow` plus `data-kendo-grid-item-index`).
    # Modal-scoped selectors run first; if those miss, we re-try the
    # same selectors against the whole page so a Kendo grid living
    # outside the dialog wrapper still gets picked up.
    row_selectors_in_dialog = [
        'mat-dialog-container tr[kendogridlogicalrow]',
        '[role="dialog"] tr[kendogridlogicalrow]',
        'mat-dialog-container tr', '[role="dialog"] tr',
        'mat-dialog-container mat-row', '[role="dialog"] mat-row',
        'mat-dialog-container cdk-row', '[role="dialog"] cdk-row',
        'mat-dialog-container [role="row"]', '[role="dialog"] [role="row"]',
        '.cdk-overlay-pane tr', '.cdk-overlay-pane [role="row"]',
        # WC2.0's <global-search-common> — results land in .row divs
        # AFTER the Job Results <h6> header, not in a <table> at all.
        'global-search-common .row > div',
    ]
    row_selectors_global = [
        'tr[kendogridlogicalrow]',
        'tr[data-kendo-grid-item-index]',
        'tr.k-grid-row',
        'tr[role="row"]',
        'mat-row, cdk-row',
    ]
    rows = []
    for rsel in row_selectors_in_dialog + row_selectors_global:
        rows = page.query_selector_all(rsel)
        if rows:
            _log(f"found {len(rows)} row element(s) via: {rsel}")
            break

    out: List[JobMatch] = []
    for row in rows:
        # Material rows use <mat-cell>; plain tables use <td>; Kendo
        # rows use <td role="gridcell">. Try them all.
        cells = row.query_selector_all(
            'td, mat-cell, cdk-cell, [role="cell"], [role="gridcell"]')
        if not cells:
            row_text = (row.inner_text() or "").strip()
            if not row_text:
                continue
            texts = [row_text]
        else:
            texts = [(c.inner_text() or "").strip() for c in cells]
        if not any(texts):
            continue

        # Workcenter title cell renders as
        # <a class="title-link" href="...regionGuid=...&jobGuid=...">
        #   {name} - {project_id}</a>.
        # The href is the path to the legacy project page; we extract
        # the GUIDs at parse time so download/claim# calls don't have
        # to re-search to find them.
        title_anchor = row.query_selector('a.title-link, a[class*="title-link"]')
        title_text = ""
        title_href = ""
        if title_anchor:
            try:
                title_text = (title_anchor.inner_text() or "").strip()
                title_href = title_anchor.get_attribute("href") or ""
            except Exception:
                pass

        pid, loss_code, name_from_title = "", "", ""
        if title_text:
            m = _PROJECT_ID_RE.search(title_text)
            if m:
                pid = m.group(0)
                loss_code = m.group(2)
                # Strip the ID + separator off the title to leave just
                # the insured name. Workcenter uses " - " as the joiner.
                stripped = title_text[: m.start()].rstrip(" -· ")
                name_from_title = stripped.strip()

        if not pid:
            for t in texts:
                m = _PROJECT_ID_RE.search(t)
                if m:
                    pid = m.group(0)
                    loss_code = m.group(2)
                    break
        if not pid:
            continue

        addr = ""
        for t in texts:
            if t and t != pid and (',' in t or re.search(r'\b[A-Z]{2}\s*\d{5}', t)):
                addr = t
                break

        if name_from_title:
            name = name_from_title
        else:
            name = ""
            for t in texts:
                if t and t != pid and t != addr and pid not in t:
                    name = t
                    break

        region_guid, job_guid = _extract_guids(title_href)
        out.append(JobMatch(
            project_id=pid, name=name, address=addr, loss_code=loss_code,
            region_guid=region_guid, job_guid=job_guid,
            legacy_url=_build_legacy_url(region_guid, job_guid)))

    # Last-resort fallback — sweep the entire dialog's text for project
    # IDs using the regex. Drops name/address but at least gets the IDs.
    if not out and dialog is not None:
        try:
            blob = (dialog.inner_text() or "")
            for m in _PROJECT_ID_RE.finditer(blob):
                out.append(JobMatch(project_id=m.group(0),
                                    loss_code=m.group(2)))
            if out:
                _log(f"row parsing failed; regex fallback found {len(out)} ID(s)")
        except Exception:
            pass

    if not out:
        # Dump the dialog HTML so we can see what markup WC2.0 actually
        # uses — next iteration's parser anchors on that.
        try:
            html = dialog.evaluate("el => el.outerHTML") if dialog else ""
            path = paths.data("workcenter_debug_modal.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write(html or "<!-- no dialog captured -->")
            _log(f"saved dialog HTML → {path}  (share to fix the parser)")
        except Exception as ex:
            _log(f"dialog HTML dump failed: {ex}")
        _dump_screenshot(page, "modal_zero_rows")

    return out


def search_jobs(query: str, ems_only: bool = True,
                 include_unknown: bool = True) -> List[JobMatch]:
    """Type `query` into the Workcenter search bar and return parsed
    matches. Caller must have already confirmed login via
    `ensure_logged_in()` — we don't re-auth here so a stale session
    surfaces as a clear error rather than a silent re-login.

    Args:
        ems_only: drop Contents/Recon jobs (loss codes in
            NON_EMS_LOSS_CODES). Default True since the audit only ever
            cares about EMS work.
        include_unknown: when ems_only=True, keep loss codes we don't
            recognize yet so a brand-new SERVPRO code doesn't make jobs
            silently disappear. The CLI annotates these as "(unknown)".
    """
    if not query or not query.strip():
        return []
    with _lock:
        page = _ensure_started()
        if not _is_logged_in(page, timeout_ms=2000):
            raise RuntimeError(
                "Workcenter session is not authenticated — "
                "call ensure_logged_in() first.")
        _log(f"search_jobs({query!r})")
        inp = _find_search_input(page)
        # Clear first — search inputs in WC2.0 keep the previous value.
        inp.click()
        page.keyboard.press("Control+A")
        page.keyboard.press("Delete")
        inp.type(query.strip(), delay=20)
        _log("typed query, submitting")
        if not _submit_search(page):
            _log("no results modal — aborting")
            return []
        results = _parse_results_table(page)
        _log(f"parsed {len(results)} row(s) from modal")
        # Close the modal so the next search starts clean. Pressing Esc
        # is more reliable than guessing the close button's selector.
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        if ems_only:
            results = [
                r for r in results
                if r.category == "ems"
                or (include_unknown and r.category == "unknown")
            ]
        return results


# ── Stubs for Phase 2 (forms + attachments download) ──────────────────────────

# Required forms we always want regardless of carrier. Match by exact
# form-number prefix — '28000' is NOT the same as '28000-CA' (the CA
# variant), and the audit's regex-based name matching can't tell them
# apart. Carrier-specific variants gate on the job's carrier below.
REQUIRED_FORM_NUMBERS = frozenset({
    "28000",  # Auth to Perform Services and Direction of Payment
    "28001",  # Authorization to Perform Services
    "28501",  # Customer Information Form
    "28509",  # Customer Equipment Responsibility
    "28531",  # Cert of Satisfaction
})

# Map a carrier-name fragment (lowercase substring) → set of form-number
# suffixes to additionally allow. Today only the California variant is
# observed; extend cautiously when new carrier suffixes appear.
_CARRIER_FORM_SUFFIXES = {
    "california": {"CA"},
    "farmers":    {"CA"},   # most Farmers jobs at this franchise are CA
    "state farm": {"CA"},
}


def _form_number_from_text(text):
    """Pull (number, suffix) out of a Workcenter form-row label like
    '28000 - Auth to Perform' or '28501-CA - California CIF — Water'.
    Returns (None, None) if the row doesn't start with a form number."""
    m = re.match(r'^\s*(\d{4,6})(?:-([A-Z]{1,4}))?\s*[-–]', text or "")
    if not m:
        return None, None
    return m.group(1), (m.group(2) or "")


def _allow_form(num, suffix, carrier):
    """Decide whether a given form (number + optional carrier suffix)
    should be downloaded."""
    if num not in REQUIRED_FORM_NUMBERS:
        return False
    if not suffix:
        return True               # plain form, always allow
    if not carrier:
        return False              # variant suffix but no carrier known
    cl = carrier.lower()
    for kw, allowed in _CARRIER_FORM_SUFFIXES.items():
        if kw in cl and suffix in allowed:
            return True
    return False


def jobmatch_from_url(legacy_url: str, name: str = "",
                       project_id: str = "") -> JobMatch:
    """Build a JobMatch directly from a legacy project URL — bypass the
    global search entirely. Useful when search is unreliable or when
    we've already discovered the URL (e.g., from a prior session)."""
    region_guid, job_guid = _extract_guids(legacy_url)
    if not (region_guid and job_guid):
        raise RuntimeError(
            f"URL {legacy_url!r} doesn't contain regionGuid + jobGuid.")
    # Loss code parsed from project_id when available.
    loss_code = ""
    if project_id:
        m = _PROJECT_ID_RE.search(project_id)
        if m:
            loss_code = m.group(2)
    return JobMatch(
        project_id=project_id, name=name, loss_code=loss_code,
        region_guid=region_guid, job_guid=job_guid,
        legacy_url=_build_legacy_url(region_guid, job_guid))


def _resolve_to_jobmatch(target, project_id: Optional[str] = None) -> JobMatch:
    """Resolve `target` to a fully-populated JobMatch with a legacy_url.

    target can be:
      - A JobMatch (passed through after a legacy_url sanity check).
      - An insured-name string ("Antonio Garcia") — searched globally
        and the result is filtered by `project_id` if provided.

    Workcenter's global search bar searches NAMES + CONTACTS only —
    Project IDs aren't indexed there, and Job Results can be empty
    for names that exist as Contacts only. When search is unreliable,
    callers can build a JobMatch directly via `jobmatch_from_url(...)`
    and pass that instead of a string.
    """
    if isinstance(target, JobMatch):
        if not target.legacy_url:
            raise RuntimeError(
                f"JobMatch for {target.project_id} has no "
                "legacy_url — re-run search to populate the GUIDs.")
        return target

    query = str(target).strip()
    if not query:
        raise RuntimeError("Empty Workcenter lookup target.")

    # Reject Project-ID-shaped queries with a helpful error rather than
    # an empty result. Workcenter's global search only matches names/
    # contacts; a "2604-202129WTR" query always returns no results.
    if _PROJECT_ID_RE.fullmatch(query.upper()):
        raise RuntimeError(
            f"{query!r} looks like a Project ID, but Workcenter's global "
            "search only indexes names/contacts. Pass the insured name "
            "instead (use --project= to disambiguate when there are "
            "multiple).")

    matches = search_jobs(query, ems_only=False)
    if not matches:
        raise RuntimeError(
            f"No Workcenter results for {query!r}.")

    # Disambiguate via project_id when the caller knows it (and the
    # name returned multiple shells — common when a Contents and an
    # EMS shell share an insured name).
    if project_id:
        pid = project_id.strip().upper()
        narrowed = [m for m in matches if m.project_id.upper() == pid]
        if not narrowed:
            ids = ", ".join(m.project_id for m in matches)
            raise RuntimeError(
                f"None of the matches for {query!r} have project_id "
                f"{project_id!r}. Got: {ids}")
        target_match = narrowed[0]
    elif len(matches) > 1:
        ids = ", ".join(f"{m.project_id} ({m.loss_code})" for m in matches)
        raise RuntimeError(
            f"{len(matches)} matches for {query!r}; pass --project=<ID> "
            f"to pick one. Got: {ids}")
    else:
        target_match = matches[0]

    if not target_match.legacy_url:
        raise RuntimeError(
            f"Match for {query!r} had no regionGuid/jobGuid in the "
            "title-link href.")
    return target_match


def _wait_through_sso(page, timeout_seconds: int = 600) -> bool:
    """The legacy workcenter-rm subdomain uses a separate SSO via
    idsrv.servpronet.com (with 2FA on most accounts). The first time
    we hit it Chromium gets bounced through that login — wait for the
    user to complete it, then the profile carries the cookies for days.

    Returns True once the URL leaves idsrv.servpronet.com.
    """
    import time
    deadline = time.time() + timeout_seconds
    warned = False
    while time.time() < deadline:
        try:
            url = (page.url or "").lower()
        except Exception:
            url = ""
        if "idsrv.servpronet.com" not in url:
            return True
        if not warned:
            _log("SSO challenge detected — complete login + 2FA in the "
                 "Chromium window. (One-time per profile.)")
            warned = True
        time.sleep(1)
    return False


def _navigate_to_project(jm: JobMatch):
    """Navigate the cached page to a project's legacy detail URL and
    wait for the page chrome to render. Detects + waits through the
    legacy SSO+2FA challenge that fires on first navigation."""
    page = _ensure_started()
    _log(f"navigating to project page → {jm.legacy_url}")
    page.goto(jm.legacy_url, wait_until="domcontentloaded", timeout=30000)
    # If the legacy app bounced us to idsrv (SSO), wait for the user
    # to complete that login. Without this gate, we'd race against
    # whatever was on the SSO page and time out looking for project
    # fields that never appear.
    if not _wait_through_sso(page):
        raise RuntimeError(
            "Legacy SSO/2FA login timed out. Complete it in the "
            "Chromium window and re-run the command — the profile "
            "will remember it next time.")
    # The legacy app redirects through several intermediate URLs after
    # SSO; wait for domcontentloaded once more before probing fields.
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass
    # Wait for ANY tab marker we know lives on the project page so we
    # don't try to read fields before Angular bootstraps.
    for sel in ('text="Detail"', 'text="DBMX Docs/Pics"',
                'text="Project Snapshot"'):
        try:
            page.wait_for_selector(sel, state="visible", timeout=8000)
            return page
        except Exception:
            continue
    return page


def fetch_claim_number(target, project_id: Optional[str] = None) -> str:
    """Open the project page and read the Claim Number field from the
    Detail tab's General section. Returns "" when the field is empty
    (which is most jobs at intake stage).

    target is the insured name OR a JobMatch from a prior search;
    project_id disambiguates when multiple shells share that name.
    """
    jm = _resolve_to_jobmatch(target, project_id=project_id)
    with _lock:
        page = _navigate_to_project(jm)
        # The Detail tab is usually the default landing tab. If a
        # different tab is active, click Detail first.
        try:
            page.get_by_text("Detail", exact=True).first.click(timeout=2000)
        except Exception:
            pass
        try:
            loc = page.get_by_label("Claim Number", exact=False)
            loc.first.wait_for(state="visible", timeout=8000)
            return (loc.first.input_value() or "").strip()
        except Exception as ex:
            _log(f"claim-number field not found: {ex}")
            _dump_screenshot(page, "no_claim_number")
            return ""


# ── Downloads ────────────────────────────────────────────────────────────────

def _open_dbmx_subtab(page, subtab_name: str):
    """Click DBMX Docs/Pics → <subtab>.  subtab_name ∈ {'Forms', 'Attachments'}"""
    try:
        page.get_by_text("DBMX Docs/Pics", exact=True).first.click(timeout=4000)
        _log("opened DBMX Docs/Pics tab")
    except Exception:
        _log("DBMX Docs/Pics tab not found — already there?")
    try:
        # The left rail in DBMX Docs/Pics has Forms / Miscellaneous Documents
        # / Attachments. Click the requested subtab.
        page.get_by_text(subtab_name, exact=True).first.click(timeout=4000)
        _log(f"opened {subtab_name} subtab")
    except Exception as ex:
        _log(f"{subtab_name} subtab click failed: {ex}")
    # Brief settle so the table's <tr> rows render
    try:
        page.wait_for_selector('table tr, [role="row"]',
                                state="visible", timeout=8000)
    except Exception:
        pass


def _row_text(row):
    try:
        return (row.inner_text() or "").strip()
    except Exception:
        return ""


def _row_uploaded(row) -> bool:
    """Best-effort read of a row's Uploaded? checkbox. The Forms table
    layout per the user's screenshot is:
        [row-select cb]  [name]  [Included? cb]  [Uploaded? cb]  [Import] [Display]
    so the Uploaded? checkbox is the LAST checkbox in the row.
    """
    boxes = row.query_selector_all('input[type="checkbox"]')
    if len(boxes) < 2:
        return False
    last = boxes[-1]
    try:
        return last.is_checked()
    except Exception:
        return False


def _check_row_select(row) -> bool:
    """Tick the leftmost checkbox in a row (the row-select). Returns
    True if successful."""
    boxes = row.query_selector_all('input[type="checkbox"]')
    if not boxes:
        return False
    try:
        boxes[0].check()
        return True
    except Exception:
        return False


def _click_download_and_save(page, dest_dir: str) -> List[str]:
    """Click the table's top-right Download button and capture the file
    Playwright sees coming back. Returns list of saved paths."""
    saved = []
    try:
        with page.expect_download(timeout=45000) as dl_info:
            # Multiple buttons may say 'Download'; the toolbar one is
            # the only visible one near the table header.
            page.get_by_role("button", name="Download").first.click()
        dl = dl_info.value
        out = os.path.join(dest_dir, dl.suggested_filename)
        dl.save_as(out)
        saved.append(out)
        _log(f"saved download → {out}")
    except Exception as ex:
        _log(f"download capture failed: {ex}")
        _dump_screenshot(page, "download_failed")
    return saved


def download_forms(target, job_root: str,
                    carrier: Optional[str] = None,
                    project_id: Optional[str] = None) -> List[str]:
    """Download Required forms from Workcenter into
    `<job_root>/EMS/DOCS/`. Filters by form NUMBER (not name) so the
    California '28000-CA' variant doesn't collide with the plain
    '28000', then by Uploaded?=true so we only pull what's actually
    available.

    target: insured name string or JobMatch.
    project_id: optional disambiguator when the name has multiple shells.
    """
    jm = _resolve_to_jobmatch(target, project_id=project_id)
    dest_dir = os.path.join(job_root, "EMS", "DOCS")
    os.makedirs(dest_dir, exist_ok=True)
    _log(f"download_forms → {dest_dir}  (carrier={carrier!r})")

    with _lock:
        page = _navigate_to_project(jm)
        _open_dbmx_subtab(page, "Forms")
        rows = page.query_selector_all('tr[role="row"], tr')
        matched = 0
        for row in rows:
            text = _row_text(row)
            num, suffix = _form_number_from_text(text)
            if not num:
                continue
            if not _allow_form(num, suffix, carrier):
                continue
            if not _row_uploaded(row):
                _log(f"skip {num}{('-' + suffix) if suffix else ''} (not uploaded)")
                continue
            if _check_row_select(row):
                matched += 1
                _log(f"selected form {num}{('-' + suffix) if suffix else ''}")
        if matched == 0:
            _log("no forms matched the allowlist + Uploaded?=true")
            return []
        return _click_download_and_save(page, dest_dir)


def download_attachments(target, job_root: str,
                          project_id: Optional[str] = None) -> List[str]:
    """Download attachments (initial photos etc.) from Workcenter into
    `<job_root>/EMS/PICS/`. No allowlist — any row with Uploaded?=true
    is included, since attachments are user-named (Cause of Loss,
    Front of Structure, etc.) without a stable form-number scheme.

    target: insured name string or JobMatch.
    project_id: optional disambiguator when the name has multiple shells.
    """
    jm = _resolve_to_jobmatch(target, project_id=project_id)
    dest_dir = os.path.join(job_root, "EMS", "PICS")
    os.makedirs(dest_dir, exist_ok=True)
    _log(f"download_attachments → {dest_dir}")

    with _lock:
        page = _navigate_to_project(jm)
        _open_dbmx_subtab(page, "Attachments")
        rows = page.query_selector_all('tr[role="row"], tr')
        matched = 0
        for row in rows:
            text = _row_text(row)
            if not text:
                continue
            if not _row_uploaded(row):
                continue
            if _check_row_select(row):
                matched += 1
                _log(f"selected attachment: {text[:60]}")
        if matched == 0:
            _log("no attachments are Uploaded? = true on this job")
            return []
        return _click_download_and_save(page, dest_dir)


# ── CLI smoke test ────────────────────────────────────────────────────────────

def _cli(argv):
    global _DEBUG
    # Pull --debug out of argv before command dispatch so subcommands
    # don't see it. With --debug we print step-by-step progress and dump
    # a screenshot on selector failures.
    if "--debug" in argv:
        _DEBUG = True
        argv = [a for a in argv if a != "--debug"]
    if len(argv) < 2:
        print(
            "Usage:\n"
            "  python workcenter_client.py login\n"
            "  python workcenter_client.py search <name> [--all]\n"
            "  python workcenter_client.py claim <name> [--project=<ID>]\n"
            "  python workcenter_client.py forms <name> <job_root> [--project=<ID>] [--carrier=<name>]\n"
            "  python workcenter_client.py attachments <name> <job_root> [--project=<ID>]\n"
            "\n"
            "Note: lookups are by INSURED NAME, not Project ID. Workcenter's\n"
            "global search bar doesn't index Project IDs. Use --project= to\n"
            "disambiguate when a name has both a Contents and an EMS shell.\n"
            "\n"
            "First run opens Chromium for interactive login; the profile\n"
            f"persists at:\n  {_PROFILE_DIR}\n"
            "\n"
            "Add --debug for step-by-step progress + screenshots to\n"
            "%APPDATA%\\Linguar Hub\\workcenter_debug_*.png on misses.",
            file=sys.stderr)
        return 2
    cmd = argv[1].lower()
    if cmd == "login":
        ok = ensure_logged_in()
        print("logged in" if ok else "TIMEOUT — login window left open")
        return 0 if ok else 1
    if cmd == "search":
        query = " ".join(argv[2:]) or input("Search Workcenter for: ").strip()
        if not ensure_logged_in():
            print("Login required (and timed out).", file=sys.stderr)
            return 1
        # Default CLI shows EMS-only results + unknown codes; pass
        # --all to include Contents/Recon for debugging.
        ems_only = "--all" not in argv
        results = search_jobs(query, ems_only=ems_only)
        if not results:
            print(f"No matches for: {query!r}")
            return 0
        # User-requested layout: job type + name only (Project ID kept
        # because it's the disambiguator when two jobs share a name).
        print(f"{len(results)} match(es) for {query!r}:")
        for r in results:
            tag = "" if r.category == "ems" else f"  [{r.category}]"
            print(f"  {r.loss_code:5}  {r.name:35}  {r.project_id}{tag}")
        return 0
    # Pull --url out once — it short-circuits the search step for any
    # of the Phase 2 commands. Useful when global search is flaky and
    # the caller already has the project URL from a prior session.
    url_arg = next((a.split("=", 1)[1] for a in argv
                     if a.startswith("--url=")), None)

    def _resolve_target(positional, project_id):
        """Build the lookup target (string for search, or JobMatch when
        --url= was given). Keeps the three Phase 2 commands DRY."""
        if url_arg:
            name = positional[0] if positional else ""
            return jobmatch_from_url(url_arg, name=name,
                                      project_id=project_id or "")
        if not positional:
            raise SystemExit("Pass <name> or --url=<legacy_url>.")
        return positional[0]

    if cmd == "claim":
        positional = [a for a in argv[2:] if not a.startswith("--")]
        if not positional and not url_arg:
            print("Usage: claim <name> [--project=<ID>]  OR  "
                  "claim --url=<legacy_url>", file=sys.stderr)
            return 2
        project_id = next((a.split("=", 1)[1] for a in argv
                            if a.startswith("--project=")), None)
        if not ensure_logged_in():
            print("Login required.", file=sys.stderr)
            return 1
        target = _resolve_target(positional, project_id)
        val = fetch_claim_number(target, project_id=project_id)
        label = (positional[0] if positional else url_arg) + \
                (f" ({project_id})" if project_id else "")
        print(f"Claim Number for {label}: {val!r}")
        return 0
    if cmd in ("forms", "attachments"):
        positional = [a for a in argv[2:] if not a.startswith("--")]
        # With --url= the CLI needs only <job_root>; without it,
        # it needs <name> <job_root>.
        need = 1 if url_arg else 2
        if len(positional) < need:
            print(f"Usage: {cmd} <name> <job_root> [--project=<ID>]"
                  + (" [--carrier=<name>]" if cmd == "forms" else "")
                  + f"\n   or: {cmd} <job_root> --url=<legacy_url>",
                  file=sys.stderr)
            return 2
        if url_arg:
            job_root = positional[0]
        else:
            job_root = positional[1]
        project_id = next((a.split("=", 1)[1] for a in argv
                            if a.startswith("--project=")), None)
        carrier = next((a.split("=", 1)[1] for a in argv
                        if a.startswith("--carrier=")), None)
        if not ensure_logged_in():
            print("Login required.", file=sys.stderr)
            return 1
        target = _resolve_target(positional, project_id)
        if cmd == "forms":
            saved = download_forms(target, job_root, carrier=carrier,
                                    project_id=project_id)
        else:
            saved = download_attachments(target, job_root,
                                          project_id=project_id)
        print(f"Saved {len(saved)} file(s):")
        for p in saved:
            print(f"  {p}")
        return 0
    print(f"Unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    # Force unbuffered + UTF-8 stdio — some terminals (Git Bash, certain
    # VSCode configs) buffer Python output until the process exits,
    # which makes the script appear to "do nothing" while it's running.
    # UTF-8 is required because our log messages contain → and … which
    # Windows' default cp1252 codec can't encode (UnicodeEncodeError).
    try:
        sys.stdout.reconfigure(line_buffering=True, encoding="utf-8")
        sys.stderr.reconfigure(line_buffering=True, encoding="utf-8")
    except Exception:
        pass
    try:
        rc = _cli(sys.argv)
    except SystemExit:
        raise
    except BaseException as ex:
        import traceback
        print("\n[workcenter] UNCAUGHT EXCEPTION:", flush=True)
        traceback.print_exc()
        rc = 99
    sys.exit(rc)
