"""Hygiene — Pywebview panel.

Renders the cached hygiene scan as sections with item counts +
per-section action rows. The full background scan runs from the
shared trello_hygiene / closeout_watcher / adjuster_monitor /
estimate_request_tracker / dispute_email_scan modules; this panel
reads the cache and exposes per-section actions: resolve, dismiss,
mark-handled, post, snooze, escalate, etc.
"""
from __future__ import annotations
import os, sys, webbrowser
import webview

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path: sys.path.insert(0, _HERE)

import hygiene_tabs as _htabs
import persistence
from web_helpers import jsonify as _jsonify, run_bg as _wh_run_bg

# Pre-import the scan modules at module load. The earlier code did
# `import trello_hygiene` inside the scan worker thread; first-call
# imports hold the GIL while resolving sub-imports (oauth lib,
# requests, etc.) and the pywebview bridge thread can't run while
# the GIL is locked. That made the bridge call run_scan() appear to
# hang for ~1-3 seconds the first time the user clicked Run Scan —
# which the user reported as "freezes when I click run scan". With
# the imports hoisted, the bridge call returns in microseconds.
try:
    import trello_hygiene as _th_pre
    import closeout_watcher as _cw_pre  # noqa: F401
    import xa_apology as _xa_pre  # noqa: F401
    import weekly_checkins as _wc_pre  # noqa: F401
    import estimate_requests as _er_pre  # noqa: F401
    import adjuster_monitor as _am_pre  # noqa: F401
    import ar_followup as _arf_pre  # noqa: F401
except Exception:
    # Each import is best-effort — if any module is unavailable,
    # the worker re-imports inside try/except at scan time. The
    # pre-warm is just to avoid the first-click latency.
    pass

ASSETS_DIR = os.path.join(_HERE, "hygiene_web_assets")
INDEX_HTML = os.path.join(ASSETS_DIR, "index.html")


