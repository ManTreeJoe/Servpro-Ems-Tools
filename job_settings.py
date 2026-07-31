"""Job settings — one editable record per job, synced both ways with Trello.

Job facts (carrier, claim number, date of loss, adjuster…) have only ever
lived in the Trello card's DESCRIPTION, as a templated block of
`**SECTION**` headers and `Key: value` lines. Snapshot re-parses that text
every time it needs a carrier, and `ems_db.jobs` has had empty
claim_number / carrier / loss_type / status / date_received columns since
it was built — 0 of 415 rows populated.

This module makes that record editable in the Hub and keeps it in step
with the card.

Two-way, per FIELD
------------------
`merge()` is a three-way merge against the values we last synced, not a
last-write-wins on the whole card. If a colleague adds the claim number in
Trello while you set the carrier here, both land. Only when the SAME field
changed on both sides does it report a conflict for a human to settle.
Whole-card resolution would silently eat one side's edit — on a shared
board that is a matter of when, not if.

Writing back without losing anything
------------------------------------
`render_desc` rewrites the description LINE BY LINE. A line we did not
change is emitted byte-identical, so:

  * fields the UI never shows (tenant block, scope of work) survive,
  * markdown the office typed by hand survives — emails arrive as
    `[addr](mailto:addr)` and stay that way unless you edit them,
  * anything the parser doesn't recognise is passed through untouched
    rather than dropped.

Regenerating the description from a template instead would be far simpler
and would quietly delete every one of those.
"""
import json
import re

# Card sections, in template order.
CUSTOMER  = "CUSTOMER INFORMATION"
TENANT    = "TENANT INFORMATION"
INSURANCE = "INSURANCE INFORMATION"
PROPERTY  = "PROPERTY DETAILS"
LINKS     = "LINKS"
NOTES     = "NOTES"
SCOPE     = "SCOPE OF WORK:"

# (id, section, card key, label, core?)
#
# `core` decides what the editor shows up front. It is a DISPLAY choice
# only — everything here round-trips either way, and unlisted card fields
# survive untouched, so a collapsed field is never a field at risk.
#
# Which are core came from sampling live cards: tenant, agent name and
# scope of work were empty on every one, so they collapse.
FIELDS = [
    ("customer_name",   CUSTOMER,  "CUSTOMER NAME",       "Customer name",   True),
    ("address",         CUSTOMER,  "ADDRESS",             "Address",         True),
    ("phone",           CUSTOMER,  "PHONE NUMBER",        "Phone",           True),
    ("email",           CUSTOMER,  "EMAIL",               "Email",           True),
    ("source_of_lead",  CUSTOMER,  "SOURCE OF LEAD",      "Source of lead",  True),
    ("addl_contacts",   CUSTOMER,  "ADDITIONAL CONTACTS", "Other contacts",  False),

    ("tenant_name",     TENANT,    "NAME",                "Tenant name",     False),
    ("tenant_phone",    TENANT,    "PHONE NUMBER",        "Tenant phone",    False),
    ("tenant_email",    TENANT,    "EMAIL",               "Tenant email",    False),

    ("carrier",         INSURANCE, "INSURANCE COMPANY",   "Carrier",         True),
    ("claim_number",    INSURANCE, "CLAIM NUMBER",        "Claim #",         True),
    ("adjuster_name",   INSURANCE, "ADJUSTER NAME",       "Adjuster",        True),
    ("adjuster_email",  INSURANCE, "ADJUSTER EMAIL",      "Adjuster email",  True),
    ("adjuster_phone",  INSURANCE, "ADJUSTER NUMBER",     "Adjuster phone",  True),
    ("deductible",      INSURANCE, "DEDUCTIBLE",          "Deductible",      True),
    ("agent_name",      INSURANCE, "AGENT NAME",          "Agent",           False),
    ("inspection_fee",  INSURANCE, "INSPECTION FEE (SELF PAY)",
                                                          "Inspection fee",  False),

    ("date_of_loss",    PROPERTY,  "DATE OF LOSS",        "Date of loss",    True),
    ("date_received",   PROPERTY,  "DATE RECEIVED",       "Date received",   True),
    ("cause_of_loss",   PROPERTY,  "CAUSE OF LOSS",       "Cause of loss",   True),
    ("year_built",      PROPERTY,  "YEAR BUILT",          "Year built",      True),

    ("link_xa",         LINKS,     "EMS XACTANALYSIS LINK",  "XactAnalysis", True),
    ("link_companycam", LINKS,     "COMPANYCAM LINK",        "CompanyCam",   True),
    ("link_docusketch", LINKS,     "DOCUSKETCH LINK",        "Docusketch",   True),
    ("link_video",      LINKS,     "INITIAL VIDEO LINK",     "Initial video", True),
    ("link_post_video", LINKS,     "POST VIDEO LINK",        "Post video",   False),
    ("link_prev_loss",  LINKS,     "PREVIOUS LOSS LINK",     "Previous loss", False),
    ("link_packout_xa", LINKS,     "PACK OUT XACTANALYSIS LINK",
                                                             "Pack-out XA",  False),

    ("field_notes",     NOTES,     "FIELD NOTES",         "Field notes",     False),
    ("office_notes",    NOTES,     "OFFICE NOTES",        "Office notes",    False),

    ("scope_initial",   SCOPE,     "INITIAL",             "Scope: initial",  False),
    ("scope_additional", SCOPE,    "ADDITIONAL",          "Scope: extra",    False),
]

