"""New-loss intake: parse a carrier assignment email and clone the matching
Trello "New Loss" template into the active department's WORK IN PROGRESS board.

Flow (driven by the audit "🆕 New Loss" dialog):
  1. parse_assignment_email(raw)  → normalized field dict (editable in the UI).
  2. list_templates()             → the Water / Fire / Property template cards
                                    on the active dept's WIP board.
  3. create_new_loss(payload)     → clone the chosen template into the intake
                                    list (bottom), fill its templated desc from
                                    the fields, name it, return {card_id,url}.

Everything is department-aware: templates + boards resolve from config.load()
(the active department's trello_workspace_id), so OC and IE each get their own.
"""

import re


# ── Assignment-email parser ────────────────────────────────────────────────
# Carrier XA dispatch emails are flat "Label:    value" lines. The label is
# always the text before the FIRST colon; values may themselves contain colons
# (times, coordinates), so we split on the first colon only. We key off a known
# label set so section headers / map junk lines never become fields.
_LABELS = {
    "type":                                "assignment_type",
    "claim rep":                           "adjuster_name",
    "adjuster":                            "adjuster_name",
    "adjuster name":                       "adjuster_name",
    "claim rep email":                     "adjuster_email",
    "adjuster email":                      "adjuster_email",
    "claim rep phone":                     "adjuster_number",
    "adjuster phone":                      "adjuster_number",
    "adjuster number":                     "adjuster_number",
    "date of loss":                        "date_of_loss",
    "claim number":                        "claim_number",
    "policy number":                       "policy_number",
    "insured name":                        "insured_name",
    "insured":                             "insured_name",
    "mobile phone":                        "phone",
    "home phone":                          "phone",
    "phone":                               "phone",
    "phone number":                        "phone",
    "email address":                       "email",
    "email":                               "email",
    "type of loss":                        "type_of_loss",
    "cause of loss":                       "type_of_loss",
    "xa id":                               "xa_id",
    "deductible":                          "deductible",
    "agent name":                          "agent_name",
    "agent":                               "agent_name",
    "year built":                          "year_built",
    "location of property":                "address",
    "property address":                    "address",
    "loss address":                        "address",
    "loss details":                        "loss_details",
    "assignment received by xactanalysis": "date_received_raw",
    "notification sent":                   "notification_sent_raw",
}

_DATE_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def parse_assignment_email(text):
    """Return a normalized {key: value} dict from a carrier assignment email.

    Unknown lines are ignored. Missing fields simply don't appear — the UI
    shows every field as an editable row so the office fills the gaps."""
    text = text or ""
    f = {}

    # Carrier from the "From: <Carrier> - Servpro ..." header.
    m = re.search(r"^\s*From:\s*(.+)$", text, re.I | re.M)
    if m:
        frm = m.group(1).strip()
        carrier = re.split(r"\s*-\s*servpro", frm, flags=re.I)[0].strip()
        carrier = re.split(r"\s*(?:<|\()", carrier)[0].strip()
        if carrier:
            f["carrier"] = carrier

    for line in text.splitlines():
        if ":" not in line:
            continue
        label, _, val = line.partition(":")
        key = _LABELS.get(label.strip().lower())
        if not key:
            continue
        val = val.strip()
        if not val:
            continue
        f.setdefault(key, val)

    # An adjuster email sometimes trails the Claim Rep line or sits on its own
    # line right after it — if we caught a name but no email, grab the first
    # address that isn't the insured's.
    if f.get("adjuster_name") and not f.get("adjuster_email"):
        insured_email = (f.get("email") or "").lower()
        for em in _EMAIL_RE.findall(text):
            if em.lower() != insured_email:
                f["adjuster_email"] = em
                break

    # Clean date received down to the date portion.
    raw = f.get("date_received_raw") or f.get("notification_sent_raw") or ""
    dm = _DATE_RE.search(raw)
    if dm:
        f["date_received"] = dm.group(0)

    # Loss narrative → field notes; XA id noted for office reference.
    if f.get("loss_details"):
        f["field_notes"] = f["loss_details"]

    return f


def loss_type_from(type_of_loss):
    """Map a carrier 'Type of Loss' string to a template kind: water|fire|
    property. Defaults to water (the most common EMS loss)."""
    s = (type_of_loss or "").strip().lower()
    if any(w in s for w in ("fire", "smoke", "soot")):
        return "fire"
    if any(w in s for w in ("property", "mgmt", "management")):
        return "property"
    return "water"


def suggest_card_name(fields):
    """Card-name suggestion matching the WIP board convention '<Insured> -
    <Carrier>'. The insured name is left as-received (the office can reorder
    in the dialog)."""
    insured = (fields.get("insured_name") or "").strip()
    carrier = (fields.get("carrier") or "").strip()
    if insured and carrier:
        return f"{insured} - {carrier}"
    return insured or carrier or ""


# ── Board / template / list resolution (department-aware) ──────────────────
def _wip_board():
    """The active department's WORK IN PROGRESS board dict, or None."""
    import trello_client as tc
    for b in tc.list_boards():
        if "work in progress" in (b.get("name") or "").lower():
            return b
    return None