class Api:
    def __init__(self):
        self._window = None
        # Holds the full grouped + raw payload in Python memory between
        # get_cache and get_section_items calls. Lets the frontend lazy-
        # load slices instead of receiving every item upfront (which was
        # OOMing the WebView2 renderer for large scans).
        self._cache_grouped: dict[str, list] = {}
        self._cache_age_minutes: int | None = None
    def attach(self, w): self._window = w

    # ── Simple job board (shared renderer web_shared/hygiene_board.js) ──
    def hygiene_board_rows(self):
        """Active jobs + their four admin milestones — the simplified
        default view. Same source the audit Overview reads."""
        try:
            import hygiene_board as _hb
            return {"ok": True, "rows": _hb.board_rows()}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "rows": []}

    def hygiene_mark(self, canon, milestone, card_id=""):
        try:
            import hygiene_board as _hb
            return _hb.mark_milestone(canon, milestone, card_id=card_id)
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def request_item_options(self):
        try:
            import request_items as _ri
            return {"ok": True, "items": _ri.ITEMS,
                    "handles": _ri.recent_handles()}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "items": [], "handles": []}

    def request_items_send(self, card_id, canon, keys, other="",
                           handle="", client=""):
        try:
            import request_items as _ri
            return _ri.send(card_id, canon, keys or [], other, handle, client)
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def get_cache(self):
        """Return the latest hygiene scan from persistence, grouped
        into the same sections the Tk panel uses (see hygiene_gui.py
        _SECTIONS). `scanned=False` only when NO scan has ever run —
        otherwise we always surface whatever's persisted regardless
        of age so the user has something to act on. The frontend
        decides when to warn: stale=True at 2h, very_stale at 24h.
        """
        # 30-day window — effectively "show whatever we've got" so
        # the panel never goes empty just because the user didn't
        # scan today. Tk's hygiene_gui does the same — it loads the
        # cache on open and warns about staleness in the status bar
        # rather than blocking the view.
        cache = persistence.get_hygiene_scan_cache(max_age_minutes=30 * 24 * 60)
        if cache is None:
            return {"scanned": False, "sections": [], "age_minutes": None,
                    "tabs": _TABS_PAYLOAD, "display": _DISPLAY_SECTIONS,
                    "stale": False, "very_stale": False}
        payload, age = cache
        age_minutes = max(0, int(age / 60))
        # Staleness thresholds — tuned for the hygiene workflow where
        # Trello state changes frequently. 2h = "remind to rescan",
        # 24h = "this is genuinely old, treat carefully".
        STALE_MIN       = 2 * 60      # 2 hours
        VERY_STALE_MIN  = 24 * 60     # 24 hours

        # ── Group by Tk-style section key (NOT by raw rule) ───────
        hyg_items = payload.get("hygiene") or []
        grouped: dict[str, list] = {k: [] for k, *_ in _TK_SECTIONS}

        # concerns ← rule=customer_complaint
        grouped["concerns"] = [v for v in hyg_items
                               if v.get("rule") == "customer_complaint"]
        # handoff   ← rule=lane_move_no_handoff
        grouped["handoff"]  = [v for v in hyg_items
                               if v.get("rule") == "lane_move_no_handoff"]
        # eq_on_site ← rule=equipment_on_site (equipment placed, no pickup)
        grouped["eq_on_site"] = [v for v in hyg_items
                                 if v.get("rule") == "equipment_on_site"]
        # lost_job   ← rule=lost_job (customer went with another firm)
        grouped["lost_job"] = [v for v in hyg_items
                               if v.get("rule") == "lost_job"]
        # hygiene   ← everything else (no_owner / no_follow_up /
        #             no_next_action / stale_no_comment / etc)
        _own_rules = ("customer_complaint", "lane_move_no_handoff",
                      "equipment_on_site", "lost_job")
        grouped["hygiene"]  = [v for v in hyg_items
                               if v.get("rule") not in _own_rules]

        # Other payload keys come pre-grouped from the scan
        for key in ("closeout", "xa_apology", "xa_gaps", "ipr",
                    "estimates", "weekly", "missing_items",
                    "docusketch", "docusketch_needed", "docusign",
                    "docusign_resends", "open_jobs", "stalled",
                    "anomalies", "wc_audit_due"):
            grouped[key] = list(payload.get(key) or [])

        # Adjuster pending — live from adjuster_monitor (mirror Tk).
        # Cap at 500 — a stuck queue can grow into thousands and
        # cause the bridge payload to balloon.
        try:
            import adjuster_monitor as am
            grouped["adjuster_pending"] = list(
                am.list_pending() or [])[:500]
        except Exception:
            grouped["adjuster_pending"] = []

        # Disputes — live from dispute_tracker. Same 500 cap.
        try:
            import dispute_tracker as dt
            grouped["disputes"] = list(dt.all_active() or [])[:500]
        except Exception:
            grouped["disputes"] = list(payload.get("disputes") or [])[:500]

        # XA inquiries — live from xa_inquiry_scan's review queue. Shaped
        # so `_shape` reads client/detail/message_id off each candidate.
        try:
            import xa_inquiry_scan as _xi
            grouped["xa_inquiries"] = [{
                "client_name": (e.get("insured") or "").strip()
                               or (e.get("claim") or ""),
                "detail":      e.get("preview") or e.get("note") or "",
                "message_id":  e.get("message_id") or "",
                "claim":       e.get("claim") or "",
                "body":        e.get("note") or "",
            } for e in (_xi.list_pending() or [])][:500]
        except Exception:
            grouped["xa_inquiries"] = []

        # Build the section payload in _TK_SECTIONS declared order.
        #
        # HEADERS-ONLY mode for the bridge AND aggressive Python-side
        # truncation. The diagnostic in the field showed a user with
        # 3,331 hygiene items cached — reading + shaping those into
        # `self._cache_grouped` even in Python alone allocated enough
        # heap to push the rest of the WebView2 process into OOM.
        #
        # Truncate every section at 200 items at the read boundary so
        # the worst case is bounded regardless of cache bloat. Users
        # who hit the cap should run "⚡ Minimal scan" or clear the
        # cache via 🩺 Diag to start fresh.
        INITIAL_PAGE = 0
        SECTION_CAP = 200
        self._cache_grouped = {}
        self._cache_age_minutes = age_minutes
        sections = []
        for entry in _TK_SECTIONS:
            key, icon, label = entry[0], entry[1], entry[2]
            description = entry[3] if len(entry) > 3 else ""
            raw_items = grouped.get(key) or []
            full_count = len(raw_items)
            # SECTION_CAP truncates at the read boundary — this is the
            # bound on what we keep in Python memory. The Python heap
            # never grows past ~200 items per section regardless of
            # what's in persistence. Cached over-quota items are
            # silently dropped at read time; the only way to see them
            # is to run a fresh scan that produces fewer than 200.
            items = list(raw_items[:SECTION_CAP])
            truncated = full_count > SECTION_CAP
            self._cache_grouped[key] = items
            sections.append({
                "key":         key,
                "label":       f"{icon} {label}" if icon else label,
                "description": description,
                "tab":         _SECTION_TO_TAB.get(key, "action"),
                "count":       len(items),  # advertise the capped count
                "full_count":  full_count,  # original count for telemetry
                "items":       [],            # ZERO items in bridge payload
                "shown":       0,
                "has_more":    len(items) > 0,
                "next_offset": 0,
                "truncated":   truncated,
            })
        return {
            "scanned":     True,
            "sections":    sections,
            "tabs":        _TABS_PAYLOAD,
            "display":     _DISPLAY_SECTIONS,
            "age_minutes": age_minutes,
            "stale":       age_minutes >= STALE_MIN,
            "very_stale":  age_minutes >= VERY_STALE_MIN,
            "scanned_at":  payload.get("ts") or "",
            "total":       sum(s["count"] for s in sections),
        }

    def get_section_items(self, key: str, offset: int = 0,
                          limit: int = 50) -> dict:
        """Lazy-load page of items for one section. Slices the in-memory
        cache built by `get_cache` — no scan re-run, no full re-shape.

        The frontend renders the first `INITIAL_PAGE` items returned by
        get_cache; calls this when the user clicks "Load more" or
        scrolls near the bottom of the section. Bounded payload (<= 50
        items × ~15 fields) keeps the JS bridge call small.
        """
        items = self._cache_grouped.get(key) or []
        try:
            offset = max(0, int(offset))
            limit = max(1, min(int(limit), 200))
        except Exception:
            offset, limit = 0, 50
        slice_ = items[offset:offset + limit]
        return {
            "key":         key,
            "items":       [_shape(it) for it in slice_],
            "offset":      offset,
            "next_offset": offset + len(slice_),
            "has_more":    (offset + len(slice_)) < len(items),
            "total":       len(items),
        }

    def get_priority_feed(self, display_keys=None, limit: int = 120) -> dict:
        """Unified, most-urgent-first feed for the priority dashboard.

        Merges items from the ALREADY-CAPPED in-memory cache built by
        get_cache (≤200 per backend section), so this adds no new memory
        pressure — critical on the user's RAM-constrained laptop. Each
        item is shaped once, tagged with its display section (key/icon/
        label) + backend section key (for per-row action routing), and
        scored by (tier, aging-days, severity). `display_keys` filters to
        one or more tiles; None = every feed section.

        Returns {items, total, shown, truncated}.
        """
        want = set(display_keys) if display_keys else None
        sev_rank = {"high": 3, "critical": 3, "urgent": 3,
                    "med": 2, "medium": 2, "amber": 2,
                    "low": 1, "": 0}
        collected = []
        for d in _DISPLAY_SECTIONS:
            if d.get("feed") is False:
                continue
            if want is not None and d["key"] not in want:
                continue
            for bkey in d["keys"]:
                for it in (self._cache_grouped.get(bkey) or []):
                    shaped = _shape(it)
                    try:
                        days = int(shaped.get("days") or 0)
                    except Exception:
                        days = 0
                    sev = sev_rank.get(
                        str(shaped.get("severity") or "").lower(), 0)
                    shaped["section"]       = bkey
                    shaped["display_key"]   = d["key"]
                    shaped["display_label"] = d["label"]
                    shaped["display_icon"]  = d["icon"]
                    shaped["tier"]          = d["tier"]
                    # Sort key: lower tier first, then older, then severe.
                    shaped["_sort"] = (d["tier"], -days, -sev)
                    collected.append(shaped)
        collected.sort(key=lambda r: r["_sort"])
        total = len(collected)
        try:
            limit = max(1, min(int(limit), 500))
        except Exception:
            limit = 120
        out = collected[:limit]
        for r in out:
            r.pop("_sort", None)
        return {"items": out, "total": total, "shown": len(out),
                "truncated": total > len(out)}

    # ── XA inquiries (review-gated → Inquiries & Disputes tracker) ──
    def run_xa_inquiry_scan(self, days: int = 30) -> dict:
        """Scan the inbox for XA adjuster inquiries and queue candidates.
        Returns {ok, queued, scanned, error?}."""
        try:
            import xa_inquiry_scan as _xi
            res = _xi.scan(days=int(days or 30))
            if res.get("error"):
                return {"ok": False, "error": res["error"]}
            return {"ok": True, "queued": res.get("queued", 0),
                    "scanned": res.get("scanned", 0)}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def approve_xa_inquiry(self, message_id: str) -> dict:
        """✓ Add a queued XA inquiry to the Inquiries & Disputes tracker."""
        try:
            import xa_inquiry_scan as _xi
            return _xi.approve(message_id)
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def dismiss_xa_inquiry(self, message_id: str) -> dict:
        """✕ Dismiss a queued XA inquiry (don't track it)."""
        try:
            import xa_inquiry_scan as _xi
            return {"ok": bool(_xi.dismiss(message_id))}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def open_url(self, url):
        if not url: return False
        try: webbrowser.open(url); return True
        except Exception: return False

    def dismiss(self, card_id, rule, hours=24):
        """Snooze a hygiene row by `card_id` + `rule` for `hours`.
        Mirrors persistence.dismiss_card_warning the Tk panel uses."""
        if not card_id or not rule: return {"ok": False}
        try:
            persistence.dismiss_card_warning(card_id, rule, hours=int(hours))
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    # ── Per-section row actions ─────────────────────────────────────
    # Each section type has its own primary action. Web exposes the
    # backends here; the JS picks the right button per section key.

    def mark_docusketch_requested(self, card_id, client, body=""):
        """Mark DocuSketch as requested — same backend the Tk hygiene
        panel calls. Posts Trello comment + records a pending entry
        so the Hygiene reminder auto-clears on the next scan."""
        if not card_id:
            return {"ok": False, "error": "no card"}
        try:
            import docusketch_requests as dr
            entry = dr.request(card_id, client_name=client)
            if entry is None:
                return {"ok": False, "error": "request failed"}
            return {"ok": True,
                    "card_name": entry.get("card_name", ""),
                    "posted":    bool(entry.get("comment_posted", True))}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def resend_docusign(self, card_id, client, body=""):
        """Repost a DocuSign-resend comment + bump the 5-day SLA
        timer in persistence. Mirrors Tk's Resend button."""
        if not card_id:
            return {"ok": False}
        try:
            import trello_client as tc
            tc.post_comment(card_id,
                "📧 DocuSign Final-Paperwork resent — please re-sign.")
            # Reset the per-card SLA timer if persistence helper exists
            try:
                key = f"docusign_resends.{card_id}.last_sent"
                import datetime as _dt
                persistence.set_value(key,
                    _dt.datetime.now().isoformat(timespec="seconds"))
            except Exception:
                pass
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def ack_estimate(self, card_id, client, body=""):
        """Acknowledge an overdue estimate request — posts the canned
        ack to Trello + clears the Hygiene clock. Mirrors Tk's
        💬 ack button on the Estimate-requests section."""
        if not card_id:
            return {"ok": False}
        try:
            import trello_client as tc
            ack_text = (
                f"💰 Estimate request acknowledged — will follow up "
                f"within 48 hours.")
            tc.post_comment(card_id, ack_text)
            try:
                key = f"estimate_acks.{card_id}.acked_at"
                import datetime as _dt
                persistence.set_value(key,
                    _dt.datetime.now().isoformat(timespec="seconds"))
            except Exception:
                pass
            return {"ok": True, "ack_text": ack_text}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def confirm_ipr(self, card_id, client, body=""):
        """Confirm Initial Photo Report uploaded — posts the canonical
        comment + records in IPR tracker via persistence."""
        if not card_id:
            return {"ok": False}
        try:
            import trello_client as tc
            tc.post_comment(card_id,
                "📷 Initial Photo Report Created and Uploaded to OD.")
            # The IPR tracker auto-clears on this comment text per
            # project_ipr_tracker. No extra write needed.
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def send_weekly_note(self, card_id, client, body=""):
        """Post the canonical 'weekly status' Trello comment + mark the
        card so it drops off the Hygiene Weekly Check-Ins section for
        another 7 days. Mirrors hygiene_gui._send_weekly_note."""
        if not card_id:
            return {"ok": False, "error": "no card"}
        try:
            import weekly_checkins as wc
            import trello_client as tc
            text = wc.template()
            tc.post_comment(card_id, text)
            try:
                wc.mark_weekly_note_sent(card_id)
            except Exception:
                pass
            return {"ok": True, "text": text}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def mark_handoff_done(self, card_id, client, body=""):
        """User says the lane move had a handoff posted manually —
        clear it from the Hygiene Handoff Missing section by adding
        the card to a dismiss list. Mirrors the Tk panel's per-row
        ✓ button on the handoff section."""
        if not card_id:
            return {"ok": False, "error": "no card"}
        try:
            # Use the standard hygiene dismiss with a long TTL (essentially
            # forever) — the audit/scan that detects missing handoffs only
            # flags within a 24h window anyway, so the dismissal naturally
            # expires when the underlying signal does.
            persistence.dismiss_card_warning(card_id, "lane_move_no_handoff",
                                              hours=24 * 7)
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def post_adjuster_inquiry(self, card_id, client, body):
        """Post a queued adjuster-inquiry comment to Trello after the
        user approves it. Mirrors Tk's ✓ Post button on the Adjuster
        inquiries section. Also dismisses from the pending-approval
        queue so it doesn't re-surface."""
        if not card_id or not body:
            return {"ok": False, "error": "missing card or body"}
        try:
            import trello_client as tc
            tc.post_comment(card_id, body)
            # Clear the per-card pending entry
            try:
                pending = persistence.get("adjuster_pending_approval") or {}
                if card_id in pending:
                    del pending[card_id]
                    persistence.set_value("adjuster_pending_approval", pending)
            except Exception:
                pass
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def get_xa_apology_note(self):
        """Return the canonical XA apology note text. Mirrors
        audit_web.Api.get_xa_apology_note — single source of truth in
        ar_followup.DEFAULT_NOTE."""
        try:
            from ar_followup import DEFAULT_NOTE as _note
            return {"ok": True, "note": _note}
        except Exception:
            return {"ok": True,
                    "note": ("Our apologies for the delay. Please note "
                              "our estimating team is diligently working "
                              "on the file.")}

    def list_boards(self):
        """List in-scope Trello boards for the filter dropdown."""
        try:
            import trello_client as tc
            return [{"id": b.get("id"), "name": b.get("name") or "Board"}
                    for b in (tc.list_boards(exclude_quality=True) or [])]
        except Exception:
            return []

    # ── P1: Cross-panel jumps + XA quick link ───────────────────────
    # ── Secondary per-section actions (mirror Tk per-row buttons) ───
    # Each method maps to an underlying tracker module helper. Hygiene
    # Tk rows have 2-4 actions per section; the web previously exposed
    # only the primary one. These methods round out the set so a user
    # can fully manage a row without flipping to Tk.

    def resolve_docusketch_request(self, card_id: str) -> dict:
        """✓ Resolve a pending Docusketch request (zip received)."""
        if not card_id:
            return {"ok": False, "error": "card_id required"}
        try:
            import docusketch_requests as _dr
            _dr.resolve(card_id)
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def dismiss_docusketch_wip(self, card_id: str) -> dict:
        """🙈 Dismiss a Docusketch WIP card (won't surface again)."""
        if not card_id:
            return {"ok": False, "error": "card_id required"}
        try:
            import docusketch_requests as _dr
            _dr.dismiss_wip_card(card_id)
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def resolve_docusign_request(self, card_id: str) -> dict:
        """✓ Resolve a Docusign-pending row (paperwork signed)."""
        if not card_id:
            return {"ok": False, "error": "card_id required"}
        try:
            import docusign_requests as _dr
            _dr.resolve(card_id)
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def mark_xa_handled(self, card_id: str) -> dict:
        """✓ Mark an XA apology row handled (won't re-flag)."""
        if not card_id:
            return {"ok": False, "error": "card_id required"}
        try:
            import ar_followup as _arf
            _arf.mark_handled(card_id)
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def mark_xa_gap_resolved(self, group_key: str) -> dict:
        """✓ Mark an XA-notes gap row resolved (won't re-flag)."""
        if not group_key:
            return {"ok": False, "error": "group_key required"}
        try:
            import xa_email_ingest as _xae
            _xae.mark_resolved(group_key)
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def missing_item_resolved(self, request_id: str) -> dict:
        """✓ Mark a missing-item flag resolved (the file showed up)."""
        if not request_id:
            return {"ok": False, "error": "request_id required"}
        try:
            import missing_items_tracker as _mit
            _mit.mark_resolved(request_id)
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def missing_item_ignored(self, request_id: str, reason: str = "") -> dict:
        """🙈 Ignore a missing-item flag (won't re-surface)."""
        if not request_id:
            return {"ok": False, "error": "request_id required"}
        try:
            import missing_items_tracker as _mit
            _mit.mark_ignored(request_id, reason=reason or "")
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def docusign_resend_signed(self, request_id: str) -> dict:
        """✓ Mark a Docusign resend as signed."""
        if not request_id:
            return {"ok": False, "error": "request_id required"}
        try:
            import missing_items_tracker as _mit
            _mit.mark_docusign_signed(request_id)
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def docusign_resend_physical(self, request_id: str,
                                 note: str = "") -> dict:
        """📝 Mark a Docusign resend as physical signature collected."""
        if not request_id:
            return {"ok": False, "error": "request_id required"}
        try:
            import missing_items_tracker as _mit
            _mit.mark_physical_signature_done(request_id, note=note or "")
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def closeout_mark_drafted(self, card_id: str) -> dict:
        """🏁 Mark snapshot drafted (clears the closeout queue row)."""
        if not card_id:
            return {"ok": False, "error": "card_id required"}
        try:
            import closeout_watcher as _cw
            _cw.mark_drafted(card_id)
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def adjuster_dismiss(self, message_id: str) -> dict:
        """✕ Dismiss a pending adjuster-inquiry row (don't post)."""
        if not message_id:
            return {"ok": False, "error": "message_id required"}
        try:
            import adjuster_monitor as _am
            _am.dismiss_pending(message_id)
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def estimate_dismiss(self, request_id: str, reason: str = "") -> dict:
        """✕ Dismiss an estimate-request row (no ack needed)."""
        if not request_id:
            return {"ok": False, "error": "request_id required"}
        try:
            import estimate_requests as _er
            _er.dismiss(request_id, reason=reason or "")
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def open_xa_link(self, card_id):
        """Open the XactAnalysis link attached to this Trello card."""
        if not card_id:
            return False
        try:
            import trello_client as tc
            url = ""
            if hasattr(tc, "card_xa_link"):
                # card_xa_link parses the card DICT's desc — fetch it.
                card = tc.get_card(card_id) or {}
                url = tc.card_xa_link(card) or ""
            if url:
                webbrowser.open(url)
                return True
        except Exception:
            pass
        return False

    # ── P1: Manual DocuSign add (no Trello card needed) ─────────────
    def add_manual_docusign(self, client, days_ago=0, note=""):
        """Manually log a DocuSign-sent entry without going through
        the docusketch_requests/docusign_requests flow. Useful when
        the user sent a DocuSign outside the app and just wants the
        5-day SLA timer started in Hygiene."""
        if not client:
            return {"ok": False, "error": "client required"}
        try:
            import datetime as _dt
            sent_at = _dt.datetime.now() - _dt.timedelta(days=int(days_ago or 0))
            iso = sent_at.isoformat(timespec="seconds")
            existing = persistence.get("docusign_resends") or {}
            if not isinstance(existing, dict): existing = {}
            # Use client name (lowercased) as a synthetic key since
            # there's no card_id
            key = f"manual::{client.strip().lower()}"
            existing[key] = {
                "client":    client.strip(),
                "last_sent": iso,
                "note":      note or "",
                "manual":    True,
            }
            persistence.set_value("docusign_resends", existing)
            return {"ok": True, "key": key, "sent_at": iso}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    # ── P1: Section-title click → email-first / Trello-first ────────
    def get_section_link_target(self, rule):
        """Return the URL the section title should open when clicked.
        Email-first for sections where the workflow is email-driven
        (XA, estimate requests), Trello-first otherwise. Mirrors
        memory's project_hygiene_clickable_titles config."""
        EMAIL_FIRST = {
            "xa_gap", "xa_apology", "estimate_request_overdue",
            "estimate_pending_ack",
        }
        if rule in EMAIL_FIRST:
            return {"kind": "email",
                    "url": "https://outlook.office.com/mail/inbox"}
        return {"kind": "trello", "url": "https://trello.com/"}

    def navigate(self, panel_key, args=None):
        """Open another (web) panel in a new window. The home shell
        already has all panels mounted in the sidebar, so this just
        opens them in a fresh process via the launcher dispatcher.
        Used for jump-to-Pipeline, jump-to-Snapshot, etc."""
        if not panel_key:
            return False
        try:
            import paths
            paths.spawn_tool(panel_key)
            return True
        except Exception:
            return False

    # ── Poll-based scan progress (subprocess-backed) ────────────────
    def get_scan_progress(self):
        """JS polls this while a scan is running. Reads the subprocess
        status file the worker writes to. No GIL contention with the
        UI process because the scan runs in an entirely separate
        Python interpreter.

        Returns `{running, done, total, name, phase, error}`.
        """
        try:
            import hygiene_scan_worker as _hsw
            status = _hsw._read_status() or {}
        except Exception:
            status = {}
        phase = status.get("phase") or ""
        # Subprocess writes phase=done/error when it exits. Treat
        # anything not "running" as not-running so the JS poll knows
        # to fire the post-scan reload.
        running = (phase == "running")
        # Also clear our own _scan_running flag when subprocess is
        # no longer running, so a fresh Run Scan can be accepted.
        if not running:
            self._scan_running = False
        return {
            "running": running,
            "phase":   phase,
            "done":    int(status.get("done")  or 0),
            "total":   int(status.get("total") or 0),
            "name":    str(status.get("name")  or ""),
            "error":   str(status.get("error") or ""),
        }

    def get_scan_diagnostics(self) -> dict:
        """Diagnostic snapshot the user can share when reporting
        problems. Returns last scan status + error + worker script
        existence + persistence cache age + estimated payload size."""
        info = {"ok": True}
        # Worker script
        worker = os.path.join(_HERE, "hygiene_scan_worker.py")
        info["worker_script"]  = worker
        info["worker_exists"]  = os.path.isfile(worker)
        # Last scan status file
        try:
            import hygiene_scan_worker as _hsw
            info["status_path"] = _hsw.status_path()
            info["last_status"] = _hsw._read_status() or {}
        except Exception as ex:
            info["status_path"] = ""
            info["last_status"] = {"error": str(ex)}
        # Persistence file size (rough proxy for cache bloat)
        try:
            import persistence as _per
            p = _per._path() if hasattr(_per, "_path") else ""
            if p and os.path.isfile(p):
                info["persistence_path"] = p
                info["persistence_kb"]   = round(
                    os.path.getsize(p) / 1024, 1)
        except Exception:
            pass
        # Current cache summary
        try:
            cache = persistence.get_hygiene_scan_cache(
                max_age_minutes=30 * 24 * 60)
            if cache is None:
                info["cache"] = {"empty": True}
            else:
                payload, age = cache
                info["cache"] = {
                    "age_min":     round(age / 60, 1),
                    "hygiene":     len(payload.get("hygiene") or []),
                    "closeout":    len(payload.get("closeout") or []),
                    "xa_apology":  len(payload.get("xa_apology") or []),
                    "xa_gaps":     len(payload.get("xa_gaps") or []),
                    "ipr":         len(payload.get("ipr") or []),
                    "estimates":   len(payload.get("estimates") or []),
                    "weekly":      len(payload.get("weekly") or []),
                }
        except Exception as ex:
            info["cache"] = {"error": str(ex)}
        return info

    def run_adjuster_scan(self, days: int = 14) -> dict:
        """Standalone Outlook inbox scan for adjuster inquiries.
        Was previously fused into the full hygiene scan but the
        Outlook COM walk added 30–60 seconds + memory pressure, so
        it's now opt-in. Spawns a tiny background thread so the
        bridge call returns immediately."""
        if getattr(self, "_adj_running", False):
            return {"started": False, "reason": "adjuster scan already running"}
        self._adj_running = True
        # Stash a result slot the JS can poll for completion.
        self._adj_result = None
        def _bg():
            try:
                import adjuster_monitor as _am
                result = _am.scan_and_post(days=int(days), dry_run=False)
                # adjuster_monitor returns various shapes; coerce to a
                # count + timestamp the JS can show in a toast.
                import datetime as _dt
                self._adj_result = {
                    "ok":         True,
                    "found":      (len(result) if hasattr(result, "__len__")
                                    else 0),
                    "finished_at": _dt.datetime.now().isoformat(timespec="seconds"),
                }
            except Exception as ex:
                self._adj_result = {"ok": False, "error": str(ex)}
            finally:
                self._adj_running = False
        _wh_run_bg(_bg)
        return {"started": True, "days": int(days)}

    def get_adjuster_scan_status(self) -> dict:
        """Polled by the JS button to detect when the inbox scan
        finishes. Returns `{running, result}` — `result` is the dict
        the background thread stashed on completion (or None while
        still running / never run)."""
        return {
            "running": bool(getattr(self, "_adj_running", False)),
            "result":  getattr(self, "_adj_result", None),
        }

    def cancel_scan(self) -> dict:
        """Force-stop a running subprocess scan. Reads the PID from the
        status file, fire-and-forget terminates that process, and
        resets the local running flag + status file so a fresh scan
        can be started.

        FIRE-AND-FORGET kill: earlier version used `subprocess.run`
        which is synchronous — the bridge call hung 1–5 seconds while
        taskkill executed (user-reported "clicked Run Scan and it
        froze" 2026-05-29). Now we use `Popen` and return immediately;
        the killing happens in the OS background.
        """
        try:
            import hygiene_scan_worker as _hsw
            status = _hsw._read_status() or {}
        except Exception:
            status = {}
        pid = status.get("pid")
        if pid:
            try:
                if os.name == "nt":
                    import subprocess as _sp
                    # Popen, NOT run — don't wait for taskkill to finish.
                    _sp.Popen(
                        ["taskkill", "/F", "/T", "/PID", str(pid)],
                        stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
                        creationflags=0x08000000,  # CREATE_NO_WINDOW
                    )
                else:
                    import signal as _sig
                    os.kill(int(pid), _sig.SIGTERM)
            except Exception:
                pass
        # Reset state regardless of whether the kill landed — the
        # status file marks the scan as cancelled, so the next
        # spawn won't reject as "already in progress".
        self._scan_running = False
        try:
            import hygiene_scan_worker as _hsw
            import datetime as _dt
            _hsw._write_status({
                "phase": "cancelled",
                "ended_at": _dt.datetime.now().isoformat(timespec="seconds"),
                "previous_pid": pid or 0,
            })
        except Exception:
            pass
        return {"ok": True, "pid": pid or 0}

    def clear_hygiene_cache(self) -> dict:
        """Wipe the persistence-side hygiene scan cache. Use when the
        cache has grown too large (3000+ items) and is contributing
        to memory pressure. The next scan rebuilds it from scratch."""
        try:
            persistence.set_hygiene_scan_cache(
                [], [], xa_apology=[], xa_gaps=[],
                ipr=[], estimates=[], weekly=[])
            self._cache_grouped = {}
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def run_minimal_scan(self, tab_key: str = "") -> dict:
        """Spawn the scan subprocess in MINIMAL mode — hygiene rules
        only, 50-card cap per board, no side fetches. For diagnosing
        OOM symptoms when the full scan misbehaves."""
        return self._spawn_scan_subprocess(tab_key, mode="minimal")

    # ── Subprocess-based scan (no UI-process GIL contention) ────────
    def run_scan(self, tab_key: str = "") -> dict:
        """Spawn the standalone hygiene_scan_worker process in FULL
        mode. Returns immediately with `{started: True}` — the
        subprocess writes progress to a status file the JS polls.
        """
        return self._spawn_scan_subprocess(tab_key, mode="full")

    def _spawn_scan_subprocess(self, tab_key: str, *, mode: str) -> dict:
        """Shared launcher for both `run_scan` (full) and
        `run_minimal_scan` (hygiene-only). Subprocess isolates the
        scan from the UI process — different interpreter, different
        GIL, different heap. The UI process stays responsive
        regardless of how much work the scan does.
        """
        # Defensive coercion — pywebview's bridge has been observed to
        # pass non-string args when the JS side accidentally bound the
        # click handler so the Event object becomes the first arg
        # (serializes to {} → dict → Popen "expected str, not dict").
        # The JS is also fixed but this catches any future regression.
        if not isinstance(tab_key, str):
            tab_key = ""
        if not isinstance(mode, str):
            mode = "full"
        # If a previous subprocess is still running, AUTO-CANCEL it.
        # The user clicking ↻ Run scan / ⚡ Minimal scan again
        # implicitly means "I want a new one" — the prior version
        # rejected with "scan already in progress" and forced the user
        # to find a Cancel button. Now we just clean up.
        try:
            import hygiene_scan_worker as _hsw
            status = _hsw._read_status() or {}
            if status.get("phase") == "running":
                self.cancel_scan()
        except Exception:
            pass
        # Drop the in-memory cache from the previous scan. The Api
        # instance survives iframe reloads, so the previous scan's
        # _cache_grouped (up to 200 items × 20 sections = ~4000 dicts)
        # would otherwise sit in the bridge process holding memory the
        # OS could be reclaiming. We're about to overwrite it anyway.
        self._cache_grouped = {}
        self._cache_age_minutes = None
        # Launch the subprocess.
        try:
            import subprocess as _sp
            import sys as _sys
            script = os.path.join(_HERE, "hygiene_scan_worker.py")
            if not os.path.isfile(script):
                return {"started": False,
                        "reason": "hygiene_scan_worker.py missing"}
            kwargs = {}
            if _sys.platform.startswith("win"):
                CREATE_NO_WINDOW = 0x08000000
                DETACHED_PROCESS = 0x00000008
                kwargs["creationflags"] = CREATE_NO_WINDOW | DETACHED_PROCESS
            if getattr(_sys, "frozen", False):
                cmd = [_sys.executable, "--hygiene-scan",
                       tab_key or "", mode]
            else:
                cmd = [_sys.executable, script,
                       tab_key or "", mode]
            # Write an initial "running" status SYNCHRONOUSLY before
            # spawning the subprocess. This closes a race window where
            # the JS-side runScan does location.reload() (OOM defense
            # — drops the iframe's accumulated heap) before the worker
            # has had time to write its own first status. Without this,
            # the post-reload get_scan_progress sees an empty/stale
            # status and falls through to the CTA, making the user
            # think the click did nothing.
            try:
                import hygiene_scan_worker as _hsw
                import datetime as _dt
                _hsw._write_status({
                    "phase":      "running",
                    "started_at": _dt.datetime.now().isoformat(timespec="seconds"),
                    "mode":       mode,
                    "done":       0,
                    "total":      0,
                    "name":       "Starting subprocess…",
                })
            except Exception:
                pass
            _sp.Popen(cmd, **kwargs)
            self._scan_running = True
            return {"started": True, "mode": mode}
        except Exception as ex:
            return {"started": False, "reason": str(ex)}

    # Legacy in-process scan (kept as a manual fallback if the
    # subprocess approach proves unreliable in the user's environment).
    # Triggered only when someone explicitly calls
    # `run_scan_in_process` from the JS console.
    def run_scan_in_process(self, tab_key: str = ""):
        """Trigger a fresh hygiene scan on a background thread. Same
        backend the Tk panel uses — `trello_hygiene.scan_all_in_scope`
        + the closeout watcher + XA apology + estimate requests etc.
        Caches the result via persistence.set_hygiene_scan_cache so
        subsequent views (web AND Tk) pick it up.

        Fires window.evaluate_js events:
          • hygiene:scan-progress {done, total, name}
          • hygiene:scan-done     {ok, count, error}
        """
        if getattr(self, "_scan_running", False):
            return {"started": False, "reason": "scan already in progress"}
        self._scan_running = True

        def _bg():
            try:
                import trello_hygiene as _th
                import closeout_watcher as _cw  # optional
            except Exception as ex:
                self._emit_done(ok=False,
                                error=f"hygiene import failed: {ex}")
                self._scan_running = False
                return
            try:
                # No per-card progress events. Pywebview's
                # `evaluate_js` is synchronous from a worker thread
                # — every call round-trips to the UI thread, and
                # under the WebView2 backend those round-trips block
                # the worker AND can stall the UI when several stack
                # up (GC pause, edge background work, etc.). The
                # throttled-event variant still hit this on long
                # scans. Instead we publish progress into a shared
                # Python state slot that the JS polls every second
                # via `get_scan_progress` — pure data over the
                # standard bridge, no JS dispatch from the worker.
                # Tk's hygiene panel uses the same pattern (Tk's
                # after-queue is non-blocking; the web's bridge isn't).
                self._scan_progress = {
                    "done": 0, "total": 0, "name": "Starting…"}
                def _progress(done, total, name):
                    # Just stash — JS polls.
                    try:
                        self._scan_progress = {
                            "done":  int(done or 0),
                            "total": int(total or 0),
                            "name":  str(name or ""),
                        }
                    except Exception:
                        pass
                # Use the optimized scan_workspace (same path Tk uses
                # via hygiene_gui._start_scan). Three reasons this is
                # ~3× faster than the legacy scan_all_in_scope path the
                # web was using:
                #   1. Activity prefilter drops parked-lane cards quiet
                #      >90 days BEFORE any get_card round-trips
                #   2. Bundles hygiene + closeout + xa_gaps + ipr into
                #      ONE get_card per card (legacy called separate
                #      list_pending_closeouts + list_recent_apologies
                #      = 2-3 Trello fetches per card)
                #   3. include_* flags skip whole sections when the
                #      caller is only refreshing one tab
                #
                # Tk's hygiene panel measures full scans at ~30-90s.
                # The legacy path web was using ran 3-5min on the same
                # boards and saturated the UI thread with progress
                # round-trips along the way.
                tab_flags = _htabs.scan_flags_for_tab(tab_key) if tab_key else {}
                # _scan_flags_for_tab returns {'hygiene', 'handoff',
                # 'closeout', 'xa_gaps', 'ipr', 'any_workspace', ...}
                # — translate to scan_workspace's include_* kwargs.
                results = _th.scan_workspace(
                    include_hygiene=bool(tab_flags.get("hygiene", True)),
                    include_handoff=bool(tab_flags.get("handoff", True)),
                    include_closeout=bool(tab_flags.get("closeout", True)),
                    include_xa_gaps=bool(tab_flags.get("xa_gaps", True)),
                    include_ipr=bool(tab_flags.get("ipr", True)),
                    progress_cb=_progress,
                ) or {}
                # Each bucket goes to its own keyword arg on the cache
                # writer — the UI's get_cache reads them by name. The
                # earlier code flattened xa_gaps + ipr into the
                # `hygiene` list, which (a) emptied the XA gaps + IPR
                # sections in the UI and (b) leaked those items into
                # the Hygiene section where their rule keys broke the
                # render. That was the "breaks everything" symptom.
                violations = list(results.get("hygiene") or [])
                closeouts  = list(results.get("closeout") or [])
                xa_gaps    = list(results.get("xa_gaps") or [])
                ipr_rows   = list(results.get("ipr") or [])

                # XA apology rows — not produced by scan_workspace.
                # Match Tk's hygiene_gui flow: pull from ar_followup.
                xa_apology_rows = []
                try:
                    import ar_followup as _arf
                    xa_apology_rows = _arf.find_stale_cards() or []
                except Exception:
                    try:
                        import xa_apology as _xa
                        xa_apology_rows = _xa.list_recent_apologies() or []
                    except Exception:
                        xa_apology_rows = []

                # Weekly check-ins (Estimating board) — Tk pulls these
                # via weekly_checkins.find_due_cards(). Returns [] if
                # the module isn't importable.
                weekly_rows = []
                try:
                    import weekly_checkins as _wc
                    weekly_rows = _wc.find_due_cards() or []
                except Exception:
                    pass

                # Estimate requests — Tk runs detect_pending against
                # the xa_gaps groups + adjuster_monitor's scan output,
                # then reads all_active(). Best-effort.
                estimate_rows = []
                try:
                    import estimate_requests as _er
                    # adjuster_monitor.scan_and_post removed from this
                    # path — see hygiene_scan_worker for rationale. Opt
                    # in via Api.run_adjuster_scan() when you want a
                    # fresh inbox pull.
                    try:
                        _er.detect_pending(xa_gaps, None)
                    except Exception:
                        pass
                    estimate_rows = _er.all_active() or []
                except Exception:
                    pass

                # Cap EVERY bucket at 1000 rows before persisting.
                # An out-of-control Trello board (legacy lane with
                # 4000+ stale cards) used to push the persistence
                # file past 5 MB; reading that back in get_cache
                # piled Python heap allocations and chained into
                # WebView2 OOM. 1000 is well above what a healthy
                # board produces and still leaves the user with
                # plenty to triage. Anything over the cap is
                # silently truncated (newest-first by virtue of
                # scan_workspace's enumeration order).
                CAP = 1000
                try:
                    persistence.set_hygiene_scan_cache(
                        violations[:CAP],
                        closeouts[:CAP],
                        xa_apology=xa_apology_rows[:CAP],
                        xa_gaps=xa_gaps[:CAP],
                        ipr=ipr_rows[:CAP],
                        estimates=estimate_rows[:CAP],
                        weekly=weekly_rows[:CAP],
                    )
                except Exception:
                    pass

                self._emit_done(
                    ok=True,
                    count=(len(violations) + len(closeouts)
                           + len(xa_apology_rows) + len(xa_gaps)
                           + len(ipr_rows) + len(estimate_rows)
                           + len(weekly_rows)))
            except Exception as ex:
                self._emit_done(
                    ok=False,
                    error=f"{type(ex).__name__}: {ex}")
            finally:
                self._scan_running = False

        _wh_run_bg(_bg)
        return {"started": True}

    def _emit_done(self, *, ok, count=0, error=""):
        # Iframe-aware dispatch via web_event so the listener inside
        # the embedded panel actually receives the event.
        try:
            import web_event
            web_event.event(self._window, "hygiene:scan-done",
                            {"ok": ok, "count": count, "error": error})
        except Exception:
            pass


