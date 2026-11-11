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
`render_desc` rewrites ordinary fields line by line and scope fields as
complete text blocks. An untouched line is preserved, so:

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
ACCOUNT   = "ACCOUNT INFO"
TENANT    = "TENANT INFORMATION"
POC       = "POINTS OF CONTACT"
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

    ("poc_name",        POC, "POC NAME", "POC name", True),
    ("poc_role",        POC, "POC ROLE", "POC role / relationship", True),
    ("poc_phone",       POC, "POC PHONE", "POC phone", True),
    ("poc_email",       POC, "POC EMAIL", "POC email", True),
    ("poc_2_name",      POC, "SECOND POC NAME", "Second POC name", True),
    ("poc_2_role",      POC, "SECOND POC ROLE", "Second POC role / relationship", True),
    ("poc_2_phone",     POC, "SECOND POC PHONE", "Second POC phone", True),
    ("poc_2_email",     POC, "SECOND POC EMAIL", "Second POC email", True),

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
    ("loss_categories", PROPERTY,  "LOSS TYPE",           "Loss type",       True),
    ("year_built",      PROPERTY,  "YEAR BUILT",          "Year built",      True),

    # Identifiers, kept beside the links they belong to — the card template
    # has no section for them and this is where anyone would look. Neither
    # key exists on any live card yet; render_desc appends a missing field
    # under its section rather than dropping it.
    ("xa_id",           LINKS,     "XACTANALYSIS ID",        "XA ID",       True),
    ("wc_project_id",   LINKS,     "WORKCENTER PROJECT ID",  "WC Project ID", True),

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

# Fields backed by a real column on `jobs` (schema v6). Everything else —
# the long free text: field/office notes, scope, additional contacts —
# stays in metadata_json, where nobody needs to filter on it.
#
# Only four of these had columns before v6; the rest sat in the JSON blob
# and so could not be filtered, grouped or reported on. The field id and
# the column name match except where the card's wording differs from the
# column's ("cause of loss" is the loss_type column).
COLUMN_FIELDS = {
    "carrier":        "carrier",
    "claim_number":   "claim_number",
    "cause_of_loss":  "loss_type",
    "date_received":  "date_received",
    # v6
    "address":        "address",
    "phone":          "phone",
    "email":          "email",
    "adjuster_name":  "adjuster_name",
    "adjuster_email": "adjuster_email",
    "adjuster_phone": "adjuster_phone",
    "agent_name":     "agent_name",
    "deductible":     "deductible",
    "date_of_loss":   "date_of_loss",
    "xa_id":          "xa_id",
    "wc_project_id":  "wc_project_id",
}

_META_SETTINGS = "settings"     # current values not backed by a column
_META_BASE     = "trello_base"  # what we last synced, for the 3-way merge

_SECTION_RE = re.compile(r"^\*\*([^*]+)\*\*\s*$")
_KV_RE      = re.compile(r"^([A-Za-z][^:]{0,40}):\s*(.*)$")

# Explicit template aliases only. Do not fuzzy-match insurance/customer fields.
_KEY_ALIASES = {(LINKS, "INITIAL DOCUSKETCH LINK"): "DOCUSKETCH LINK"}

# Older commercial cards keep these facts in Account Info above an empty
# customer template. Never borrow tenant/POC fields or insurance details.
_ACCOUNT_FIELDS = ('customer_name', 'address', 'phone', 'email')


def _account_fallbacks(parsed):
    customer, account = parsed.get(CUSTOMER, {}), parsed.get(ACCOUNT, {})
    return {fid: str(account.get(BY_ID[fid][2]) or '').strip()
            for fid in _ACCOUNT_FIELDS
            if not str(customer.get(BY_ID[fid][2]) or '').strip()
            and str(account.get(BY_ID[fid][2]) or '').strip()}


def _section_name(name):
    name = name.strip().upper()
    return SCOPE if name.rstrip(':').strip() in ('SCOPE', 'SCOPE OF WORK') else name