def list_templates():
    """Return {water,fire,property: {id,name}} — the template cards on the WIP
    board's TEMPLATES list. Missing kinds are absent from the dict.

    Also returns the resolved board + intake list under '_board' / '_intake'
    so the caller can create without re-resolving."""
    import trello_client as tc
    board = _wip_board()
    if not board:
        return {}
    bid = board["id"]
    lists = tc._call(f"/boards/{bid}/lists",
                     params={"fields": "id,name", "filter": "open"}) or []
    intake = None
    for l in lists:
        if "new loss" in (l.get("name") or "").lower():
            intake = l
            break
    cards = tc._call(f"/boards/{bid}/cards",
                     params={"fields": "id,name,isTemplate", "filter": "all"}) or []
    out = {"_board": board, "_intake": intake}
    for c in cards:
        if not c.get("isTemplate"):
            continue
        nm = (c.get("name") or "").lower()
        if "water" in nm:
            out.setdefault("water", {"id": c["id"], "name": c["name"]})
        elif "fire" in nm or "smoke" in nm:
            out.setdefault("fire", {"id": c["id"], "name": c["name"]})
        elif "property" in nm:
            out.setdefault("property", {"id": c["id"], "name": c["name"]})
    return out


# Which parsed field feeds each (SECTION, FIELD) slot in the template desc.
_DESC_MAP = {
    ("CUSTOMER INFORMATION", "CUSTOMER NAME"):      "insured_name",
    ("CUSTOMER INFORMATION", "ADDRESS"):            "address",
    ("CUSTOMER INFORMATION", "PHONE NUMBER"):       "phone",
    ("CUSTOMER INFORMATION", "EMAIL"):              "email",
    ("CUSTOMER INFORMATION", "ADDITIONAL CONTACTS"): "additional_contacts",
    ("INSURANCE INFORMATION", "INSURANCE COMPANY"): "carrier",
    ("INSURANCE INFORMATION", "CLAIM NUMBER"):      "claim_number",
    ("INSURANCE INFORMATION", "ADJUSTER NAME"):     "adjuster_name",
    ("INSURANCE INFORMATION", "ADJUSTER EMAIL"):    "adjuster_email",
    ("INSURANCE INFORMATION", "ADJUSTER NUMBER"):   "adjuster_number",
    ("INSURANCE INFORMATION", "DEDUCTIBLE"):        "deductible",
    ("INSURANCE INFORMATION", "AGENT NAME"):        "agent_name",
    ("PROPERTY DETAILS", "YEAR BUILT"):             "year_built",
    ("PROPERTY DETAILS", "DATE OF LOSS"):           "date_of_loss",
    ("PROPERTY DETAILS", "DATE RECEIVED"):          "date_received",
    ("NOTES", "FIELD NOTES"):                       "field_notes",
    ("NOTES", "OFFICE NOTES"):                      "office_notes",
}

_SECTION_RE = re.compile(r"^\*\*([^*]+)\*\*\s*$")
_KV_RE = re.compile(r"^([A-Za-z][^:]{0,40}):\s*(.*)$")


def fill_template_desc(template_desc, fields):
    """Return the template desc with each known field slot filled in, leaving
    the template's section structure and any unmapped lines untouched."""
    out = []
    cur = None
    for raw in (template_desc or "").splitlines():
        s = raw.strip()
        sm = _SECTION_RE.match(s)
        if sm:
            cur = sm.group(1).strip().upper()
            out.append(raw)
            continue
        km = _KV_RE.match(s)
        if km and cur is not None:
            fld = km.group(1).strip().upper()
            key = _DESC_MAP.get((cur, fld))
            val = (fields.get(key) or "").strip() if key else ""
            if val:
                out.append(f"{km.group(1).strip()}: {val}")
                continue
        out.append(raw)
    return "\n".join(out)


def create_new_loss(fields, loss_type=None, *, pin=True):
    """Clone the chosen template into the intake list (bottom), fill its desc
    from `fields`, name it, and (optionally) pin it to the insured so the audit
    picks it up. Returns {ok, card_id, url, name} or {ok:False, error}."""
    import trello_client as tc

    fields = dict(fields or {})
    loss_type = (loss_type or loss_type_from(fields.get("type_of_loss"))).lower()

    # NOTE: the XA ID and every LINKS field (Xactanalysis / CompanyCam / video
    # links) are deliberately NOT written to the card — the office supplies
    # those links manually outside this flow. The XA ID is parsed only so it
    # shows in the dialog for reference.

    tmpls = list_templates()
    if not tmpls:
        return {"ok": False, "error": "No WORK IN PROGRESS board / templates "
                                      "found for the active department."}
    src = tmpls.get(loss_type)
    if not src:
        return {"ok": False,
                "error": f"No '{loss_type}' template on the board."}
    intake = tmpls.get("_intake")
    if not intake:
        return {"ok": False, "error": "No 'New Loss' intake list on the board."}

    name = (fields.get("card_name") or suggest_card_name(fields)
            or src["name"]).strip()

    try:
        card = tc._call("/cards", method="POST", data={
            "idList":         intake["id"],
            "idCardSource":   src["id"],
            "keepFromSource": "all",     # checklists, labels, desc, attachments
            "name":           name,
            "pos":            "bottom",  # land at the bottom of the lane
        })
    except Exception as ex:
        return {"ok": False, "error": f"Card create failed: {ex}"}

    card_id = card.get("id")
    # Fill the templated desc from the fields (the clone starts with the blank
    # template desc; overwrite with the populated one).
    try:
        full = tc.get_card(card_id) or {}
        desc = fill_template_desc(full.get("desc") or "", fields)
        if desc:
            tc._call(f"/cards/{card_id}", method="PUT", data={"desc": desc})
    except Exception:
        pass  # card exists; desc fill is best-effort

    if pin:
        try:
            import persistence
            insured = (fields.get("insured_name") or name).strip()
            if insured:
                persistence.set_trello_card_ids(insured, [card_id])
        except Exception:
            pass

    return {
        "ok":      True,
        "card_id": card_id,
        "url":     card.get("shortUrl") or card.get("url") or "",
        "name":    name,
        "list":    intake.get("name", ""),
        "template": src["name"],
    }