# ── Section + tab structure (mirrors hygiene_gui._SECTIONS / _TABS) ──
# (key, icon, label, description)
_TK_SECTIONS = (
    ("wc_audit_due",      "🗂", "Monthly WC Audit due",          "Surfaces the first Monday of every month."),
    ("weekly",            "📆", "Weekly check-ins due",          "Estimating cards stale 7+ days."),
    ("estimates",         "💰", "Estimate Requests (48h SLA)",   "Adjuster/carrier inquiries; flips red when overdue."),
    ("eq_on_site",        "🔌", "Equipment still on site",       "Air scrubbers / dehus placed with no pickup logged after 3+ days — rental / loss risk."),
    ("lost_job",          "🚪", "Lost jobs — close out",         "Customer went with another firm; the card is still open."),
    ("adjuster_pending",  "📨", "Adjuster inquiries",            "Inbox messages queued for approval before posting."),
    ("xa_inquiries",      "📨", "XA inquiries",                  "Adjuster questions/requests from XA emails; approve to add to the Inquiries & Disputes tracker."),
    ("disputes",          "⚖",  "Inquiries & Disputes (open + overdue)", "Open inquiry/dispute tracker rows."),
    ("concerns",          "🚨", "Customer concerns",             "Complaint / legal / refund / escalation keywords."),
    ("ipr",               "📷", "Initial Photo Report requests", "@mentions asking for the IPR."),
    ("xa_apology",        "🔔", "Apology reminders (XA)",        "AR Board cards needing XA apology note."),
    ("docusketch_needed", "📐", "Docusketch needed (WIP)",       "WIP-lane cards without a Docusketch request yet."),
    ("docusketch",        "📐", "Docusketch pending",            "Requested but zip not yet imported."),
    ("docusign",          "📝", "Docusign pending",              "Paperwork awaiting e-signature or insured email."),
    ("docusign_resends",  "✍",  "Docusign physical-signature SLA", "Resends past 5 days without signature."),
    ("missing_items",     "📋", "Missing",                       "Items flagged missing at any stage."),
    ("xa_gaps",           "📝", "XA gaps (stale + open commitments)", "Stale XA notes / open verbal commitments."),
    ("hygiene",           "⚠",  "Hygiene violations",            "Missing owner, follow-up date, or recent activity."),
    ("handoff",           "🔄", "Lane moves missing handoff",    "New lane move in 24h without handoff note."),
    ("closeout",          "📸", "Ready for Snapshot",            "Cards in SNAPSHOT lane / 'ready for snapshot' comment."),
    ("open_jobs",         "📋", "All open Trello jobs",          "Every in-scope card, aging-first."),
    ("stalled",           "🐌", "Stalled in stage",              "Past per-stage threshold (e.g. 14d Mit / 30d AR)."),
    ("anomalies",         "🚨", "Anomalous jobs",                "3+× the historical median for their stage."),
)