def _scope_blocks(lines):
    """Yield (start, end, field key, value) for the two free-text scope blocks.

    Room labels such as ``Downstairs:`` belong to the scope, not separate
    fields. Section headers, rules, and the next scope field end the block.
    Trailing blank separators are excluded so an edit preserves spacing.
    """
    section, current = None, None
    for index in range(len(lines) + 1):
        line = lines[index].strip() if index < len(lines) else ''
        header = _SECTION_RE.match(line)
        kv = _KV_RE.match(line)
        key = kv.group(1).strip().upper() if kv else None
        scope_start = section == SCOPE and key in ('INITIAL', 'ADDITIONAL')
        if current is not None and (index == len(lines) or header or line == '---' or scope_start):
            start, field_key, first_value = current
            end = index
            while end > start + 1 and not lines[end - 1].strip():
                end -= 1
            value = '\n'.join([first_value, *lines[start + 1:end]]).strip()
            yield start, end, field_key, value
            current = None
        if header:
            section = _section_name(header.group(1))
            if section == SCOPE:
                following = next((s.strip() for s in lines[index + 1:] if s.strip()), '')
                first = _KV_RE.match(following)
                if following and not _SECTION_RE.match(following) and following != '---' and not (
                        first and first.group(1).strip().upper() in ('INITIAL', 'ADDITIONAL')):
                    current = (index, 'INITIAL', '')
        elif scope_start:
            current = (index, key, kv.group(2))


def schema():
    """Field list for the UI, grouped and flagged core/collapsed.

    `options` (when present) are SUGGESTIONS, not a whitelist — the field
    stays free text so a carrier nobody has seen before still types
    through.
    """
    out = []
    for fid, section, key, label, core in FIELDS:
        f = {"id": fid, "section": section, "key": key,
             "label": label, "core": core}
        if section == SCOPE:
            f['multiline'] = True
            f['core'] = True
        if fid == "carrier":
            try:
                import carriers
                f["options"] = carriers.options()
            except Exception:
                pass
        out.append(f)
    return out


# ── reading the card ───────────────────────────────────────────────────

_XA_ID_RE = re.compile(r"[?&]ddid=([A-Za-z0-9]+)", re.I)


def xa_id_from_link(link):
    """The assignment id embedded in an XactAnalysis URL.

    Live links look like
    `…/detail.jsp?ddid=06YD7CD&xlink=false&src=#d_clientpolicy`, so the id
    is already on the card — asking someone to retype it, when it is sat
    right there and a typo silently points at the wrong assignment, would
    be a worse field than no field.
    """
    m = _XA_ID_RE.search(str(link or ""))
    return m.group(1) if m else ""


def _legacy_poc(desc):
    """Read explicitly introduced POC blocks, without consuming customer facts.

    Return a customer-parser view with contact-owned lines removed. Original
    Trello text is never changed by this read operation.
    """
    result, retained = {}, []
    section, contact = '', 0
    for raw in (desc or '').splitlines():
        line = raw.strip().replace('\\*', '*').replace('**', '').strip()
        header = _SECTION_RE.match(raw.strip())
        start = re.fullmatch(r'(?:POC|POINT OF CONTACT)\s*:\s*(.+)', line, re.I)
        next_person = re.fullmatch(r'([^:()]+?)\s*\(([^()]+)\)\s*(?:POC)?', line, re.I) if contact else None
        if start and section == CUSTOMER:
            contact += 1
            if contact <= 2:
                prefix = 'poc_' if contact == 1 else 'poc_2_'
                result[prefix + 'name'] = start[1].strip()
            continue
        if header and not start and ':' not in line:
            section = _section_name(header[1])
            contact = 0
        if line == '---' or re.match(r'(?:Additional Contacts|Customer Name|Address|Source of Lead)\s*:', line, re.I):
            contact = 0
        if next_person and section == CUSTOMER:
            contact += 1
            if contact <= 2:
                prefix = 'poc_' if contact == 1 else 'poc_2_'
                result[prefix + 'name'] = next_person[1].strip()
                result[prefix + 'role'] = next_person[2].strip()
            continue
        if contact and section == CUSTOMER:
            prefix = 'poc_' if contact == 1 else 'poc_2_'
            email = re.match(r'(?:E-?mail)\s*:\s*(.*)', line, re.I)
            phone = re.match(r'(?:Number|Phone(?: Number)?)\s*:\s*(.*)', line, re.I)
            if email:
                value = re.search(r'[A-Za-z0-9.!#$%&\x27+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', email[1])
                if value and contact <= 2: result[prefix + 'email'] = value[0]
                continue
            if phone or re.fullmatch(r'[+()\d][\d() .+\-]{6,}(?:\s*(?:ext|x)\.?\s*\d+)?', line, re.I):
                if contact <= 2: result[prefix + 'phone'] = phone[1].strip() if phone else line
                continue
        retained.append(raw)
    return '\n'.join(retained), result


