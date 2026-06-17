"""Shared audit PDF export — job picker + PDF generator."""
import os
import json as _json
import tkinter as tk
from tkinter import messagebox
from datetime import datetime, timedelta, date as _date
from theme import BG, WHITE, GREEN, GREEN_DARK, TEXT_DARK, BORDER, FLAG_RED
from ui_buttons import done_button
import theme as _theme

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (SimpleDocTemplate, Paragraph,
                                 Spacer, Table, TableStyle)

import paths

DOWNLOADS     = os.path.join(os.environ["USERPROFILE"], "Downloads")  # still used by callers for Docusketch
_OUTPUT_DIR   = paths.DATA_DIR  # audit log + PDF save under %APPDATA%
_BACKLOG_FILE = paths.data("audit_backlog.json")
_BACKLOG_MD   = paths.data("EMS_Audit_Backlog.md")


# ── Backlog (persistent per-job history) ─────────────────────────────────────

def _week_start(dt=None):
    """Return the Monday of the given datetime's week as 'YYYY-MM-DD'."""
    d = (dt or datetime.today()).date()
    return (d - timedelta(days=d.weekday())).isoformat()


def load_audit_backlog():
    """Return the backlog dict {last_updated, jobs:[...]} or {jobs:[]} if none."""
    try:
        with open(_BACKLOG_FILE, encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        return {"jobs": []}


def get_audit_count_index():
    """Return a dict {(folder, unit_lower): audit_count} built from the
    backlog. Used by the audit panel to render a "↻ Nx" repeat-offender
    badge so chronic flagged jobs are visually obvious — Bridgette
    Miles flagged for 150 audits in a row should look different from a
    job flagged for the first time."""
    idx = {}
    try:
        data = load_audit_backlog()
    except Exception:
        return idx
    for j in data.get("jobs", []):
        folder = (j.get("folder") or "").strip()
        unit   = (j.get("unit") or "").strip().lower()
        if not folder:
            continue
        cnt = j.get("audit_count", 0)
        # If multiple legacy entries collide on the same (folder, unit)
        # because old data lacks unit info, keep the highest count.
        prev = idx.get((folder, unit), 0)
        if cnt > prev:
            idx[(folder, unit)] = cnt
    return idx


def get_stale_flagged_jobs(days=7):
    """Return a list of backlog entries that are flagged AND haven't
    been audited in `days`+ days. Surfaced as a banner in the audit
    panel so jobs that fell off the daily run-doc but were never
    resolved don't get forgotten."""
    out = []
    try:
        data = load_audit_backlog()
    except Exception:
        return out
    cutoff = (datetime.today() - timedelta(days=days)).isoformat()
    for j in data.get("jobs", []):
        if j.get("status") != "FLAG":
            continue
        if (j.get("last_audited") or "") >= cutoff:
            continue
        out.append(j)
    out.sort(key=lambda j: j.get("last_audited", ""), reverse=True)
    return out


def update_audit_backlog(results):
    """
    Upsert every job in `results` into audit_backlog.json.
    Re-audited jobs move to the current week; their issues are refreshed.
    Also regenerates EMS_Audit_Backlog.md.
    """
    try:
        with open(_BACKLOG_FILE, encoding="utf-8") as f:
            data = _json.load(f)
        jobs = data.get("jobs", [])
    except Exception:
        data = {}
        jobs = []

    # ── One-shot migration: audit_count → per-day ────────────────────
    # Before 2026-05-18, audit_count bumped once PER RUN. The user runs
    # the audit many times per day (jumping around the workflow), so
    # counts inflated into the hundreds. New logic bumps once per
    # calendar day. Rescale the existing counts at migration time so
    # the badges read sensibly today — divide by 5 (a reasonable runs-
    # per-day estimate) and round up. Marked complete via
    # `audit_count_schema_v` so the rescale only runs once.
    if data.get("audit_count_schema_v", 0) < 2:
        for j in jobs:
            old = int(j.get("audit_count", 0) or 0)
            if old > 1:
                # Ceiling division keeps a 1-run job at 1 and a 200-run
                # job at 40 — closer to a real "days outstanding" count.
                j["audit_count"] = max(1, -(-old // 5))
        data["audit_count_schema_v"] = 2

    now  = datetime.today()
    week = _week_start(now)

    # Dedup by resolved (FOLDER, UNIT), not by client string. Same
    # folder gets audited under different client spellings — "Antonio
    # Garcia" from the run-doc, "Antoino Garcia" if a typo, "Garcia
    # Antonio" when the snapshot's full-sweep feeds folder names back
    # as clients — all three are one job. Unit is part of the key so
    # multi-unit properties (Keystone-Highland Village Unit 168 vs
    # Unit 182) don't collapse into a single entry — they share the
    # property folder but are genuinely separate jobs. Client is the
    # fallback when no folder was resolved.
    def _key(c, f, u):
        unit = (u or "").strip().lower()
        if f:
            return f"folder::{f}::unit::{unit}"
        return f"client::{c}::unit::{unit}"

    by_key = {}
    for j in jobs:
        k = _key(j.get("client", ""), j.get("folder", ""), j.get("unit", ""))
        # If two stale entries collide on the same folder key, the
        # newer one (by last_audited) wins so we don't lose audit_count
        # progress when collapsing legacy duplicates.
        prior = by_key.get(k)
        if prior is None or (j.get("last_audited", "") >
                              prior.get("last_audited", "")):
            by_key[k] = j

    today_date = now.strftime("%Y-%m-%d")
    for r in results:
        client = r["client"]
        folder = r.get("folder") or ""
        unit   = r.get("unit") or ""
        k = _key(client, folder, unit)
        entry = by_key.get(k, {"client": client, "audit_count": 0})
        # Capture the prior audit date BEFORE we overwrite last_audited
        # below — we only bump audit_count when this job hasn't been
        # counted today yet (one bump per calendar day, not per run).
        prior_date = (entry.get("last_audited") or "")[:10]
        entry["unit"]        = unit
        # Refresh client display string to whatever this run used —
        # the run-doc spelling is closer to what the user types into
        # search than a folder-name fallback.
        entry["client"]      = client
        entry["folder"]      = folder or client
        entry["status"]      = "FLAG" if r["flagged"] else "OK"
        entry["form_issues"] = r.get("form_issues") or []
        entry["photo_issues"]= r.get("photo_issues") or []
        entry["note_issues"] = r.get("note_issues") or []
        entry["missing"]     = r.get("missing") or []
        entry["aging"]       = r.get("aging", 0)
        last = r.get("last")
        entry["last_active"] = last.isoformat() if isinstance(last, datetime) else (last or "")
        entry["new_loss"]    = r.get("new_loss", False)
        entry["found"]       = r.get("found", True)
        entry["week_start"]  = week
        entry["last_audited"]= now.isoformat()
        # One bump per calendar day per job — the user re-runs audits
        # many times (jumping around the workflow), so per-run bumps
        # inflated audit_count into the hundreds. Per-day matches the
        # intent: how many DAYS has this job been outstanding.
        if prior_date != today_date:
            entry["audit_count"] = entry.get("audit_count", 0) + 1
        by_key[k]            = entry

    all_jobs = list(by_key.values())

    # Prune entries that haven't been audited in over 90 days — keeps the
    # backlog from growing unbounded over years
    cutoff_iso = (now - timedelta(days=90)).isoformat()
    all_jobs = [j for j in all_jobs if j.get("last_audited", "") >= cutoff_iso]

    all_jobs.sort(key=lambda j: j.get("last_audited", ""), reverse=True)

    out = {
        "last_updated": now.isoformat(),
        "audit_count_schema_v": data.get("audit_count_schema_v", 2),
        "jobs": all_jobs,
    }
    try:
        with open(_BACKLOG_FILE, "w", encoding="utf-8") as f:
            _json.dump(out, f, indent=2)
    except OSError:
        pass

    _write_backlog_md(all_jobs, now)


def _week_label(ws):
    try:
        d = _date.fromisoformat(ws)
        return f"Week of {d.strftime('%B %d, %Y')}"
    except Exception:
        return ws or "Unknown Week"


def _write_backlog_md(jobs, now=None):
    """Regenerate EMS_Audit_Backlog.md grouped by week, newest week first."""
    now = now or datetime.today()
    week_groups = {}
    for j in jobs:
        ws = j.get("week_start", "")
        week_groups.setdefault(ws, []).append(j)

    lines = [
        "# EMS Audit Backlog",
        "",
        f"_Last updated: {now.strftime('%A %m/%d/%Y  %I:%M %p')}_",
        "",
    ]

    for ws in sorted(week_groups.keys(), reverse=True):
        group    = week_groups[ws]
        flagged  = [j for j in group if j["status"] == "FLAG"]
        ok_jobs  = [j for j in group if j["status"] == "OK"]

        lines.append(f"## {_week_label(ws)}")
        lines.append("")

        if flagged:
            lines.append("### ⚠ Flagged")
            lines.append("")
            for j in flagged:
                cnt = j.get("audit_count", 1)
                suffix = f" _(audited {cnt}×)_" if cnt > 1 else ""
                lines.append(f"**{j['client']}**{suffix}")
                for fi in (j.get("form_issues") or []):
                    lines.append(f"- ☐ {fi}")
                for pi in (j.get("photo_issues") or []):
                    lines.append(f"- ☐ {pi}")
                for ni in (j.get("note_issues") or []):
                    lines.append(f"- ☐ {ni}")
                for m in (j.get("missing") or []):
                    lines.append(f"- ☐ Empty folder: {m}")
                lines.append("")

        if ok_jobs:
            lines.append("### ✓ OK")
            lines.append("")
            for j in ok_jobs:
                lines.append(f"- {j['client']}")
            lines.append("")

        lines.append("---")
        lines.append("")

    try:
        with open(_BACKLOG_MD, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except OSError:
        pass


# ── Colours ──────────────────────────────────────────────────────────────────
_GREEN  = colors.Color(0/255,   166/255,  81/255)
_RED    = colors.Color(192/255,  57/255,  43/255)
_ORANGE = colors.Color(230/255, 126/255,  34/255)
_LGRAY  = colors.Color(0.93, 0.93, 0.93)
_DGRAY  = colors.Color(0.5,  0.5,  0.5)

# ── Markdown log ─────────────────────────────────────────────────────────────

def write_audit_md(results, run_date="", source="", trello_notes=""):
    """
    Prepend a new audit entry to EMS_Audit_Log.md in the scripts folder.
    Returns the path to the log file.
    """
    now = datetime.today().strftime("%A %m/%d/%Y  %I:%M %p")
    flagged_list = [r for r in results if r["flagged"]]
    ok_list      = [r for r in results if not r["flagged"]]

    parts = [now]
    if run_date:
        parts.append(f"doc: {run_date}")
    if source:
        parts.append(source)

    lines = []
    lines.append(f"# EMS Audit — {' · '.join(parts)}")
    lines.append(
        f"**{len(results)} jobs · {len(flagged_list)} flagged · {len(ok_list)} OK**")
    lines.append("")

    if flagged_list:
        lines.append("## ⚠ Flagged")
        lines.append("")
        for r in flagged_list:
            name = r["client"]
            if r.get("folder") and r["folder"].lower() != r["client"].lower():
                name += f" ({r['folder']})"
            if r.get("found") is False:
                name += " — folder not found"
            lines.append(f"### {name}")
            for fi in (r.get("form_issues") or []):
                lines.append(f"- ☐ {fi}")
            for pi in (r.get("photo_issues") or []):
                lines.append(f"- ☐ {pi}")
            for ni in (r.get("note_issues") or []):
                lines.append(f"- ☐ {ni}")
            for m in (r.get("missing") or []):
                lines.append(f"- ☐ Empty folder: {m}")
            if r.get("new_loss"):
                lines.append("- ☐ New loss — setup not complete yet")
            if r.get("aging", 0) >= 3 and r.get("found", True):
                ls = r["last"].strftime("%m/%d/%y") if r.get("last") else "never"
                lines.append(f"- ⚠ {r['aging']}d inactive (last: {ls})")
            if trello_notes and r.get("is_current"):
                lines.append("")
                lines.append("<details>")
                lines.append("<summary>Trello Comments</summary>")
                lines.append("")
                lines.append("```")
                lines.append(trello_notes.strip())
                lines.append("```")
                lines.append("")
                lines.append("</details>")
            lines.append("")

    if ok_list:
        lines.append("## ✓ OK")
        lines.append("")
        for r in ok_list:
            lines.append(f"- {r['client']}")
        lines.append("")

    lines.append("---")
    new_block = "\n".join(lines)

    md_path = os.path.join(_OUTPUT_DIR, "EMS_Audit_Log.md")
    existing = ""
    if os.path.isfile(md_path):
        try:
            with open(md_path, "r", encoding="utf-8") as f:
                existing = f.read().strip()
        except OSError:
            pass

    content = new_block + ("\n\n" + existing if existing else "")
    try:
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError:
        pass

    update_audit_backlog(results)
    return md_path


# ── Job-picker window ─────────────────────────────────────────────────────────

def open_export_window(parent, results, run_date="", on_close=None):
    """Open job-selection dialog then generate the PDF."""
    if not results:
        messagebox.showinfo("Nothing to Export", "No jobs to export.", parent=parent)
        if on_close:
            on_close()
        return

    win = tk.Toplevel(parent)
    win.title("Export Audit PDF")
    win.geometry("560x600")
    win.configure(bg=BG)
    win.resizable(False, True)
    win.grab_set()
    win.protocol("WM_DELETE_WINDOW",
                 lambda: (on_close() if on_close else None, win.destroy()))

    # Header
    n_flagged = sum(1 for r in results if r["flagged"])
    n_ok      = len(results) - n_flagged
    hdr = tk.Frame(win, bg=GREEN, pady=12)
    hdr.pack(fill="x")
    tk.Label(hdr, text="Export Audit PDF",
             font=("Fraunces", 15, "bold"), bg=GREEN, fg=WHITE).pack()
    tk.Label(hdr, text=f"{n_flagged} flagged  ·  {n_ok} OK  ·  Uncheck to exclude",
             font=("Segoe UI Variable", 9), bg=GREEN, fg="#B2DFC4").pack(pady=(2, 0))

    # Scrollable job list
    outer = tk.Frame(win, bg=BG, padx=12, pady=8)
    outer.pack(fill="both", expand=True)

    canvas = tk.Canvas(outer, bg=WHITE, highlightthickness=1,
                       highlightbackground=BORDER)
    sb = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
    _theme.style_tk_scrollbar(sb)
    canvas.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    inner = tk.Frame(canvas, bg=WHITE)
    cw = canvas.create_window((0, 0), window=inner, anchor="nw")
    inner.bind("<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>",
        lambda e: canvas.itemconfig(cw, width=e.width))

    def _scroll(e):
        canvas.yview_scroll(-1 * (e.delta // 120), "units")
    canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _scroll))
    canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

    job_vars = []

    # Flagged first, then OK
    for r in sorted(results, key=lambda r: (0 if r["flagged"] else 1)):
        var = tk.BooleanVar(value=True)
        job_vars.append((r, var))

        row = tk.Frame(inner, bg=WHITE, pady=5)
        row.pack(fill="x", padx=8)

        tk.Checkbutton(row, variable=var, bg=WHITE,
                       activebackground=WHITE,
                       selectcolor=WHITE).pack(side="left")

        badge_bg = FLAG_RED if r["flagged"] else GREEN
        tk.Label(row, text="FLAG" if r["flagged"] else " OK ",
                 font=("Segoe UI Variable", 7, "bold"),
                 bg=badge_bg, fg=WHITE, padx=3).pack(side="left", padx=(2, 6))

        name = r["client"]
        if r.get("folder") and r["folder"].lower() != r["client"].lower():
            name += f"  ({r['folder']})"
        if not r.get("found", True):
            name += "  — folder not found"
        tk.Label(row, text=name, font=("Segoe UI Variable", 9, "bold"),
                 bg=WHITE, fg=TEXT_DARK, anchor="w").pack(side="left",
                                                           fill="x", expand=True)

        # Issue bullets for flagged jobs
        if r["flagged"]:
            issues = (list(r.get("form_issues") or [])
                      + list(r.get("photo_issues") or [])
                      + list(r.get("note_issues") or []))
            for m in (r.get("missing") or []):
                issues.append(f"Empty folder: {m}")
            if r.get("new_loss"):
                issues.append("New loss — setup not complete yet")
            if r.get("aging", 0) >= 3 and r.get("found", True):
                last_s = r["last"].strftime("%m/%d/%y") if r.get("last") else "never"
                issues.append(f"{r['aging']}d inactive (last: {last_s})")
            for issue in issues:
                det = tk.Frame(inner, bg=WHITE)
                det.pack(fill="x", padx=36)
                tk.Label(det, text=f"☐  {issue}",
                         font=("Segoe UI Variable", 8), bg=WHITE,
                         fg=FLAG_RED, anchor="w").pack(fill="x")

        tk.Frame(inner, bg=BORDER, height=1).pack(fill="x")

    # Bottom bar
    bot = tk.Frame(win, bg=BG, padx=12, pady=10)
    bot.pack(fill="x")

    sel_var = tk.BooleanVar(value=True)
    def _toggle_all():
        v = sel_var.get()
        for _, jv in job_vars:
            jv.set(v)
    tk.Checkbutton(bot, text="Select All", variable=sel_var,
                   font=("Segoe UI Variable", 9), bg=BG, activebackground=BG,
                   selectcolor=WHITE, command=_toggle_all).pack(side="left")

    def _generate():
        chosen = [r for r, v in job_vars if v.get()]
        if not chosen:
            messagebox.showerror("Nothing Selected",
                                 "Select at least one job.", parent=win)
            return
        fname = f"EMS_Audit_{datetime.today().strftime('%m-%d-%Y')}.pdf"
        out   = os.path.join(_OUTPUT_DIR, fname)
        try:
            _build_pdf(chosen, run_date, out)
        except Exception as ex:
            messagebox.showerror("PDF Error", str(ex), parent=win)
            return
        win.destroy()
        if on_close:
            on_close()
        os.startfile(out)

    done_button(bot, "Generate PDF",
                 padx=16, pady=6,
                 command=_generate).pack(side="right")


# ── PDF builder ───────────────────────────────────────────────────────────────

def _build_pdf(results, run_date, out_path):
    today_str = datetime.today().strftime("%B %d, %Y")
    styles    = getSampleStyleSheet()

    def _style(name, **kw):
        return ParagraphStyle(name, parent=styles["Normal"], **kw)

    title_s  = _style("T",  fontSize=17, fontName="Helvetica-Bold",
                      textColor=colors.white, alignment=TA_CENTER)
    sub_s    = _style("Su", fontSize=9,  fontName="Helvetica",
                      textColor=colors.Color(0.7, 0.9, 0.75),
                      alignment=TA_CENTER)
    sec_s    = _style("Se", fontSize=11, fontName="Helvetica-Bold",
                      spaceBefore=8, spaceAfter=4)
    job_s    = _style("J",  fontSize=10, fontName="Helvetica-Bold",
                      textColor=colors.Color(0.1, 0.1, 0.1))
    issue_s  = _style("I",  fontSize=9,  fontName="Helvetica",
                      textColor=_RED,    leftIndent=14, spaceAfter=2)
    aging_s  = _style("A",  fontSize=9,  fontName="Helvetica",
                      textColor=_ORANGE, leftIndent=14, spaceAfter=2)
    ok_s     = _style("O",  fontSize=9,  fontName="Helvetica",
                      textColor=_GREEN,  leftIndent=14)

    doc = SimpleDocTemplate(
        out_path, pagesize=letter,
        leftMargin=0.75*inch, rightMargin=0.75*inch,
        topMargin=0.75*inch,  bottomMargin=0.75*inch,
    )

    story = []

    # ── Header bar ──────────────────────────────────────────────────────────
    hdr = Table([
        [Paragraph("SERVPRO  ·  EMS Audit Report", title_s)],
        [Paragraph(
            f"Run date: {run_date}  ·  Generated {today_str}  ·  {len(results)} jobs",
            sub_s)],
    ], colWidths=[7*inch])
    hdr.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), _GREEN),
        ("TOPPADDING",    (0,0), (-1,0),  14),
        ("BOTTOMPADDING", (0,-1), (-1,-1), 14),
        ("LEFTPADDING",   (0,0), (-1,-1), 16),
        ("RIGHTPADDING",  (0,0), (-1,-1), 16),
    ]))
    story.append(hdr)
    story.append(Spacer(1, 0.18*inch))

    # ── Summary row ─────────────────────────────────────────────────────────
    flagged = [r for r in results if r["flagged"]]
    ok      = [r for r in results if not r["flagged"]]

    summ = Table([[
        Paragraph(f"<b>{len(flagged)}</b> Flagged",
                  _style("SF", fontSize=12, fontName="Helvetica-Bold",
                         textColor=_RED, alignment=TA_CENTER)),
        Paragraph(f"<b>{len(ok)}</b> OK",
                  _style("SO", fontSize=12, fontName="Helvetica-Bold",
                         textColor=_GREEN, alignment=TA_CENTER)),
    ]], colWidths=[3.5*inch, 3.5*inch])
    summ.setStyle(TableStyle([
        ("BOX",           (0,0), (-1,-1), 0.5, _LGRAY),
        ("INNERGRID",     (0,0), (-1,-1), 0.5, _LGRAY),
        ("TOPPADDING",    (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ("BACKGROUND",    (0,0), (0,0), colors.Color(1, 0.95, 0.95)),
        ("BACKGROUND",    (1,0), (1,0), colors.Color(0.94, 1, 0.96)),
    ]))
    story.append(summ)
    story.append(Spacer(1, 0.22*inch))

    # ── Job block helper ─────────────────────────────────────────────────────
    def _job_block(r):
        badge = "FLAG" if r["flagged"] else " OK "
        bc    = _RED if r["flagged"] else _GREEN

        name = r["client"]
        if r.get("folder") and r["folder"].lower() != r["client"].lower():
            name += f"  ({r['folder']})"
        if not r.get("found", True):
            name += "  — folder not found"

        badge_p = Paragraph(
            f'<font color="white"><b>{badge}</b></font>',
            _style("B2", fontSize=8, fontName="Helvetica-Bold",
                   backColor=bc, alignment=TA_CENTER))

        hdr_t = Table([[badge_p, Paragraph(name, job_s)]],
                      colWidths=[0.55*inch, 6.45*inch])
        hdr_t.setStyle(TableStyle([
            ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
            ("LEFTPADDING",   (0,0), (-1,-1), 4),
            ("RIGHTPADDING",  (0,0), (-1,-1), 4),
            ("TOPPADDING",    (0,0), (-1,-1), 5),
            ("BOTTOMPADDING", (0,0), (-1,-1), 5),
            ("BACKGROUND",    (0,0), (-1,-1), _LGRAY),
            ("BOX",           (0,0), (-1,-1), 0.5, colors.Color(0.8,0.8,0.8)),
        ]))

        block = [hdr_t]
        has_issue = False

        for fi in (r.get("form_issues") or []):
            block.append(Paragraph(f"  ☐  {fi}", issue_s))
            has_issue = True
        for pi in (r.get("photo_issues") or []):
            block.append(Paragraph(f"  ☐  {pi}", issue_s))
            has_issue = True
        for ni in (r.get("note_issues") or []):
            block.append(Paragraph(f"  ☐  {ni}", issue_s))
            has_issue = True
        if r["aging"] >= 3 and r.get("found", True):
            ls = r["last"].strftime("%m/%d/%y") if r["last"] else "never"
            block.append(Paragraph(f"  ⚠  {r['aging']}d inactive (last: {ls})",
                                   aging_s))
            has_issue = True
        if not has_issue:
            block.append(Paragraph("  ✓  All items complete", ok_s))

        block.append(Spacer(1, 0.08*inch))
        return block

    # ── Sections ─────────────────────────────────────────────────────────────
    if flagged:
        sec = sec_s.clone("SF2"); sec.textColor = _RED
        story.append(Paragraph("Flagged Jobs", sec))
        for r in flagged:
            story.extend(_job_block(r))
        story.append(Spacer(1, 0.12*inch))

    if ok:
        sec = sec_s.clone("SO2"); sec.textColor = _GREEN
        story.append(Paragraph("OK Jobs", sec))
        for r in ok:
            story.extend(_job_block(r))

    # ── Footer ───────────────────────────────────────────────────────────────
    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(_DGRAY)
        canvas.drawString(0.75*inch, 0.38*inch,
            f"SERVPRO EMS Audit  ·  {today_str}  ·  Confidential")
        canvas.drawRightString(7.75*inch, 0.38*inch, f"Page {doc.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