# (tab_key, label, section_keys_tuple) — defined in hygiene_tabs. This
# file kept its own copy alongside hygiene_gui's and the two drifted;
# see that module for what went missing on the Tk side.
_TABS_DEF = _htabs.TABS
_TABS_PAYLOAD = _htabs.TABS_PAYLOAD
_SECTION_TO_TAB = _htabs.SECTION_TO_TAB


# ── Priority-dashboard display sections ──────────────────────────────
# Each tile aggregates one or more backend section keys. `tier` weights
# urgency (0 = most urgent action items → 3 = informational). `feed:
# False` keeps a section OUT of the default unified feed (the demoted
# "All open jobs" catch-all — it's a toggle, not a tile/feed item).
# User-approved 2026-06-10: merge docusketch needed+pending, docusign
# pending+resends, stalled+anomalies; demote open_jobs.
_DISPLAY_SECTIONS = [
    {"key": "estimates",    "icon": "💰", "label": "Estimate Requests",      "keys": ["estimates"],                      "tier": 0},
    {"key": "eq_on_site",   "icon": "🔌", "label": "Equipment on site",      "keys": ["eq_on_site"],                     "tier": 0},
    {"key": "lost_job",     "icon": "🚪", "label": "Lost jobs",              "keys": ["lost_job"],                       "tier": 1},
    {"key": "adjuster",     "icon": "📨", "label": "Adjuster inquiries",     "keys": ["adjuster_pending"],               "tier": 0},
    {"key": "xa_inquiries", "icon": "📨", "label": "XA inquiries",           "keys": ["xa_inquiries"],                   "tier": 0},
    {"key": "disputes",     "icon": "⚖",  "label": "Inquiries & Disputes",   "keys": ["disputes"],                       "tier": 0},
    {"key": "concerns",     "icon": "🚨", "label": "Customer concerns",      "keys": ["concerns"],                       "tier": 0},
    {"key": "ipr",          "icon": "📷", "label": "IPR requests",           "keys": ["ipr"],                            "tier": 1},
    {"key": "xa_apology",   "icon": "🔔", "label": "XA apology",             "keys": ["xa_apology"],                     "tier": 1},
    {"key": "docusketch",   "icon": "📐", "label": "Docusketch",             "keys": ["docusketch_needed", "docusketch"],"tier": 1},
    {"key": "docusign",     "icon": "📝", "label": "Docusign",               "keys": ["docusign", "docusign_resends"],   "tier": 1},
    {"key": "missing_items","icon": "📋", "label": "Missing items",          "keys": ["missing_items"],                  "tier": 1},
    {"key": "wc_audit_due", "icon": "🗂", "label": "WC Audit due",           "keys": ["wc_audit_due"],                   "tier": 1},
    {"key": "weekly",       "icon": "📆", "label": "Weekly check-ins",       "keys": ["weekly"],                         "tier": 1},
    {"key": "hygiene",      "icon": "⚠",  "label": "Trello hygiene",         "keys": ["hygiene"],                        "tier": 2},
    {"key": "handoff",      "icon": "🔄", "label": "Handoff missing",        "keys": ["handoff"],                        "tier": 2},
    {"key": "closeout",     "icon": "📸", "label": "Ready for Snapshot",     "keys": ["closeout"],                       "tier": 2},
    {"key": "stalled",      "icon": "🐌", "label": "Stalled / anomalous",    "keys": ["stalled", "anomalies"],           "tier": 2},
    {"key": "xa_gaps",      "icon": "📝", "label": "XA gaps",                "keys": ["xa_gaps"],                        "tier": 2},
    {"key": "open_jobs",    "icon": "📋", "label": "All open jobs",          "keys": ["open_jobs"],                      "tier": 3, "feed": False},
]
# Reverse map: backend section key → its display tile (for per-row action
# routing + which display section an item belongs to in the feed).
_DISPLAY_BY_SECTION = {sk: d for d in _DISPLAY_SECTIONS for sk in d["keys"]}