def from_card(desc):
    """Card description text -> {field_id: value}."""
    import trello_client as tc
    customer_view, legacy_poc = _legacy_poc(desc)
    parsed = tc.parse_card_desc(customer_view) or {}
    parsed = {_section_name(section): fields for section, fields in parsed.items()}
    for (section, alias), key in _KEY_ALIASES.items():
        fields = parsed.get(section, {})
        # An explicitly empty canonical field is a clear, not a fallback.
        if key not in fields and alias in fields:
            fields[key] = fields[alias]
    for _start, _end, key, value in _scope_blocks((desc or '').splitlines()):
        parsed.setdefault(SCOPE, {})[key] = value
    out = {}
    for fid, section, key, _label, _core in FIELDS:
        out[fid] = ((parsed.get(section) or {}).get(key) or "").strip()
    out.update(_account_fallbacks(parsed))
    for fid, value in legacy_poc.items():
        # Explicit modern fields, including intentional clears, win.
        if BY_ID[fid][2] not in parsed.get(POC, {}):
            out[fid] = value
    # Derive the XA id from the link when the card carries no explicit one.
    # Never overwrite a value someone typed: a hand-entered id beats one
    # parsed out of a URL that may point at a superseded assignment.
    if not out.get("xa_id"):
        out["xa_id"] = xa_id_from_link(out.get("link_xa"))
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

    # Edit/clear the field we actually displayed, not just its empty duplicate.
    # Otherwise clearing a customer field would resurrect the Account value.
    import trello_client as tc
    original_fields = tc.parse_card_desc(original) or {}
    account_edits = set(_account_fallbacks(original_fields))
    for fid in _ACCOUNT_FIELDS:
        key = BY_ID[fid][2]
        account_value = str(original_fields.get(ACCOUNT, {}).get(key) or '').strip()
        if account_value and account_value == str(original_fields.get(CUSTOMER, {}).get(key) or '').strip():
            account_edits.add(fid)
    for fid in account_edits:
        if fid in ids:
            key = BY_ID[fid][2]
            want[(ACCOUNT, key)] = (key, values.get(fid) or '')

    lines = (original or '').splitlines()
    seen = set()
    # Replace the whole old block, not just its first line. The same block
    # boundaries serve the reader and writer, including explicit clears.
    for start, end, key, _old in reversed(list(_scope_blocks(lines))):
        hit = want.get((SCOPE, key))
        if hit is not None:
            if _SECTION_RE.match(lines[start].strip()):
                lines[start:end] = [lines[start], str(hit[1])]
            else:
                label = lines[start].split(':', 1)[0]
                lines[start:end] = [f'{label}: {hit[1]}'.rstrip()]
            seen.add((SCOPE, key))

    adjuster_continuations = (tc.adjuster_continuation_lines(lines)
                              if (INSURANCE, 'ADJUSTER NAME') in want else set())
    out, cur = [], None
    for index, raw in enumerate(lines):
        if index in adjuster_continuations:
            continue
        line = raw.strip()
        header = tc.description_section_header(line)
        if header:
            cur = _section_name(header)
            out.append(raw)
            continue
        kv = _KV_RE.match(line)
        if kv and cur is not None:
            key = kv.group(1).strip().upper()
            key = _KEY_ALIASES.get((cur, key), key)
            hit = want.get((cur, key))
            if hit is not None and cur != SCOPE:
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
    import trello_client as tc
    for (section, key), (label, value) in missing.items():
        idx = None
        for i, raw in enumerate(lines):
            header = tc.description_section_header(raw)
            if header and _section_name(header) == section:
                idx = i
                continue
            if idx is not None and header:
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