BY_ID = {f[0]: f for f in FIELDS}

# The four with real columns on `jobs`. Everything else lives in
# metadata_json beside them — the columns existed and were never filled,
# so this finally uses them rather than adding more.
COLUMN_FIELDS = {
    "carrier":       "carrier",
    "claim_number":  "claim_number",
    "cause_of_loss": "loss_type",
    "date_received": "date_received",
}

_META_SETTINGS = "settings"     # current values not backed by a column
_META_BASE     = "trello_base"  # what we last synced, for the 3-way merge

_SECTION_RE = re.compile(r"^\*\*([^*]+)\*\*\s*$")
_KV_RE      = re.compile(r"^([A-Za-z][^:]{0,40}):\s*(.*)$")


def schema():
    """Field list for the UI, grouped and flagged core/collapsed."""
    out = []
    for fid, section, key, label, core in FIELDS:
        out.append({"id": fid, "section": section, "key": key,
                    "label": label, "core": core})
    return out


# ── reading the card ───────────────────────────────────────────────────

def from_card(desc):
    """Card description text -> {field_id: value}."""
    import trello_client as tc
    parsed = tc.parse_card_desc(desc or "") or {}
    out = {}
    for fid, section, key, _label, _core in FIELDS:
        out[fid] = ((parsed.get(section) or {}).get(key) or "").strip()
    return out


# ── three-way merge ────────────────────────────────────────────────────

def merge(base, mine, theirs):
    """Per-field 3-way merge.

    base   — values at the last sync
    mine   — what the Hub holds now
    theirs — what the card holds now

    Returns (merged, conflicts). A conflict is a field both sides changed
    to DIFFERENT values; the merged dict keeps `mine` for those so nothing
    is lost while the user decides.
    """
    merged, conflicts = {}, []
    for fid in BY_ID:
        b = (base.get(fid) or "").strip()
        m = (mine.get(fid) or "").strip()
        t = (theirs.get(fid) or "").strip()
        if m == t:
            merged[fid] = m
        elif m == b:                 # only they changed it
            merged[fid] = t
        elif t == b:                 # only we changed it
            merged[fid] = m
        else:                        # both moved, and disagree
            merged[fid] = m
            conflicts.append({"id": fid, "label": BY_ID[fid][3],
                              "base": b, "mine": m, "theirs": t})
    return merged, conflicts


# ── writing the card ───────────────────────────────────────────────────