def _shape(it):
    """Pick the most-useful fields off a hygiene item for the row UI.

    Field mapping notes:
      • Violations from trello_hygiene emit `card_name` for the client
        title (NOT `client_name`/`name`) — fall back through both so
        non-violation rows (closeout / xa_apology) still work.
      • `detail` carries the human-readable reason (e.g. "Photos
        missing: ATP, CIF"); falls back through note/subtitle/desc
        for non-violation payloads.
      • `card_url` is already populated from Trello's `shortUrl` —
        prefer it over reconstructing from card_id (the shortUrl
        contains the slug so it actually opens the card view).
      • `board_id` must be preserved so the board-filter dropdown
        in the UI works.
      • `body`/`lane`/`board_name` are kept verbatim so per-section
        actions (adjuster inquiry post, etc.) have what they need.
    """
    client = (it.get("client_name") or it.get("client")
              or it.get("name") or it.get("card_name") or "")
    subtitle = (it.get("detail") or it.get("note") or it.get("subtitle")
                or it.get("desc") or it.get("lane") or "")
    card_id = it.get("card_id") or ""
    card_url = it.get("card_url") or ""
    if not card_url and card_id:
        card_url = f"https://trello.com/c/{card_id}"
    base = {
        "client":     client,
        "subtitle":   subtitle,
        "card_id":    card_id,
        "card_url":   card_url,
        "board_id":   it.get("board_id") or "",
        "board_name": it.get("board_name") or it.get("_board_name") or "",
        "lane":       it.get("lane") or "",
        "days":       it.get("days") or it.get("aging_days") or it.get("days_old") or 0,
        # Pass-through fields per-section actions need
        "body":       it.get("body") or "",
        "severity":   it.get("severity") or "",
        # `rule` drives the hygiene-row snooze (dismiss(card_id, rule)).
        "rule":       it.get("rule") or "",
        # Section-specific identifiers — needed by per-row buttons
        # that route to a tracker module other than Trello card_id
        # (missing-items uses request_id, adjuster uses message_id,
        # xa_gap uses group_key, docusign_resends uses request_id).
        "request_id": it.get("request_id") or it.get("id") or "",
        "message_id": it.get("message_id") or "",
        "group_key":  it.get("group_key") or it.get("claim") or "",
    }
    return _jsonify(base)


def main(argv=None):
    api = Api()
    win = webview.create_window(
        title="Hygiene — Linguar Hub (web)",
        url=INDEX_HTML, js_api=api,
        width=1280, height=820, min_size=(720, 500))
    api.attach(win)
    webview.start(debug=False)


if __name__ == "__main__":
    main()