def display_values(rec, desc=''):
    """Preview never-imported facts without replacing saved or cleared values."""
    facts = stored_values(rec)
    meta = _meta_of(rec)
    saved = meta.get(_META_SETTINGS) or {}
    base = meta.get(_META_BASE) or {}
    recorded = set(saved) | set(base)
    descriptions = [desc] if isinstance(desc, str) else desc
    candidates = [from_card(text) for text in descriptions if text]
    # Multiple placements may share a job; only preview facts they agree on.
    preview = {}
    for key in BY_ID:
        values = {item.get(key) for item in candidates if item.get(key)}
        if len(values) == 1:
            preview[key] = values.pop()
    for key, value in preview.items():
        # A stored blank matching a stored blank baseline is unchanged, so a
        # value newly observed on the exact card can be previewed. A clear
        # against a non-empty baseline remains an intentional local edit.
        unchanged_blank = (key in saved and key in base and
                           not str(saved.get(key) or '').strip() and
                           not str(base.get(key) or '').strip())
        if (key not in recorded or unchanged_blank) and not facts.get(key):
            facts[key] = value
    return facts


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


def inherited_values(canon_key, child_rec):
    """A child's effective values: its own where set, the client's otherwise.

    Carrier, adjuster and deductible are nearly always shared across a
    property's units — retyping them six times for Avana Springs would be
    absurd and would drift. Date of loss and claim number usually differ,
    so anything typed on the child WINS and is stored as an override.

    A value equal to the parent's is not stored as an override, so
    correcting the client later flows down to every unit that never
    disagreed with it.
    """
    parent = stored_values(_record(canon_key) or {})
    own = _meta_of(child_rec).get(_META_SETTINGS) or {}
    out, inherited = {}, []
    for fid in BY_ID:
        v = (own.get(fid) or "").strip()
        if v:
            out[fid] = v
        else:
            out[fid] = (parent.get(fid) or "").strip()
            if out[fid]:
                inherited.append(fid)
    return out, inherited, parent


def _uninitialized(rec):
    meta = _meta_of(rec)
    recorded = set(meta.get(_META_SETTINGS) or {}) | set(meta.get(_META_BASE) or {})
    return not (recorded & BY_ID.keys()) and not any(stored_values(rec).values())