def render_desc(original, values, changed_ids=None):
    """Rewrite a card description, touching ONLY the fields given.

    `changed_ids` limits the rewrite to fields that actually changed, so
    an untouched line is re-emitted exactly as it was — preserving the
    markdown the office typed (emails arrive as `[a](mailto:a)`) and every
    field this module doesn't model.

    A field that has no line in the card yet is appended under its section
    rather than dropped, so setting a deductible works on a card whose
    template predates that row.
    """
    ids = set(changed_ids if changed_ids is not None else values.keys())
    want = {}
    for fid in ids:
        f = BY_ID.get(fid)
        if f:
            want[(f[1], f[2])] = (f[2], values.get(fid) or "")

    out, cur, seen = [], None, set()
    for raw in (original or "").splitlines():
        line = raw.strip()
        m = _SECTION_RE.match(line)
        if m:
            cur = m.group(1).strip().upper()
            out.append(raw)
            continue
        kv = _KV_RE.match(line)
        if kv and cur is not None:
            key = kv.group(1).strip().upper()
            hit = want.get((cur, key))
            if hit is not None:
                # Keep the card's own label casing — rewriting
                # "Customer Name" as "CUSTOMER NAME" would churn the whole
                # description on the first save.
                out.append(f"{kv.group(1)}: {hit[1]}".rstrip())
                seen.add((cur, key))
                continue
        out.append(raw)

    missing = {k: v for k, v in want.items()
               if k not in seen and (v[1] or "").strip()}
    if missing:
        out = _append_missing(out, missing)
    text = "\n".join(out)
    # splitlines() drops a trailing newline and join() won't put it back,
    # so without this every save leaves a one-character diff — enough to
    # show as an edit in the card's history on a save that changed nothing.
    if (original or "").endswith("\n") and not text.endswith("\n"):
        text += "\n"
    return text


def _append_missing(lines, missing):
    """Add fields that had no line, under their section header."""
    for (section, key), (label, value) in missing.items():
        idx = None
        for i, raw in enumerate(lines):
            m = _SECTION_RE.match(raw.strip())
            if m and m.group(1).strip().upper() == section:
                idx = i
                continue
            if idx is not None and _SECTION_RE.match(raw.strip()):
                break                      # start of the NEXT section
            if idx is not None and raw.strip():
                idx = i                    # last non-blank line in section
        new_line = f"{label.title()}: {value}"
        if idx is None:
            # No such section on this card — add it rather than silently
            # dropping a value the user typed.
            lines = lines + ["", f"**{section}**", "", new_line]
        else:
            lines = lines[:idx + 1] + ["", new_line] + lines[idx + 1:]
    return lines


# ── storage ────────────────────────────────────────────────────────────

def _meta_of(rec):
    md = rec.get("metadata") if isinstance(rec, dict) else None
    if isinstance(md, dict):
        return md
    raw = (rec or {}).get("metadata_json") or ""
    try:
        return json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}


def stored_values(rec):
    """Current Hub-side values for a job or child row."""
    meta = _meta_of(rec)
    saved = meta.get(_META_SETTINGS) or {}
    out = {fid: (saved.get(fid) or "") for fid in BY_ID}
    for fid, col in COLUMN_FIELDS.items():
        col_val = (rec or {}).get(col)
        if (col_val or "").strip():
            out[fid] = str(col_val).strip()
    return out


def stored_base(rec):
    """What we last synced from the card, for the 3-way merge."""
    return dict(_meta_of(rec).get(_META_BASE) or {})


# ── load / save ────────────────────────────────────────────────────────

def _record(canon_key, child_name=""):
    """The job row, or the child row when `child_name` is given."""
    import ems_db
    if child_name:
        for ch in ems_db.children_of(canon_key):
            if (ch.get("name") or "") == child_name:
                return ch
        return None
    return ems_db.get_job(canon_key)


def _card_id(rec, canon_key, child_name=""):
    """A child uses its OWN card when it has one — none of the 139 live
    children does yet, which is why a child's settings are Hub-only until
    someone links one."""
    import ems_db
    if child_name:
        return (rec or {}).get("trello_card") or ""
    links = ems_db.get_links(canon_key, ems_db.LINK_TRELLO)
    return links[0]["link_value"] if links else ""


