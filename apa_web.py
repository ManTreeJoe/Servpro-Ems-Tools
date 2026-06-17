"""APA Monitor — Pywebview panel.

~21 sections (built-in lifecycle slots + per-estimator slices), each
a column of items, plus .docx round-tripping for the daily APA doc.

Full feature set: parse + render today's APA doc as a horizontal
kanban; date navigator; item add/remove/move via drag-drop; status
dropdowns; section reorder; save back to .docx; Teams messaging
per-item / per-estimator / send-all; Trello pin/unpin; extended-
tracker badges; franchise color chips; escalation roles; EOD email
copy.

Launch:
    python apa_web.py
    # or via launcher:
    python launcher.py --tool apa_web
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
import webbrowser

import webview

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# apa_logic holds the UI-free section model, doc parse/write, the
# section-order cache + dropdown/Teams helpers — everything this panel
# needs. Importing it (instead of the Tk apa_monitor_gui) keeps tkinter
# out of the web process.
import apa_logic as apa


ASSETS_DIR = os.path.join(_HERE, "apa_web_assets")
INDEX_HTML = os.path.join(ASSETS_DIR, "index.html")


# How many calendar days back from today to surface in the date
# picker. APA docs only exist for working days, so a 21-day window
# typically gives the user 3 weeks' worth of historical lookback.
_NAV_DATES_WINDOW = 21


def _items_for_section(raw_items, franchise_tags=None,
                         ext_counts=None, notes_for_section=None):
    """Normalize the (text, highlighted) tuples that parse_existing_doc
    returns into JSON-friendly dicts. Skips blank items so the
    frontend doesn't have to filter them out at render time.

    `franchise_tags`: optional pre-loaded {client_key: franchise} dict.
    When provided, each item is decorated with its franchise label so
    the frontend can render the tag chip without a per-item API call.
    """
    if franchise_tags is None:
        franchise_tags = {}
    if ext_counts is None:
        ext_counts = {}
    if notes_for_section is None:
        notes_for_section = {}
    out = []
    for it in raw_items or []:
        if isinstance(it, tuple) and len(it) == 2:
            text, highlighted = it
        elif isinstance(it, dict):
            text = it.get("text", "")
            highlighted = (it.get("status", "").lower()
                            in {"upload", "missing", "service call", "tba"})
        else:
            text, highlighted = str(it), False
        text = (text or "").strip()
        if not text:
            continue
        # "-extended" suffix renders in red in the .docx; surface the
        # extended flag separately so the JS side can render the same
        # visual cue without re-parsing the suffix.
        extended = text.lower().endswith("-extended")
        # Lookup franchise tag using the same canonicalization Tk uses
        # so per-item chips stay in sync with the franchise filter.
        franchise = ""
        try:
            bare = apa.strip_status_from_text(text or "")
            key = apa._franchise_key(bare) if bare else ""
            if key:
                franchise = franchise_tags.get(key) or ""
        except Exception:
            franchise = ""
        # Per-item extras: 🔁 extended count + 📝 note presence —
        # both keyed by canonicalized client text so they survive
        # status/sub suffix changes.
        ext_count = 0
        has_note = False
        try:
            bare = apa.strip_status_from_text(text or "")
            key = apa._franchise_key(bare) if bare else ""
            if key and key in ext_counts:
                ext_count = int(ext_counts[key] or 0)
            if bare and bare in notes_for_section:
                has_note = bool(notes_for_section[bare])
        except Exception:
            pass
        out.append({
            "text":        text,
            "highlighted": bool(highlighted),
            "extended":    extended,
            "franchise":   franchise,
            "ext_count":   ext_count,
            "has_note":    has_note,
        })
    return out


def _doc_payload_for(date_obj):
    """Read the APA doc for `date_obj` and return a JSON-shaped
    payload: section_order + items per section + metadata."""
    path = apa.doc_path_for_today(date_obj)
    exists = os.path.isfile(path)
    parsed = apa.parse_existing_doc(path) if exists else {}
    # Pre-load the franchise-tags map once so we don't re-load per
    # item — keeps the payload build O(items) instead of O(items × IO).
    try:
        import persistence as _per
        franchise_tags = _per.get_franchise_tags() or {}
    except Exception:
        franchise_tags = {}
    # Bulk-load extended counts + notes once per payload — render-side
    # lookup is O(1) instead of O(items × IO).
    try:
        import persistence as _per
        ext_counts = _per.get_apa_extended_history() or {}
    except Exception:
        ext_counts = {}
    try:
        import persistence as _per
        all_notes_raw = _per.get("apa_message_notes") or {}
    except Exception:
        all_notes_raw = {}
    sections = []
    for name in apa.SECTION_ORDER:
        # `apa_message_notes` is keyed by client → {section: text}; pre-
        # invert per-section once so item lookup is a single dict get.
        notes_for_section = {}
        try:
            for client_key, by_section in (all_notes_raw or {}).items():
                if isinstance(by_section, dict):
                    v = by_section.get(name)
                    if v: notes_for_section[client_key] = v
        except Exception:
            notes_for_section = {}
        items = _items_for_section(parsed.get(name, []), franchise_tags,
                                     ext_counts=ext_counts,
                                     notes_for_section=notes_for_section)
        sections.append({
            "name":        name,
            "is_builtin":  name in apa._BUILTIN_SET,
            "is_estimator": name not in apa._BUILTIN_SET,
            "items":       items,
            "count":       len(items),
        })
    return {
        "date_iso":  date_obj.strftime("%Y-%m-%d"),
        "date_label": date_obj.strftime("%A, %B %d, %Y"),
        "doc_path":  path,
        "doc_exists": exists,
        "sections":  sections,
        "total_items": sum(s["count"] for s in sections),
    }


# ── Teams message assembly (mirrors apa_monitor_gui) ─────────────────
def _wrapped_sections_for(date_obj):
    """Parse the APA doc for `date_obj` and wrap each (text, highlighted)
    tuple into {text, sub, status, highlighted} — the same shape the Tk
    panel keeps in self.sections. Without wrapping, audit-section items
    can't be attributed to the estimator stored in their `-SUB` suffix."""
    path = apa.doc_path_for_today(date_obj)
    parsed = apa.parse_existing_doc(path) if os.path.isfile(path) else {}
    return {name: [apa.wrap_item(t, h) for (t, h) in items]
            for name, items in parsed.items()}


def _outstanding_for(estimator, sections):
    """Items in this estimator's own section PLUS Audit Rejection / Audit
    Dispute items where they're the selected sub, minus anything marked
    'uploaded'. Returns [(item, section), ...]. Mirrors
    apa_monitor_gui._outstanding_for so disputes/rejections ride along in
    an estimator's combined Teams message instead of silently dropping."""
    out = []
    for it in sections.get(estimator, []):
        if (it.get("text", "").strip()
                and (it.get("status") or "").lower() != "uploaded"):
            out.append((it, estimator))
    for sec in apa.AUDIT_SECTIONS:
        for it in sections.get(sec, []):
            if ((it.get("sub") or "").strip().upper() == estimator.upper()
                    and it.get("text", "").strip()
                    and (it.get("status") or "").lower() != "uploaded"):
                out.append((it, sec))
    return out