def load(canon_key, child_name="", *, refresh=True, exact_card_id="", initialize_missing=False):
    """Current values for a job (or child), merged with its Trello card.

    Pulls the card ONCE — about half a second — because syncing all 300
    carded jobs would be over two minutes of API calls.
    """
    rec = _record(canon_key, child_name)
    if rec is None:
        return {"ok": False, "error": "job not found"}

    import card_insurance
    if card_insurance.enabled() and not child_name:
        if not exact_card_id:
            values=card_insurance.overlay(stored_values(rec),{})
            return {'ok':True,'canon_key':canon_key,'values':values,'conflicts':[],
                    'synced':False,'source':'database','error':'Open an EMS, Contents or Recon card to edit insurance details.'}
        values,context,pending=card_insurance.load_editor(rec,exact_card_id,stored_values(rec),
            fetch_missing=bool(refresh or initialize_missing))
        if refresh or initialize_missing:
            card = card_insurance.source_card(exact_card_id)
            parsed_contacts = from_card(card.get('desc') or '')
            saved_contacts = _meta_of(rec).get(_META_SETTINGS) or {}
            for fid in BY_ID:
                if fid.startswith('poc_') and fid not in saved_contacts:
                    values[fid] = parsed_contacts.get(fid, '')
        return {'ok':True,'canon_key':canon_key,'card_id':exact_card_id,'values':values,
                'insurance_context':context,'insurance_pending':pending,'conflicts':[],
                'synced':False,'source':'database','error':''}

    if child_name:
        mine, inherited, _parent = inherited_values(canon_key, rec)
        card_id = _card_id(rec, canon_key, child_name)
        if not card_id:
            # No card of its own — which is every child on live data. The
            # client's card describes the client, not this unit, so merging
            # it in here would overwrite the unit's own claim and DOL with
            # the parent's on every open.
            return {"ok": True, "canon_key": canon_key,
                    "child_name": child_name, "card_id": "",
                    "values": mine, "inherited": inherited,
                    "conflicts": [], "synced": False, "error": ""}

    mine = stored_values(rec)
    card_id = exact_card_id or _card_id(rec, canon_key, child_name)
    out = {"ok": True, "canon_key": canon_key, "child_name": child_name,
           "card_id": card_id, "values": mine, "conflicts": [],
           "synced": False, "error": ""}
    out['loss_categories_explicit'] = 'loss_categories' in (_meta_of(rec).get(_META_SETTINGS) or {})
    first_load = bool(initialize_missing and exact_card_id and not child_name and _uninitialized(rec))
    if not refresh and not first_load:
        out.update(source='database', refresh_pending=bool(card_id),
                   conflicts=list(_meta_of(rec).get('trello_import_conflicts') or []))
        # Existing jobs predate the POC fields. The normal editor intentionally
        # skips whole-job refreshes, but must still preview new contact fields.
        saved = _meta_of(rec).get(_META_SETTINGS) or {}
        missing_poc = [fid for fid in BY_ID if fid.startswith('poc_') and fid not in saved]
        missing_customer = any(not mine.get(fid) for fid in _ACCOUNT_FIELDS)
        missing_adjuster = not mine.get('adjuster_name')
        if initialize_missing and exact_card_id and not child_name and (missing_poc or missing_customer or missing_adjuster):
            try:
                import trello_client as tc
                card = tc.get_card_lite(exact_card_id) or {}
                contacts = from_card(card.get('desc') or '')
                for fid in missing_poc:
                    out['values'][fid] = contacts.get(fid, '')
                out['poc_source'] = 'linked Trello card preview'
                preview_ids = {fid for fid in BY_ID if not fid.startswith('poc_') and fid != 'loss_categories'}
                if any(contacts.get(fid) for fid in preview_ids):
                    # Preview only. Three-way merge protects saved local edits,
                    # including intentional clears against a nonempty baseline.
                    preview, conflicts = merge(stored_base(rec), mine, contacts)
                    for fid in preview_ids:
                        out['values'][fid] = preview[fid]
                    out['conflicts'] += [c for c in conflicts if c['id'] in preview_ids]
                    out['customer_source'] = 'linked Trello description preview'
            except Exception:
                out['error'] = 'POC details could not load from the linked Trello card. Reopen Job info to retry.'
        return out
    if not card_id:
        # No card: the Hub IS the record. Not an error — 115 of 415 jobs
        # and every child are in this state.
        return out

    try:
        import trello_client as tc
        # Only the desc is read — get_card_lite, not the whole card.
        desc = (tc.get_card_lite(card_id) or {}).get("desc") or ""
    except Exception as ex:
        if first_load:
            out.update(ok=False, error='Job info has not been imported yet and Trello could not be reached. Retry before editing.')
            return out
        # Offline or Trello down: show what we have rather than nothing.
        out["error"] = f"couldn't reach Trello ({ex}); showing local values"
        return out

    theirs = from_card(desc)
    merged, conflicts = merge(stored_base(rec), mine, theirs)
    out.update({"values": merged, "conflicts": conflicts, "synced": True,
                "card_desc": desc})
    if first_load:
        out['source'] = 'verified_card_preview'
    return out