def load(canon_key, child_name=""):
    """Current values for a job (or child), merged with its Trello card.

    Pulls the card ONCE — about half a second — because syncing all 300
    carded jobs would be over two minutes of API calls.
    """
    rec = _record(canon_key, child_name)
    if rec is None:
        return {"ok": False, "error": "job not found"}

    mine = stored_values(rec)
    card_id = _card_id(rec, canon_key, child_name)
    out = {"ok": True, "canon_key": canon_key, "child_name": child_name,
           "card_id": card_id, "values": mine, "conflicts": [],
           "synced": False, "error": ""}
    if not card_id:
        # No card: the Hub IS the record. Not an error — 115 of 415 jobs
        # and every child are in this state.
        return out

    try:
        import trello_client as tc
        desc = (tc.get_card(card_id) or {}).get("desc") or ""
    except Exception as ex:
        # Offline or Trello down: show what we have rather than nothing.
        out["error"] = f"couldn't reach Trello ({ex}); showing local values"
        return out

    theirs = from_card(desc)
    merged, conflicts = merge(stored_base(rec), mine, theirs)
    out.update({"values": merged, "conflicts": conflicts, "synced": True,
                "card_desc": desc})
    return out


def save(canon_key, values, child_name="", card_desc=""):
    """Persist values and push the changed fields to the card.

    Writes locally FIRST. If Trello is unreachable the local save still
    stands and the push is reported as pending — losing the edit because a
    network call failed would be the worst outcome.
    """
    import ems_db
    rec = _record(canon_key, child_name)
    if rec is None:
        return {"ok": False, "error": "job not found"}

    values = {k: (v or "").strip() for k, v in (values or {}).items()
              if k in BY_ID}
    before = stored_values(rec)
    changed = [fid for fid, v in values.items() if v != before.get(fid, "")]

    meta = _meta_of(rec)
    settings = {fid: values.get(fid, before.get(fid, "")) for fid in BY_ID}
    meta[_META_SETTINGS] = settings

    card_id = _card_id(rec, canon_key, child_name)
    pushed, push_error, wrote = False, "", []
    if card_id:
        try:
            import trello_client as tc
            desc = card_desc or (tc.get_card(card_id) or {}).get("desc") or ""
            on_card = from_card(desc)
            # Diff against what the CARD holds, NOT against our stored copy.
            #
            # Our copy is empty before the first save, so every field looked
            # edited and every line was rewritten. That matters because the
            # parser STRIPS markdown — emails arrive as `[a](mailto:a)`,
            # links as `[XactAnalysis SP > Detail](url)` — so rewriting a
            # field whose value never actually changed still flattened the
            # label somebody typed by hand. Comparing against the card means
            # an unchanged value is never rewritten and its markdown lives.
            wrote = [fid for fid in settings
                     if (settings.get(fid) or "") != (on_card.get(fid) or "")]
            if not wrote:
                # Card already says what we do. Nothing to send, and the
                # baseline is now known-good.
                pushed = True
                meta[_META_BASE] = on_card
            else:
                new_desc = render_desc(desc, settings, changed_ids=wrote)
                if tc.update_card_desc(card_id, new_desc):
                    pushed = True
                    # The baseline is only ever what we KNOW the card holds.
                    # Advancing it on a failed push would make the next merge
                    # read our unsent edit as already agreed and silently
                    # discard whatever the card said.
                    meta[_META_BASE] = from_card(new_desc)
        except Exception as ex:
            push_error = f"{type(ex).__name__}: {ex}"

    _persist(canon_key, child_name, values, meta)
    return {"ok": True, "changed": changed, "wrote_to_card": wrote,
            "pushed": pushed,
            "pending_push": bool(card_id and wrote and not pushed),
            "error": push_error}


def _persist(canon_key, child_name, values, meta):
    import ems_db
    if child_name:
        ems_db.set_child(canon_key, child_name,
                         metadata=meta)
        return
    cols = {}
    for fid, col in COLUMN_FIELDS.items():
        if fid in values:
            cols[col] = values[fid]
    ems_db.upsert_job(display_name=(ems_db.get_job(canon_key) or {})
                      .get("display_name") or canon_key,
                      metadata=meta, **cols)