def _note_for(item, section):
    """Persisted Teams-message note for an Audit row (keyed by base text),
    or "" for non-audit rows. Mirrors apa_monitor_gui._note_for."""
    if section not in apa.AUDIT_SECTIONS:
        return ""
    base = apa.strip_to_base(item.get("text", "") or "")
    if not base:
        return ""
    try:
        import persistence as _per
        return _per.get_apa_message_note(base, section) or ""
    except Exception:
        return ""


def _build_combined_message(estimator, items_with_sections):
    """One combined message listing an estimator's outstanding jobs.
    Upload items keep the legacy phrasing; audit items get a
    Rejection/Dispute label and any persisted note as indented body text.
    Mirrors apa_monitor_gui._build_combined_message verbatim."""
    first = apa.estimator_first_name(estimator)
    if len(items_with_sections) == 1:
        item, sec = items_with_sections[0]
        client = apa.strip_status_from_text(item.get("text", ""))
        if sec in apa.AUDIT_SECTIONS:
            msg = (f"Hey {first}, can you take a look at this "
                   f"{sec.lower()}: {client}?")
            note = _note_for(item, sec)
            lines = [ln for ln in note.splitlines() if ln.strip()]
            if lines:
                msg += "\n  " + "\n  ".join(lines)
            return msg
        return f"Hey {first}, will you be uploading this job today: {client}?"

    upload_items = [(i, s) for i, s in items_with_sections
                    if s not in apa.AUDIT_SECTIONS]
    audit_items = [(i, s) for i, s in items_with_sections
                   if s in apa.AUDIT_SECTIONS]
    parts = [f"Hey {first},"]
    if upload_items:
        parts.append("will you be uploading these jobs today:")
        for i, _ in upload_items:
            parts.append("  • " + apa.strip_status_from_text(i.get("text", "")))
    if audit_items:
        if upload_items:
            parts.append("")
        parts.append("can you also take a look at these audit items:")
        for i, sec in audit_items:
            client = apa.strip_status_from_text(i.get("text", ""))
            label = ("Rejection" if sec == apa.SEC_AUDIT_REJECTION
                     else "Dispute")
            parts.append(f"  • {client}  ({label})")
            note = _note_for(i, sec)
            if note:
                for nl in note.splitlines():
                    if nl.strip():
                        parts.append("      " + nl)
    return "\n".join(parts)


def _iter_recent_dates():
    """Last `_NAV_DATES_WINDOW` weekdays (Mon-Fri), newest first.
    Skips weekends because APA docs don't exist for them."""
    today = _dt.date.today()
    out = []
    d = today
    while len(out) < _NAV_DATES_WINDOW:
        if d.weekday() < 5:  # Mon-Fri only
            out.append(d)
        d -= _dt.timedelta(days=1)
    return out