def pull_from_card(canon_key, card_id):
    """Merge a newly pinned card into the Hub without writing back to it.

    Repinning is a corrective import boundary. Values that are blank or still
    equal to the prior Trello baseline may advance; a Hub edit that disagrees
    with the newly selected card stays in place and is returned as a conflict.
    The baseline advances only for non-conflicting fields so the disagreement
    remains reviewable after the card is reopened.
    """
    import card_insurance
    if card_insurance.enabled():
        return {'ok':False,'error':'Card-specific insurance import is not enabled in this Dev preview. No shared job facts were overwritten.','conflicts':[]}
    rec = _record(canon_key)
    if rec is None:
        return {"ok": False, "error": "job not found", "conflicts": []}
    card_id = str(card_id or "").strip()
    if not card_id:
        return {"ok": False, "error": "Trello card is missing", "conflicts": []}
    try:
        import trello_client as tc
        desc = (tc.get_card_lite(card_id) or {}).get("desc") or ""
    except Exception as ex:
        return {"ok": False,
                "error": f"couldn't read the pinned Trello card ({ex})",
                "conflicts": []}

    mine = stored_values(rec)
    base = stored_base(rec)
    theirs = from_card(desc)
    merged, conflicts = merge(base, mine, theirs)
    conflict_ids = {item["id"] for item in conflicts}
    next_base = {
        fid: (base.get(fid) if fid in conflict_ids else theirs.get(fid, ""))
        for fid in BY_ID
    }
    meta = _meta_of(rec)
    meta[_META_SETTINGS] = merged
    meta[_META_BASE] = next_base
    if conflicts:
        meta["trello_import_conflicts"] = conflicts
    else:
        meta.pop("trello_import_conflicts", None)
    _persist(canon_key, "", merged, meta)
    imported = [fid for fid in BY_ID
                if merged.get(fid, "") != mine.get(fid, "")]
    return {"ok": True, "card_id": card_id, "imported": imported,
            "imported_count": len(imported), "conflicts": conflicts}


def save(canon_key, values, child_name="", card_desc="", *, edited_only=False, exact_card_id="", insurance_context=None, _shared_only=False):
    """Persist values, then push the changed fields to the card.

    THE DATABASE IS THE SOURCE OF TRUTH. Two things follow from that, and
    both are load-bearing:

    1. The local write happens FIRST — genuinely first, before any
       network call.
       It used to run at the end, after the push, so a crash or a hang
       mid-push lost the edit entirely. The docstring claimed otherwise,
       which is how it went unnoticed.

    2. Where the Hub and the card disagree, the HUB WINS. That is the
       point of a source of truth. But it is reported rather than silent:
       `clobbered` lists fields where the card had been changed by
       somebody else since our last sync and we overwrote them, so the
       overwrite is visible instead of being discovered later.

    If Trello is unreachable the local save still stands and the push is
    reported as pending — losing the edit because a network call failed
    would be the worst outcome.
    """
    import ems_db
    rec = _record(canon_key, child_name)
    if rec is None:
        return {"ok": False, "error": "job not found"}

    import card_insurance
    if card_insurance.enabled() and not child_name and not _shared_only:
        insurance={k:str(v or '').strip() for k,v in (values or {}).items() if k in card_insurance.FIELDS}
        shared={k:v for k,v in (values or {}).items() if k not in card_insurance.FIELDS}
        saved=None
        if insurance:
            saved=card_insurance.save_editor(rec,exact_card_id,insurance,insurance_context)
        result=save(canon_key,shared,card_desc=card_desc,edited_only=True,
                    exact_card_id=exact_card_id,_shared_only=True)
        if saved:
            result['insurance_context']={k:saved[k] for k in ('job_id','card_key','section','revision')}
            result['insurance_pending']=True
            result['pending_push']=True
            result['changed']=list(dict.fromkeys(result.get('changed',[])+list(insurance)))
            result['error']='Insurance saved in OneLoss for this card. Trello insurance sync is not enabled in this Dev preview.'
        return result

    values = {k: (v or "").strip() for k, v in (values or {}).items()
              if k in BY_ID}
    if edited_only and not values:
        return {"ok": True, "changed": [], "wrote_to_card": [],
                "pushed": False, "pending_push": False, "error": ""}
    # Canonicalize the carrier on the way in, so "state farm" and
    # "State Farm" stop being two carriers. Unknown names pass through
    # untouched — see carriers.normalize.
    if "carrier" in values:
        try:
            import carriers
            values["carrier"] = carriers.normalize(values["carrier"])
        except Exception:
            pass
    meta = _meta_of(rec)

    if child_name:
        # Store only what DISAGREES with the client. A value equal to the
        # parent's is inheritance, not an override — keeping it would
        # freeze a stale copy, so correcting the client later would leave
        # every unit still showing the old carrier.
        effective, _inh, parent = inherited_values(canon_key, rec)
        overrides = dict(meta.get(_META_SETTINGS) or {}) if edited_only else {}
        for fid, value in values.items():
            if value and value != (parent.get(fid) or ""):
                overrides[fid] = value
            else:
                overrides.pop(fid, None)
        changed = [fid for fid, v in values.items()
                   if v != (effective.get(fid) or "")]
        meta[_META_SETTINGS] = overrides
        _persist(canon_key, child_name, values, meta)
        return {"ok": True, "changed": changed, "wrote_to_card": [],
                "pushed": False, "pending_push": False, "error": "",
                "overrides": sorted(overrides)}

    before = stored_values(rec)
    if edited_only and exact_card_id and card_desc and _uninitialized(rec):
        # Commit the displayed first-load facts only when the user saves an
        # edit. Never mirror untouched preview values back to Trello.
        before = from_card(card_desc)
        meta[_META_BASE] = dict(before)
    changed = [fid for fid, v in values.items() if v != before.get(fid, "")]
    settings = {fid: values.get(fid, before.get(fid, "")) for fid in BY_ID}
    if edited_only and 'loss_categories' not in values and 'loss_categories' not in (meta.get(_META_SETTINGS) or {}):
        settings.pop('loss_categories', None)
    meta[_META_SETTINGS] = settings

    # ── DB FIRST ──────────────────────────────────────────────────────
    # Before the network is touched at all. The baseline is written again
    # after a successful push (it can only advance to something we KNOW
    # the card holds), but the values themselves are safe from here on.
    _persist(canon_key, child_name, values, meta)

    card_id = exact_card_id or _card_id(rec, canon_key, child_name)
    pushed, push_error, wrote, clobbered = False, "", [], []
    if card_id:
        try:
            import trello_client as tc
            desc = card_desc or (tc.get_card_lite(card_id) or {}).get("desc") or ""
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
            # DB-first editors submit only touched fields. Unknown or stale
            # untouched values must not erase newer information in Trello.
            wrote = [fid for fid in (values if edited_only else settings)
                     if (settings.get(fid) or "") != (on_card.get(fid) or "")]
            # Which of those had somebody ELSE changed on the card since
            # our last sync? The Hub still wins — that is what a source of
            # truth means — but overwriting another person's edit without
            # saying so is how a card quietly loses work.
            base = stored_base(rec)
            clobbered = [
                {"id": fid, "label": BY_ID[fid][3],
                 "was": (on_card.get(fid) or ""),
                 "now": (settings.get(fid) or "")}
                for fid in wrote
                if base and (on_card.get(fid) or "") != (base.get(fid) or "")
            ]
            if not wrote:
                # Card already says what we do. Nothing to send, and the
                # baseline is now known-good.
                pushed = True
                meta[_META_BASE] = ({**stored_base(rec), **{fid: on_card.get(fid, '') for fid in values}}
                                    if edited_only else on_card)
            else:
                new_desc = render_desc(desc, settings, changed_ids=wrote)
                if tc.update_card_desc(card_id, new_desc):
                    pushed = True
                    # The baseline is only ever what we KNOW the card holds.
                    # Advancing it on a failed push would make the next merge
                    # read our unsent edit as already agreed and silently
                    # discard whatever the card said.
                    synced = from_card(new_desc)
                    meta[_META_BASE] = ({**stored_base(rec), **{fid: synced.get(fid, '') for fid in values}}
                                        if edited_only else synced)
        except Exception as ex:
            push_error = f"{type(ex).__name__}: {ex}"

    # Second write: only the baseline can have moved, and only when the
    # push succeeded. Cheap, and it keeps the merge honest.
    if pushed:
        _persist(canon_key, child_name, values, meta)
    return {"ok": True, "changed": changed, "wrote_to_card": wrote,
            "pushed": pushed,
            "pending_push": bool(card_id and (values if edited_only else wrote) and not pushed),
            "clobbered": clobbered,
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
    ems_db.update_job(canon_key, metadata=meta,
                      clear_fields=[col for col, value in cols.items() if value == ''], **cols)