class Api:
    """Methods exposed to JS via `pywebview.api`."""

    def __init__(self):
        self._window = None

    def attach(self, window):
        self._window = window

    # ── Reads ────────────────────────────────────────────────────────
    def today_doc(self) -> dict:
        """Today's APA doc, full payload + section structure."""
        return _doc_payload_for(_dt.date.today())

    def doc_for_date(self, date_iso: str) -> dict:
        """Specific-date payload (YYYY-MM-DD)."""
        try:
            d = _dt.date.fromisoformat(date_iso)
        except Exception:
            return _doc_payload_for(_dt.date.today())
        return _doc_payload_for(d)

    def clear_all_items(self, date_iso: str = "") -> dict:
        """Empty every section of the doc (keeping the section headers /
        categories) and save. This is the morning 'clear yesterday's
        items, keep the categories' step from the cheat sheet. Returns a
        fresh payload so the frontend re-renders empty."""
        try:
            d = _dt.date.fromisoformat(date_iso) if date_iso else _dt.date.today()
        except Exception:
            d = _dt.date.today()
        try:
            path = apa.doc_path_for_today(d)
            empty = {s: [] for s in apa.SECTION_ORDER}
            apa.write_doc(path, d, empty)
            return {"ok": True, "doc": _doc_payload_for(d)}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def nav_dates(self) -> list[dict]:
        """Recent working days for the date navigator. Each entry has
        the ISO date + a short label + a flag for whether a doc
        exists on disk (so the navigator can grey out empty days)."""
        out = []
        for d in _iter_recent_dates():
            path = apa.doc_path_for_today(d)
            out.append({
                "iso":    d.strftime("%Y-%m-%d"),
                "short":  d.strftime("%a %m/%d"),
                "label":  d.strftime("%A %B %-d") if os.name != "nt"
                          else d.strftime("%A %#m/%#d"),
                "exists": os.path.isfile(path),
                "is_today": d == _dt.date.today(),
            })
        return out

    def section_order(self) -> list[str]:
        """Current persisted section order — for re-ordering UI later."""
        return list(apa.SECTION_ORDER)

    def section_list(self) -> list:
        """Every APA section name (in stored display order). Used by
        the add-to-APA confirmation dialog to populate the section
        dropdown."""
        try:
            return list(apa.SECTION_ORDER)
        except Exception:
            return []

    def add_dialog_sections(self) -> list:
        """Curated section list for the Add-to-APA dialog — matches
        the Tk `_open_add_to_apa_dialog` `sec_choices` exactly.

        Skips PENDING REVIEW because that section is estimator-routed
        (not user-typed), and includes the estimator section list so
        the user can drop a card straight into JUAN / KIM / ZAC etc.
        when the lane doesn't auto-resolve.

        Each entry: {name, has_subs} so the dialog can hide the Sub
        dropdown when subs are not applicable (estimator + Estimating-*
        sections). Mirrors `apa._sub_options_for_section is not None`.
        """
        try:
            curated = [
                apa.SEC_FINAL_UPLOADS,
                apa.SEC_EST_MISSING, apa.SEC_EST_SERVICE_CALL,
                apa.SEC_EST_TBA, apa.SEC_EST_SNAPSHOT,
            ]
            curated.extend(list(apa.ESTIMATORS_ORDERED or []))
            curated.extend([
                apa.SEC_INITIAL_UPLOADS, apa.SEC_DAILY_UPLOADS,
                apa.SEC_AUDIT_REJECTION, apa.SEC_AUDIT_DISPUTE,
            ])
            # Drop dupes preserving order
            seen, out = set(), []
            for s in curated:
                if s and s not in seen:
                    seen.add(s); out.append(s)
            # Decorate with has_subs flag — drives whether the Sub
            # dropdown is hidden in the dialog.
            decorated = []
            for name in out:
                try:
                    subs = apa._sub_options_for_section(name)
                    has_subs = subs is not None
                except Exception:
                    has_subs = True
                decorated.append({"name": name, "has_subs": bool(has_subs)})
            return decorated
        except Exception:
            return [{"name": s, "has_subs": True}
                    for s in self.section_list()]

    def status_options(self, section_name: str) -> dict:
        """Status + sub-category dropdown contents for the given
        section. Matches the Tk version's per-section dropdowns
        exactly so the same suffix conventions round-trip through
        the .docx writer."""
        try:
            statuses = apa._status_options_for_section(section_name) or []
        except Exception:
            statuses = list(apa.STATUS_OPTIONS)
        try:
            subs = apa._sub_options_for_section(section_name)
        except Exception:
            subs = None
        return {
            "statuses":   list(statuses or []),
            "subs":       list(subs) if subs is not None else None,
            "highlight":  sorted(apa.HIGHLIGHT_STATUSES),
        }

    def strip_status(self, text: str) -> dict:
        """Strip any -status / -sub suffix from `text`, returning the
        bare text + the parsed status + sub. Lets the popover prefill
        the dropdowns when editing an existing row."""
        try:
            bare = apa.strip_status_from_text(text or "")
        except Exception:
            bare = text or ""
        return {"bare": bare, "original": text or ""}

    # ── P0: Teams messaging ─────────────────────────────────────────
    def get_estimator_email(self, estimator: str) -> str:
        """Look up the saved Teams email for an estimator. Empty
        when none stored — the JS prompts for it."""
        try:
            import persistence as _per
            return _per.get_estimator_email(estimator or "") or ""
        except Exception:
            return ""

    def set_estimator_email(self, estimator: str, email: str) -> dict:
        """Persist an estimator's Teams email for future messages."""
        if not estimator or not email:
            return {"ok": False, "error": "estimator + email required"}
        try:
            import persistence as _per
            _per.set_estimator_email(estimator, email)
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def teams_per_item(self, estimator: str, item_text: str,
                       section: str = "") -> dict:
        """Open a Teams chat about ONE item. Per the Tk
        `_send_teams_about_item` — builds the question phrasing based
        on whether the section is an audit section or upload section."""
        if not estimator:
            return {"ok": False, "error": "no estimator"}
        try:
            import persistence as _per
            email = _per.get_estimator_email(estimator) or ""
        except Exception:
            email = ""
        if not email:
            return {"ok": False, "needs_email": True,
                    "estimator": estimator}
        try:
            first = apa.estimator_first_name(estimator)
            # wrap_item peels BOTH the -status and the estimator -sub
            # suffix; plain strip_status_from_text leaves estimator subs
            # on (they aren't in SUB_OPTIONS), so an audit row would read
            # "…State Farm-KIM" without this.
            client = apa.wrap_item(item_text or "").get("text") or ""
            if section in apa.AUDIT_SECTIONS:
                msg = (f"Hey {first}, can you take a look at this "
                       f"{section.lower()}: {client}?")
            else:
                msg = (f"Hey {first}, will you be uploading this job "
                       f"today: {client}?")
            # Build-only — frontend opens an editable compose dialog.
            return {"ok": True, "email": email, "message": msg}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def teams_per_estimator(self, estimator: str) -> dict:
        """Build the combined message for one estimator (all their
        outstanding items — own section PLUS any Audit Rejection / Audit
        Dispute rows where they're the sub — in one Teams chat). Mirrors
        the Tk `_send_teams_to_estimator` flow."""
        if not estimator:
            return {"ok": False}
        try:
            import persistence as _per
            email = _per.get_estimator_email(estimator) or ""
        except Exception:
            email = ""
        if not email:
            return {"ok": False, "needs_email": True,
                    "estimator": estimator}
        try:
            sections = _wrapped_sections_for(_dt.date.today())
        except Exception:
            sections = {}
        active = _outstanding_for(estimator, sections)
        if not active:
            return {"ok": False, "error": "no outstanding items"}
        try:
            # Build-only — the frontend shows an editable compose dialog
            # (Copy + Open Teams) rather than relying on the msteams: deep
            # link's message= param, which the current Teams client
            # ignores (opens an empty chat). See teams_open_chat.
            msg = _build_combined_message(estimator, active)
            return {"ok": True, "email": email, "message": msg,
                    "count": len(active)}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def teams_collect_targets(self) -> dict:
        """Plan a send-all WITHOUT opening any Teams chats.

        Returns one entry per estimator that has outstanding items (their
        own section PLUS Audit Rejection / Audit Dispute rows where
        they're the sub), each carrying the prebuilt combined message +
        email so the JS can confirm-and-open ONE chat at a time. This is
        the web equivalent of the Tk `_send_teams_to_all` collection +
        unresolved-warning logic — the per-chat prompt now lives in JS so
        the user controls the pace and can verify each message before it
        opens (instead of the old loop that fired every chat at once)."""
        try:
            sections = _wrapped_sections_for(_dt.date.today())
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

        # Audit-section subs that aren't standard estimators (first-seen
        # order) so a dispute assigned to someone outside ESTIMATORS_ORDERED
        # still gets swept in.
        covered = {e.upper() for e in apa.ESTIMATORS_ORDERED}
        extra_subs = []
        for sec in apa.AUDIT_SECTIONS:
            for it in sections.get(sec, []):
                sub = (it.get("sub") or "").strip()
                if (sub and sub.upper() not in covered
                        and it.get("text", "").strip()
                        and (it.get("status") or "").lower() != "uploaded"):
                    extra_subs.append(sub)
                    covered.add(sub.upper())

        all_ests = list(apa.ESTIMATORS_ORDERED) + extra_subs

        try:
            import persistence as _per
        except Exception:
            _per = None

        targets = []
        missing_email = []
        for est in all_ests:
            active = _outstanding_for(est, sections)
            if not active:
                continue
            email = (_per.get_estimator_email(est) if _per else "") or ""
            if email:
                try:
                    msg = _build_combined_message(est, active)
                except Exception:
                    msg = ""
                targets.append({
                    "estimator": est,
                    "first":     apa.estimator_first_name(est),
                    "email":     email,
                    "message":   msg,
                    "count":     len(active),
                })
            else:
                missing_email.append(est)

        # Audit items that can't be routed (no sub, or a sub with no email
        # saved) — surfaced so they can't silently vanish from the sweep.
        resolved_upper = ({t["estimator"].upper() for t in targets}
                          | {e.upper() for e in missing_email})
        unresolved = []
        for sec in apa.AUDIT_SECTIONS:
            for it in sections.get(sec, []):
                sub = (it.get("sub") or "").strip()
                txt = it.get("text", "").strip()
                if not txt or (it.get("status") or "").lower() == "uploaded":
                    continue
                if not sub:
                    unresolved.append(f"{txt}  [{sec}] — no estimator set")
                elif sub.upper() not in resolved_upper:
                    unresolved.append(
                        f"{txt}  [{sec}] — '{sub}' has no email saved")

        return {
            "ok":            True,
            "targets":       targets,
            "missing_email": [apa.estimator_first_name(e)
                              for e in missing_email],
            "unresolved":    unresolved[:10],
        }

    def teams_open_chat(self, email: str, message: str) -> dict:
        """Open ONE Teams chat — called by the JS confirm-between-each
        send-all loop after the user OKs the preview. Returns {ok} so the
        loop can stop on a launch failure."""
        if not email:
            return {"ok": False, "error": "no email"}
        try:
            ok = apa.open_teams_chat(email, message or "")
            return {"ok": bool(ok)}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    # ── P0: EOD email via Outlook web compose ───────────────────────
    def get_eod_recipients(self) -> list:
        try:
            import persistence as _per
            return list(_per.get_eod_recipients() or [])
        except Exception:
            return []

    def set_eod_recipients(self, emails: list) -> dict:
        if not isinstance(emails, list):
            return {"ok": False, "error": "list required"}
        try:
            import persistence as _per
            _per.set_eod_recipients([e.strip() for e in emails if e and e.strip()])
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    # ── P1: Per-item APA note dialog ────────────────────────────────
    def get_item_note(self, client_base: str, section: str) -> str:
        """Get the persisted APA note for a client+section. Notes
        get appended to Teams messages (indented body) per item."""
        try:
            import persistence as _per
            return _per.get_apa_message_note(
                client_base or "", section or "") or ""
        except Exception:
            return ""

    def set_item_note(self, client_base: str, section: str, text: str) -> dict:
        """Persist the APA note. Used by the per-item note popover."""
        if not client_base or not section:
            return {"ok": False}
        try:
            import persistence as _per
            _per.set_apa_message_note(client_base, section, text or "")
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    # ── P1: Manage estimators (roster) ──────────────────────────────
    def get_estimators(self) -> list:
        """Current estimator roster (ordered)."""
        try:
            return list(apa.ESTIMATORS_ORDERED)
        except Exception:
            return []

    def set_estimators(self, names: list) -> dict:
        """Persist a new estimator order. Saves to apa_section_order
        so the Tk panel + web both see the same roster."""
        if not isinstance(names, list):
            return {"ok": False, "error": "list required"}
        # Strip + dedupe + uppercase per Tk's normalize-on-save
        cleaned = []
        seen = set()
        for n in names:
            v = (n or "").strip().upper()
            if v and v not in seen:
                seen.add(v)
                cleaned.append(v)
        # Splice the new estimator slice into the canonical section
        # order at the same position estimators normally sit.
        try:
            import persistence as _per
            new_order = []
            placed = False
            for s in apa.SECTION_ORDER:
                if s in apa._BUILTIN_SET:
                    new_order.append(s)
                else:
                    if not placed:
                        new_order.extend(cleaned)
                        placed = True
            if not placed:
                new_order.extend(cleaned)
            _per.set_value("apa_section_order", new_order)
            apa._reload_estimators_cache()
            return {"ok": True, "count": len(cleaned)}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    # ── P1: Trello search → Add to APA ──────────────────────────────
    # ── Lane → APA section suggestion (mirrors Tk _LANE_TO_SECTION) ──
    # IMPORTANT: section values MUST match apa_monitor_gui SEC_* exactly
    # — wrong strings here would create a brand-new section with the
    # wrong title instead of routing to the existing one.
    _LANE_TO_SECTION = {
        # Estimating board — more-specific keys FIRST so substring walk
        # picks them up before bare estimator keys win.
        "add'l work":               apa.SEC_EST_MISSING,
        "additional items":         apa.SEC_EST_MISSING,
        "missing items":            apa.SEC_EST_MISSING,
        "estimating missing":       apa.SEC_EST_MISSING,
        "snapshot":                 apa.SEC_EST_SNAPSHOT,
        "estimating snapshot":      apa.SEC_EST_SNAPSHOT,
        "to be assigned":           apa.SEC_EST_TBA,
        "estimating tba":           apa.SEC_EST_TBA,
        "service call":             apa.SEC_EST_SERVICE_CALL,
        "service calls":            apa.SEC_EST_SERVICE_CALL,
        "serivce call":             apa.SEC_EST_SERVICE_CALL,
        "estimating service call":  apa.SEC_EST_SERVICE_CALL,
        "pending review":           apa.SEC_PENDING_REVIEW,
        # Estimator lanes — combo lanes default to FIRST listed name
        "juantes":   "JUAN",  "kim+esteban": "KIM",
        "samantha / al jr": "SAMANTHA",   "samantha/al jr": "SAMANTHA",
        "al jr": "AARON L",   "aaron l": "AARON L",
        "juan": "JUAN",       "aaron": "AARON",
        "johnny": "JOHNNY",   "kim": "KIM",
        "zac": "ZAC",         "esteban": "ESTEBAN",
        "victoria": "VICTORIA", "pablo": "PABLO",
        "samantha": "SAMANTHA", "recon": "RECON",
        # Job-stage lanes
        "initial inspections": apa.SEC_INITIAL_UPLOADS,
        "initial inspection":  apa.SEC_INITIAL_UPLOADS,
        "re-inspection":       apa.SEC_INITIAL_UPLOADS,
        "tbs new loss":        apa.SEC_INITIAL_UPLOADS,
        "tbs mitigation":      apa.SEC_INITIAL_UPLOADS,
        "monitor":             apa.SEC_FINAL_UPLOADS,
        "work in progress":    apa.SEC_FINAL_UPLOADS,
        "tbs contents":        apa.SEC_FINAL_UPLOADS,
        "test/clearance":      apa.SEC_FINAL_UPLOADS,
        "testing/clearance":   apa.SEC_FINAL_UPLOADS,
        "on hold":             apa.SEC_FINAL_UPLOADS,
        "pending approval":    apa.SEC_FINAL_UPLOADS,
        "pending ins":         apa.SEC_FINAL_UPLOADS,
        "selfpay":             apa.SEC_FINAL_UPLOADS,
        "self-pay":            apa.SEC_FINAL_UPLOADS,
        "self pay":            apa.SEC_FINAL_UPLOADS,
        "office questions":    apa.SEC_FINAL_UPLOADS,
        "audit rejection":     apa.SEC_AUDIT_REJECTION,
        "audit dispute":       apa.SEC_AUDIT_DISPUTE,
    }
    _LANE_TO_SUB = {
        "initial inspections":   "Initial Inspections/Re-Inspections",
        "re-inspection":         "Initial Inspections/Re-Inspections",
        "tbs new loss":          "TBS New Loss/Re-Inspection",
        "tbs mitigation":        "TBS Mitigation",
        "tbs contents":          "TBS Contents",
        "testing/clearance":     "Testing/Clearance",
        "test/clearance":        "Testing/Clearance",
        "office questions":      "Office Questions",
        "pending approval":      "PENDING APROVAL/INS/SELFPAY",
        "pending ins":           "PENDING APROVAL/INS/SELFPAY",
        "selfpay":               "PENDING APROVAL/INS/SELFPAY",
        "self-pay":              "PENDING APROVAL/INS/SELFPAY",
        "self pay":              "PENDING APROVAL/INS/SELFPAY",
        "property management":   "Pending Approvals/Property Management",
        "pending approvals":     "Pending Approvals/Property Management",
        "add'l work":            "Add'l Work/Missing Items",
        "additional items":      "Add'l Work/Missing Items",
        "missing items":         "Add'l Work/Missing Items",
        "on hold":               "On Hold",
        "work in progress":      "Work in progress",
        "monitor":               "Monitor",
        "upcoming":              "Upcoming/Pending",
        "initial":               "Initial",
    }

    def _suggest_section_for_lane(self, lane_name: str) -> str:
        ln = (lane_name or "").strip().lower()
        if not ln: return ""
        m = self._LANE_TO_SECTION
        if ln in m: return m[ln]
        for k, v in m.items():
            if k in ln: return v
        return ""

    def _suggest_sub_for_lane(self, lane_name: str, section: str = "") -> str:
        """Best-fit sub for a Trello lane. Resolution ladder:
          1. Explicit `_LANE_TO_SUB` mapping (exact lowercase + substring).
          2. **Fuzzy match against the section's actual SUB_OPTIONS**
             (token-set overlap). If the lane name is close enough to
             any canonical sub the section offers, return that sub
             instead of the raw lane string.
          3. Otherwise → fall back to the verbatim lane name. Matches
             Tk's apa_monitor_gui:2795 (`sub_var.set(lane_name)`).
        """
        ln_raw = (lane_name or "").strip()
        ln = ln_raw.lower()
        if not ln: return ""
        m = self._LANE_TO_SUB
        if ln in m: return m[ln]
        for k, v in m.items():
            if k in ln: return v

        # ── Fuzzy SUB_OPTIONS match ──────────────────────────────
        # Pull the actual subs the chosen section offers, then score
        # each against the lane by tokenized Jaccard overlap.
        # Threshold 0.5 catches obvious matches ("Testing / Clearance"
        # → "Testing/Clearance") without grabbing weak overlaps.
        try:
            subs = (apa._sub_options_for_section(section)
                    if section else None) or []
        except Exception:
            subs = []
        if subs:
            import re
            def _toks(s):
                # Drop punctuation, collapse to lowercase tokens of
                # length >= 2 so "in" / "of" don't dominate scores.
                s = re.sub(r"[^a-z0-9]+", " ", (s or "").lower())
                return set(t for t in s.split() if len(t) >= 2)
            lane_toks = _toks(ln_raw)
            if lane_toks:
                best_score, best_sub = 0.0, ""
                for sub in subs:
                    if not sub: continue
                    st = _toks(sub)
                    if not st: continue
                    union = lane_toks | st
                    inter = lane_toks & st
                    if not union: continue
                    score = len(inter) / len(union)
                    # Boost when ALL of the sub's tokens are present
                    # in the lane (e.g. lane="Pending Approval" beats
                    # "Pending Approvals/Property Management" because
                    # 'pending' and 'approval' both appear).
                    if st.issubset(lane_toks):
                        score = max(score, 0.85)
                    if score > best_score:
                        best_score, best_sub = score, sub
                if best_score >= 0.5 and best_sub:
                    return best_sub

        # No canonical mapping — return the raw lane name so the user
        # sees "sub = lane" by default.
        return ln_raw

    def suggest_apa_routing(self, card_id: str,
                              lane_hint: str = "",
                              name_hint: str = "") -> dict:
        """Look up a Trello card by ID + return the suggested APA
        routing for it: best-fit section, default sub, parsed carrier
        and claim #, franchise tag. Used by the topbar search → auto-add
        flow so picking a card lands it in the right section with the
        right shape.

        `lane_hint` + `name_hint`: passed through from the search
        result so we can still suggest section/sub even when the
        card fetch fails (rate limit, transient Trello hiccup, etc.).
        Compute the lane-driven routing FIRST so a card-desc parse
        failure doesn't strand the user on "Initial Uploads".

        ALWAYS returns ok=True so the UI never falls back to a
        hardcoded default — partial data with whatever we could
        gather beats a silent no-op.
        """
        notes = []
        name = (name_hint or "").strip()
        lane = (lane_hint or "").strip()

        # ── STEP 1: derive section/sub from the lane FIRST ─────────
        # This works without any network call, so even if get_card
        # below times out we still suggest the right section.
        section = self._suggest_section_for_lane(lane)
        sub = self._suggest_sub_for_lane(lane, section)

        # ── STEP 2: best-effort Trello fetch for desc + lane fallback ─
        card = {}
        carrier, claim = "", ""
        idBoard = ""
        if card_id:
            try:
                import trello_client as tc
                card = tc.get_card(card_id) or {}
                idBoard = card.get("idBoard") or ""
                # Card name overrides the hint when present
                cn = (card.get("name") or "").strip()
                if cn: name = cn
                # Fill missing lane via get_lane_name if we didn't get
                # one from the search result.
                if not lane:
                    try:
                        lane = tc.get_lane_name(idBoard,
                                                  card.get("idList") or "") or ""
                    except Exception:
                        lane = ""
                    # Re-suggest if we just got the lane
                    if lane:
                        section = self._suggest_section_for_lane(lane)
                        sub = self._suggest_sub_for_lane(lane, section)
                # Parse desc for carrier + claim + the clean insured name.
                try:
                    fields = tc.parse_card_desc(card.get("desc") or "") or {}
                    ins = fields.get("INSURANCE INFORMATION") or {}
                    carrier = (ins.get("INSURANCE COMPANY") or "").strip()
                    claim   = (ins.get("CLAIM NUMBER") or "").strip()
                    # Insured comes from CUSTOMER INFORMATION → Customer
                    # Name, NOT the card name. Card names often carry a
                    # trailing claim number / date ("Bromme, Ira - 12345")
                    # that we never want in the APA title. Customer Name is
                    # the clean insured. Falls back to the card name when
                    # the desc has no customer block.
                    cust = fields.get("CUSTOMER INFORMATION") or {}
                    for _k in ("CUSTOMER NAME", "INSURED", "NAME",
                               "PROPERTY NAME", "BUSINESS NAME"):
                        _cn = (cust.get(_k) or "").strip()
                        if _cn:
                            name = _cn
                            break
                except Exception as ex:
                    notes.append(f"desc parse: {ex}")
            except Exception as ex:
                notes.append(f"card fetch: {ex}")

        # Safety net: strip any trailing claim number / date / paren note
        # off the insured so it never lands in the APA title — mirrors the
        # suffix-strip trello_client.client_name_candidates uses.
        if name:
            import re as _re_name
            name = _re_name.sub(r'\s*[\(\|].*$', '', name).strip()
            name = _re_name.sub(r'\s+-\s+\d.*$', '', name).strip()

        # Multi-claim: fold the claim LABEL ("1st Claim" / "2nd Claim
        # (Kitchen)") from the card name into the insured so each claim is
        # a DISTINCT APA row that pins + tracks separately (space-form, so
        # _canon_pin_key keeps it). This is the claim LABEL, not the claim
        # NUMBER (which we deliberately keep out of titles). Runs AFTER the
        # safety-net strip so the "(Kitchen)" descriptor survives.
        try:
            import audit_logic as _al_claim
            _clbl = _al_claim.claim_label_from_folder(card.get("name") or "")
            if _clbl and name and _clbl.lower() not in name.lower():
                name = f"{name} {_clbl}"
        except Exception:
            pass

        # Build "Insured - Carrier" string the APA expects
        base = name
        if carrier and " - " not in base:
            base = f"{name} - {carrier}"
        # Existing franchise tag for this client
        franchise = ""
        try:
            import persistence as _per
            key = apa._franchise_key(base) if base else ""
            if key:
                franchise = _per.get_franchise_tag(key) or ""
        except Exception:
            pass

        return {
            "ok":                True,
            "card_id":           card_id,
            "name":              name,
            "lane":              lane,
            "board_id":          idBoard,
            "suggested_section": section,
            "suggested_sub":     sub,
            "carrier":           carrier,
            "claim":             claim,
            "base_text":         base or name,
            "franchise":         franchise,
            "notes":             notes,
        }

    def auto_add_card_to_apa(self, card_id: str,
                               override_section: str = "",
                               override_sub: str = "",
                               status: str = "pending") -> dict:
        """Fetch the card, suggest routing, then drop the row into the
        target section. `override_section`/`override_sub` let the user
        steer when the auto-pick is wrong. Returns the same payload as
        add_item_to_section plus the routing info so the UI can toast."""
        r = self.suggest_apa_routing(card_id)
        if not r.get("ok"):
            return r
        section = override_section or r.get("suggested_section") or "Initial Uploads"
        sub = override_sub or r.get("suggested_sub") or ""
        base_text = r.get("base_text") or r.get("name") or ""
        if not base_text:
            return {"ok": False, "error": "card has no name"}
        added = self.add_item_to_section(section, base_text,
                                           status=status, sub=sub,
                                           highlighted=False)
        if not added.get("ok"):
            return added
        # Pin the card to this client so audit/snapshot share the link
        try:
            import persistence as _per
            key = apa._franchise_key(base_text)
            if key: _per.set_trello_card_id(key, card_id)
        except Exception:
            pass
        added["routed_section"] = section
        added["routed_sub"]     = sub
        added["lane"]           = r.get("lane") or ""
        return added

    def trello_search(self, query: str) -> list:
        """Find Trello cards by name for the Add-to-APA dialog."""
        if not query or len(query.strip()) < 2:
            return []
        try:
            import trello_client as tc
            return [{
                "card_id":   h.get("card_id") or h.get("id") or "",
                "name":      h.get("name") or "",
                "lane":      h.get("list_name") or h.get("lane") or "",
                "board":     h.get("board") or h.get("board_name") or "",
            } for h in (tc.find_cards_by_name(query.strip()) or [])[:20]]
        except Exception:
            return []

    def add_item_to_section(self, section: str, text: str,
                              status: str = "", sub: str = "",
                              highlighted: bool = False) -> dict:
        """Add a new item to today's APA doc + save. Used by the
        Add-to-APA-from-Trello flow + bulk paste.

        Auto-highlight: any status in apa.HIGHLIGHT_STATUSES (currently
        "pending" / "pending upload") forces highlight=True regardless
        of the caller's value. Matches the Tk panel's _format_item
        behavior so a Trello auto-add lands yellow just like the Tk
        equivalent.
        """
        if not section or not text:
            return {"ok": False, "error": "section + text required"}
        # Server-side auto-highlight — mirrors the Tk rule in
        # apa_monitor_gui.py:596 (`highlight = status.lower() in HIGHLIGHT_STATUSES`).
        try:
            hi_set = {s.lower() for s in (apa.HIGHLIGHT_STATUSES or set())}
            auto_hl = (status or "").strip().lower() in hi_set
        except Exception:
            auto_hl = False
        highlighted = bool(highlighted) or auto_hl
        try:
            d = _dt.date.today()
            path = apa.doc_path_for_today(d)
            sections = apa.parse_existing_doc(path) if os.path.isfile(path) else {}
            # Normalize to dict-of-list format then build the new item
            final_text = text.strip()
            if sub:    final_text += "-" + sub.strip()
            if status: final_text += "-" + status.strip()
            entries = list(sections.get(section, []))
            entries.append((final_text, bool(highlighted)))
            sections[section] = entries
            # Backfill missing sections + write
            for s in apa.SECTION_ORDER:
                sections.setdefault(s, [])
            apa.write_doc(path, d, sections)
            return {"ok": True, "doc": _doc_payload_for(d),
                    "auto_highlighted": bool(auto_hl)}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    # ── P1: Per-item Trello pin + extended-tracker bump ─────────────
    def get_pinned_card_for_item(self, item_text):
        """Return the Trello card id + open URL for an APA item, or
        empty strings when nothing is pinned. Used by the right-click
        menu to decide whether to show 'Open Trello' (pinned) or
        'Pin Trello…' (not pinned)."""
        bare = apa.strip_status_from_text(item_text or "").strip()
        if not bare:
            return {"card_id": "", "url": ""}
        try:
            import persistence as _per
            key = apa._franchise_key(bare)
            if not key:
                return {"card_id": "", "url": ""}
            cid = _per.get_trello_card_id(key) or ""
            return {"card_id": cid,
                    "url": f"https://trello.com/c/{cid}" if cid else ""}
        except Exception:
            return {"card_id": "", "url": ""}

    def open_trello_card(self, card_id):
        """Open a pinned Trello card in the default browser."""
        if not card_id: return False
        try:
            import webbrowser as _wb
            _wb.open(f"https://trello.com/c/{card_id}")
            return True
        except Exception:
            return False

    def pin_trello_for_item(self, item_text, card_id):
        """Pin a Trello card to the client name extracted from an APA
        item. Same backend `persistence.set_trello_card_id` so the
        pin shows up in audit / snapshot / job-notes too."""
        if not card_id:
            return {"ok": False, "error": "no card"}
        bare = apa.strip_status_from_text(item_text or "").strip()
        # The persisted pin key is the lowercase + carrier-stripped
        # form — `_franchise_key` already does that for us.
        try:
            key = apa._franchise_key(bare)
            if not key:
                return {"ok": False, "error": "couldn't derive client key"}
            import persistence as _per
            _per.set_trello_card_id(key, card_id)
            return {"ok": True, "key": key}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def bump_extended(self, item_text):
        """Increment the per-client extended counter — used to show
        🔁 N× badges on APA rows. `bump_apa_extended` lives in
        persistence; falls back to manual increment if not present."""
        bare = apa.strip_status_from_text(item_text or "").strip()
        if not bare:
            return {"ok": False}
        try:
            import persistence as _per
            key = apa._franchise_key(bare)
            if hasattr(_per, "bump_apa_extended"):
                count = _per.bump_apa_extended(key)
                return {"ok": True, "count": int(count or 0)}
            # Fallback: manual increment via raw store
            counts = _per.get("apa_extended_counts") or {}
            if not isinstance(counts, dict): counts = {}
            counts[key] = int(counts.get(key, 0)) + 1
            _per.set_value("apa_extended_counts", counts)
            return {"ok": True, "count": counts[key]}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def get_extended_count(self, item_text):
        """Read the extended counter for a given item — drives the
        🔁 N× badge rendering."""
        bare = apa.strip_status_from_text(item_text or "").strip()
        if not bare: return 0
        try:
            import persistence as _per
            key = apa._franchise_key(bare)
            if hasattr(_per, "get_apa_extended"):
                return int(_per.get_apa_extended(key) or 0)
            counts = _per.get("apa_extended_counts") or {}
            return int(counts.get(key, 0)) if isinstance(counts, dict) else 0
        except Exception:
            return 0

    # ── P1: Bulk paste — multiple items at once ─────────────────────
    def bulk_add_items(self, section, lines):
        """Add multiple items to a section in one shot. `lines` is a
        list of strings — each becomes a separate row. Empty lines
        skipped. Handles deduplication against existing items."""
        if not section:
            return {"ok": False, "error": "section required"}
        cleaned = [l.strip() for l in (lines or []) if l and l.strip()]
        if not cleaned:
            return {"ok": False, "error": "no lines to add"}
        try:
            d = _dt.date.today()
            path = apa.doc_path_for_today(d)
            sections = apa.parse_existing_doc(path) if os.path.isfile(path) else {}
            # Existing keys for dedupe
            existing = set()
            for it in sections.get(section, []):
                if isinstance(it, tuple): t = it[0]
                elif isinstance(it, dict): t = it.get("text", "")
                else: t = str(it)
                existing.add(t.strip().lower())
            added = []
            for line in cleaned:
                if line.lower() in existing: continue
                sections.setdefault(section, []).append((line, False))
                existing.add(line.lower())
                added.append(line)
            for s in apa.SECTION_ORDER:
                sections.setdefault(s, [])
            apa.write_doc(path, d, sections)
            return {"ok": True, "added": added,
                    "skipped_dupes": len(cleaned) - len(added)}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    # ── P1: Franchise tag manager ───────────────────────────────────
    def get_franchise_filter(self) -> str:
        try:
            import persistence as _per
            return _per.get_apa_franchise_filter() or ""
        except Exception:
            return ""

    def set_franchise_filter(self, value: str) -> dict:
        try:
            import persistence as _per
            _per.set_apa_franchise_filter(value or "")
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def get_franchise_list(self) -> list:
        """Return the configured franchise roster (the dropdown choices)."""
        try:
            import persistence as _per
            return list(_per.get_franchise_list() or [])
        except Exception:
            return []

    def set_franchise_list(self, items: list) -> dict:
        try:
            import persistence as _per
            _per.set_franchise_list(items or [])
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def get_item_franchise(self, item_text: str) -> str:
        """Return the franchise tag stored against this item's
        canonicalized client key (or "" when none)."""
        bare = apa.strip_status_from_text(item_text or "").strip()
        if not bare: return ""
        try:
            import persistence as _per
            key = apa._franchise_key(bare)
            return (_per.get_franchise_tags().get(key) or "") if key else ""
        except Exception:
            return ""

    def set_item_franchise(self, item_text: str, franchise: str) -> dict:
        """Assign (or clear with empty string) a franchise tag against
        an APA item's client key. Survives across days because the key
        is the normalized 'Client - Carrier' form."""
        bare = apa.strip_status_from_text(item_text or "").strip()
        if not bare:
            return {"ok": False, "error": "no client text"}
        try:
            import persistence as _per
            key = apa._franchise_key(bare)
            if not key:
                return {"ok": False, "error": "couldn't derive key"}
            _per.set_franchise_tag(key, franchise or "")
            return {"ok": True, "key": key, "franchise": franchise or ""}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    # ── Section reorder + manage (Tk parity) ─────────────────────────
    def get_section_order(self) -> list:
        """Return the stored apa_section_order list — drives the
        manage-sections dialog. Mirrors apa_monitor_gui's
        `apa_section_order` persistence key."""
        try:
            import persistence as _per
            stored = _per.get("apa_section_order") or []
            if isinstance(stored, list) and stored:
                return list(stored)
        except Exception:
            pass
        # Fall back to current SECTION_ORDER if nothing saved
        try:
            return list(apa.SECTION_ORDER)
        except Exception:
            return []

    def set_section_order(self, order: list) -> dict:
        """Persist a new section order — drag-to-reorder in the
        manage-sections dialog or the kanban-column drag handles."""
        if not isinstance(order, list):
            return {"ok": False, "error": "order must be a list"}
        try:
            import persistence as _per
            cleaned = [str(s).strip() for s in order if s and str(s).strip()]
            _per.set_value("apa_section_order", cleaned)
            # Clear the legacy key so it doesn't shadow the new one
            try: _per.set_value("apa_estimators", None)
            except Exception: pass
            # Rebuild apa.SECTION_ORDER so subsequent reads pick up
            # the new ordering without a process restart.
            try:
                apa.SECTION_ORDER = list(cleaned)
            except Exception:
                pass
            return {"ok": True, "count": len(cleaned)}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def builtin_sections(self) -> list:
        """Section names that can be reordered but NOT removed via
        the manage dialog (Final Uploads, Initial Uploads, Audit*,
        Estimating* etc.). Mirrors apa._BUILTIN_SET."""
        try:
            return list(apa._BUILTIN_SET)
        except Exception:
            return []

    # ── Per-item note (Tk parity: 📝 note button per row) ───────────
    def get_item_note(self, client: str, section: str) -> str:
        """Read the per-item note stored against this (client, section)
        pair. Surfaced on the item's 📝 button — yellow when present."""
        if not client or not section:
            return ""
        try:
            import persistence as _per
            bare = apa.strip_status_from_text(client or "").strip()
            return _per.get_apa_message_note(bare, section) or ""
        except Exception:
            return ""

    def set_item_note(self, client: str, section: str, text: str) -> dict:
        """Save / clear the per-item note."""
        if not client or not section:
            return {"ok": False, "error": "client + section required"}
        try:
            import persistence as _per
            bare = apa.strip_status_from_text(client or "").strip()
            _per.set_apa_message_note(bare, section, text or "")
            return {"ok": True, "has_text": bool((text or "").strip())}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    # ── Extended counter (Tk parity: 🔁 N× badge per row) ───────────
    def get_extended_history(self) -> dict:
        """Bulk read of every client's extended count — keyed by
        canonical client. JS uses this once at render time so the
        🔁 badges paint without N round-trips."""
        try:
            import persistence as _per
            return dict(_per.get_apa_extended_history() or {})
        except Exception:
            return {}

    def get_all_franchise_tags(self) -> dict:
        """Bulk read: client_key → franchise. Used by the frontend to
        render the chip on every row in one shot."""
        try:
            import persistence as _per
            return dict(_per.get_franchise_tags() or {})
        except Exception:
            return {}

    def send_eod_email(self, date_iso: str = "",
                       sections_payload: list = None) -> dict:
        """Build EOD email body + compose URL. Returns the URL the
        frontend opens (so the user lands in Outlook web with TO +
        subject + body pre-filled). Same flow the Tk version uses.

        Prefers the frontend's in-view sections (matching Tk's
        `self.sections` semantics — works even before the user has
        saved today's APA doc). Falls back to re-reading the .docx
        from disk if the frontend didn't send a payload.
        """
        try:
            import persistence as _per
            recipients = list(_per.get_eod_recipients() or [])
        except Exception:
            recipients = []
        if not recipients:
            return {"ok": False, "needs_recipients": True}
        try:
            try:
                d = _dt.date.fromisoformat(date_iso) if date_iso else _dt.date.today()
            except Exception:
                d = _dt.date.today()
            # Prefer the frontend's current in-view state — Tk uses
            # `self.sections` here and the web equivalent is whatever
            # the user is currently looking at. Falls back to the
            # disk .docx when the frontend didn't pass a payload.
            sections = {}
            if sections_payload:
                for s in sections_payload:
                    name = s.get("name") or ""
                    if not name:
                        continue
                    items = []
                    for it in (s.get("items") or []):
                        t = (it.get("text") or "").strip()
                        if t:
                            items.append((t, bool(it.get("highlighted"))))
                    sections[name] = items
            else:
                path = apa.doc_path_for_today(d)
                sections = apa.parse_existing_doc(path) if os.path.isfile(path) else {}
            # Build the same plain-text body shape as the Tk version
            # AND match the .docx layout: the first paragraph of the
            # APA doc is the date in m/d/yy form. Mirror that at the
            # top of the email body so the recipient sees the date
            # right alongside the sections.
            lines = [d.strftime("%-m/%-d/%y") if os.name != "nt"
                     else d.strftime("%m/%d/%y").lstrip("0").replace("/0", "/")]
            lines.append("")  # blank line between date and first section
            # Iterate the section order from the payload when given —
            # the user's customized order — falling back to apa.SECTION_ORDER
            # for the disk-fallback path.
            section_order = ([s.get("name") for s in sections_payload if s.get("name")]
                             if sections_payload else list(apa.SECTION_ORDER))
            for sec in section_order:
                items = sections.get(sec, [])
                # Flatten (text, highlighted) tuples + dicts
                flat = []
                for it in items:
                    if isinstance(it, tuple):
                        if it[0] and it[0].strip(): flat.append(it[0])
                    elif isinstance(it, dict):
                        t = (it.get("text") or "").strip()
                        if t: flat.append(t)
                if not flat:
                    continue
                lines.append(sec)
                for i, txt in enumerate(flat, 1):
                    lines.append(f"{i}. {txt}")
                lines.append("")
            body = "\n".join(lines).rstrip() + "\n"
            subject = f"APA EOD - {d.strftime('%a %m/%d/%Y')}"
            import urllib.parse as _up
            params = {
                "to":      ",".join(recipients),
                "subject": subject,
                "body":    body,
            }
            url = ("https://outlook.office.com/mail/deeplink/compose?"
                    + _up.urlencode(params, quote_via=_up.quote))
            return {"ok": True, "url": url, "subject": subject,
                    "body": body, "recipients": recipients}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    # ── Actions ──────────────────────────────────────────────────────
    def open_doc_in_word(self, doc_path: str) -> bool:
        """Open the .docx in Word (or the default handler)."""
        if not doc_path or not os.path.isfile(doc_path):
            return False
        try:
            os.startfile(doc_path)  # Windows-only; mirrors Tk behavior
            return True
        except Exception:
            return False

    def reveal_in_explorer(self, doc_path: str) -> bool:
        """Open Explorer with the doc selected."""
        if not doc_path:
            return False
        try:
            import subprocess
            if os.name == "nt":
                subprocess.run(["explorer", "/select,", doc_path])
            return True
        except Exception:
            return False

    def copy_to_clipboard(self, text: str) -> bool:
        if not text:
            return False
        # Win32 clipboard, NOT a throwaway tk.Tk() — Tk's delayed-rendering
        # clipboard left a dead owner that froze the next paste everywhere.
        from web_helpers import set_clipboard_text
        return set_clipboard_text(text)

    def open_url(self, url: str) -> bool:
        if not url:
            return False
        try:
            webbrowser.open(url)
            return True
        except Exception:
            return False

    # ── Phase 2: editing ─────────────────────────────────────────────
    def create_doc(self, date_iso: str = "",
                    carry_forward: bool = True) -> dict:
        """Auto-create the APA .docx for `date_iso` (defaults to today).

        Mirrors the Tk panel's first-open auto-create flow:
          1. If the doc already exists, no-op (returns the existing
             payload — `created=False`).
          2. Otherwise walks up to 14 days back for the most recent
             prior APA doc and carries forward its still-active items
             (pending / pending upload / extended / uploading + any
             highlighted rows).
          3. Writes the .docx to disk via `apa.write_doc` so the
             file appears on the shared share immediately.
          4. Returns the fresh payload so the UI can render.

        `carry_forward=False` writes an empty doc — useful when the
        user explicitly wants to start fresh.
        """
        try:
            d = (_dt.date.fromisoformat(date_iso) if date_iso
                  else _dt.date.today())
        except Exception:
            return {"ok": False, "error": "bad date"}
        path = apa.doc_path_for_today(d)
        if os.path.isfile(path):
            return {"ok": True, "created": False,
                    "doc": _doc_payload_for(d),
                    "note": "Doc already exists"}

        # Active-status detection: same loose pattern apa_monitor_gui's
        # push_initial_uploads uses — substring match against the
        # status keywords inside the rendered item text. Avoids needing
        # to re-parse the structured status dict.
        ACTIVE_STATUSES = {"pending", "pending upload",
                           "extended", "uploading"}
        sections = {s: [] for s in apa.SECTION_ORDER}
        carried = 0
        if carry_forward:
            import datetime as _ddt
            for days_back in range(1, 15):
                prior_d = d - _ddt.timedelta(days=days_back)
                prior_path = apa.doc_path_for_today(prior_d)
                if not os.path.isfile(prior_path):
                    continue
                parsed = apa.parse_existing_doc(prior_path) or {}
                for sec, items in parsed.items():
                    if sec not in sections:
                        sections[sec] = []
                    for text, highlighted in items:
                        low = (text or "").lower()
                        if highlighted or any(s in low for s in ACTIVE_STATUSES):
                            sections[sec].append((text, bool(highlighted)))
                            carried += 1
                break  # stop at first prior doc

        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            apa.write_doc(path, d, sections)
        except Exception as ex:
            return {"ok": False,
                    "error": f"write_doc: {ex}"}
        return {"ok": True, "created": True, "carried": carried,
                "doc": _doc_payload_for(d)}

    def save_doc(self, date_iso: str, sections: list) -> dict:
        """Persist edits to the APA doc for `date_iso`. `sections` is
        a list of {name, items: [{text, highlighted}]} matching what
        the frontend renders. Writes the .docx via the existing
        `apa_monitor_gui.write_doc`, then re-parses + returns the
        fresh payload so the frontend can resync state.

        Auto-creates the target path if missing (today's first edit
        before the daily APA doc was created).
        """
        try:
            d = _dt.date.fromisoformat(date_iso)
        except Exception:
            return {"ok": False, "error": "bad date"}
        path = apa.doc_path_for_today(d)
        # Normalize input into the (text, highlighted) tuple shape
        # write_doc expects.
        normalized = {}
        for s in (sections or []):
            name = s.get("name") or ""
            if not name:
                continue
            items = []
            for it in (s.get("items") or []):
                text = (it.get("text") or "").strip()
                if not text:
                    continue
                items.append((text, bool(it.get("highlighted"))))
            normalized[name] = items
        # Backfill missing sections with empty lists so write_doc
        # renders the canonical section order without dropping any.
        for s in apa.SECTION_ORDER:
            normalized.setdefault(s, [])
        try:
            apa.write_doc(path, d, normalized)
        except Exception as ex:
            return {"ok": False,
                    "error": f"{type(ex).__name__}: {ex}"}
        # Return the fresh payload so the JS can splice it
        return {"ok": True, "doc": _doc_payload_for(d)}


def main(argv=None):
    api = Api()
    window = webview.create_window(
        title="APA Monitor — EMS Tools (web spike)",
        url=INDEX_HTML,
        js_api=api,
        width=1480, height=860,
        min_size=(820, 540),
    )
    api.attach(window)
    webview.start(debug=False)


if __name__ == "__main__":
    main()
