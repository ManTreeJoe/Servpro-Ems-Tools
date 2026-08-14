"""Job settings: the 3-way merge and the card-description rewrite.

Both halves are destructive if wrong. A bad merge silently drops a
colleague's edit; a bad rewrite silently deletes fields from a live Trello
card that the office relies on. The tests are weighted accordingly.

The sample description is the real live template — section headers, blank
lines between fields, `---` rules, and an email stored as a markdown
mailto link.
"""
import job_settings as js


CARD = """**CUSTOMER INFORMATION**

Customer Name: Brenda Washburn

Address: 31078 Manford Dr, Winchester, CA 92596

Phone Number: (760) 443-1590

Email: [brenda@yahoo.com](mailto:brenda@yahoo.com "‌")

Additional Contacts:

Source of Lead: Call Center

---

**TENANT INFORMATION**

Name:

Phone Number:

---

**INSURANCE INFORMATION**

Insurance Company: Mercury

Claim Number: ABC-123

Adjuster Name: Pat Jones

Deductible:

---

**PROPERTY DETAILS**

Date of Loss: 05/13/2026

Cause of Loss: Water
"""


# ── merge ──────────────────────────────────────────────────────────────

def test_edits_to_different_fields_both_land():
    """The whole point of merging per field. Whole-card resolution would
    drop one of these."""
    base   = {"carrier": "", "claim_number": ""}
    mine   = {"carrier": "Mercury", "claim_number": ""}
    theirs = {"carrier": "", "claim_number": "ABC-1"}
    merged, conflicts = js.merge(base, mine, theirs)
    assert merged["carrier"] == "Mercury"
    assert merged["claim_number"] == "ABC-1"
    assert conflicts == []


def test_their_change_is_taken_when_we_did_not_touch_it():
    merged, conflicts = js.merge({"carrier": "AAA"}, {"carrier": "AAA"},
                                 {"carrier": "Mercury"})
    assert merged["carrier"] == "Mercury"
    assert conflicts == []


def test_our_change_is_kept_when_they_did_not_touch_it():
    merged, conflicts = js.merge({"carrier": "AAA"}, {"carrier": "Mercury"},
                                 {"carrier": "AAA"})
    assert merged["carrier"] == "Mercury"
    assert conflicts == []


def test_same_edit_on_both_sides_is_not_a_conflict():
    merged, conflicts = js.merge({"carrier": ""}, {"carrier": "Mercury"},
                                 {"carrier": "Mercury"})
    assert merged["carrier"] == "Mercury"
    assert conflicts == []


def test_different_edits_to_one_field_conflict_and_keep_mine():
    """Reported for a human. `mine` is kept meanwhile so nothing is lost
    while the question is open."""
    merged, conflicts = js.merge({"carrier": ""}, {"carrier": "Mercury"},
                                 {"carrier": "AAA"})
    assert merged["carrier"] == "Mercury"
    assert len(conflicts) == 1
    c = conflicts[0]
    assert (c["id"], c["mine"], c["theirs"], c["base"]) == \
        ("carrier", "Mercury", "AAA", "")


def test_a_field_cleared_on_their_side_is_honoured():
    """Deleting a value is an edit too — it must not read as "unchanged"
    and get resurrected from our copy."""
    merged, conflicts = js.merge({"claim_number": "ABC-1"},
                                 {"claim_number": "ABC-1"},
                                 {"claim_number": ""})
    assert merged["claim_number"] == ""
    assert conflicts == []


# ── description rewrite ────────────────────────────────────────────────

def test_rewriting_nothing_is_byte_identical():
    """The strongest guarantee available: if we change no field, the card
    text we send back is exactly what we read."""
    vals = js.from_card(CARD)
    assert js.render_desc(CARD, vals, changed_ids=[]) == CARD


def test_changing_one_field_changes_exactly_one_line():
    vals = js.from_card(CARD)
    vals["deductible"] = "2500"
    out = js.render_desc(CARD, vals, changed_ids=["deductible"])
    before, after = CARD.splitlines(), out.splitlines()
    assert len(before) == len(after)
    diff = [(a, b) for a, b in zip(before, after) if a != b]
    assert diff == [("Deductible:", "Deductible: 2500")]


def test_untouched_markdown_email_survives():
    """Emails are stored as `[addr](mailto:addr)`. Regenerating the card
    from a template would flatten every one of them."""
    vals = js.from_card(CARD)
    vals["carrier"] = "Farmers"
    out = js.render_desc(CARD, vals, changed_ids=["carrier"])
    assert "[brenda@yahoo.com](mailto:brenda@yahoo.com" in out


def test_fields_the_ui_never_shows_survive():
    """Tenant and Source of Lead are collapsed or unlisted; a save must
    not drop them."""
    vals = js.from_card(CARD)
    vals["carrier"] = "Farmers"
    out = js.render_desc(CARD, vals, changed_ids=["carrier"])
    assert "**TENANT INFORMATION**" in out
    assert "Source of Lead: Call Center" in out


def test_label_casing_is_preserved():
    """The card says "Customer Name"; rewriting it as "CUSTOMER NAME"
    would churn the entire description on the first save."""
    vals = js.from_card(CARD)
    vals["customer_name"] = "Someone Else"
    out = js.render_desc(CARD, vals, changed_ids=["customer_name"])
    assert "Customer Name: Someone Else" in out
    assert "CUSTOMER NAME:" not in out


def test_a_field_with_no_line_yet_is_added_under_its_section():
    """Cards predating a template row have no line for it. Dropping the
    value the user typed would be the worst outcome."""
    vals = js.from_card(CARD)
    vals["year_built"] = "1998"
    out = js.render_desc(CARD, vals, changed_ids=["year_built"])
    assert "Year Built: 1998" in out
    body = out.split("**PROPERTY DETAILS**", 1)[1]
    assert "Year Built: 1998" in body      # landed in the right section


def test_a_missing_section_is_created_rather_than_dropped():
    vals = js.from_card(CARD)
    vals["office_notes"] = "called twice"
    out = js.render_desc(CARD, vals, changed_ids=["office_notes"])
    assert "**NOTES**" in out
    assert "Office Notes: called twice" in out


def test_blank_new_value_does_not_append_an_empty_line():
    vals = js.from_card(CARD)
    vals["year_built"] = ""
    out = js.render_desc(CARD, vals, changed_ids=["year_built"])
    assert "Year Built" not in out


def test_parse_reads_the_live_template():
    vals = js.from_card(CARD)
    assert vals["carrier"] == "Mercury"
    assert vals["claim_number"] == "ABC-123"
    assert vals["date_of_loss"] == "05/13/2026"
    assert vals["email"] == "brenda@yahoo.com"     # markdown stripped
    assert vals["deductible"] == ""


# ── storage ────────────────────────────────────────────────────────────

def test_real_columns_win_over_the_json_copy():
    """carrier/claim/cause/date_received have real columns. When both hold
    a value the column is the record."""
    rec = {"carrier": "Mercury", "claim_number": "ABC-1",
           "metadata": {"settings": {"carrier": "STALE",
                                     "adjuster_name": "Pat"}}}
    vals = js.stored_values(rec)
    assert vals["carrier"] == "Mercury"
    assert vals["adjuster_name"] == "Pat"


def test_stored_values_handles_a_row_with_no_metadata():
    vals = js.stored_values({"carrier": "Mercury"})
    assert vals["carrier"] == "Mercury"
    assert vals["adjuster_name"] == ""


def test_base_survives_a_json_string_round_trip():
    rec = {"metadata_json": '{"trello_base": {"carrier": "AAA"}}'}
    assert js.stored_base(rec) == {"carrier": "AAA"}


def test_corrupt_metadata_does_not_raise():
    assert js.stored_base({"metadata_json": "{not json"}) == {}


# ── save: what actually gets written to the card ──────────────────────

class _FakeDB:
    """Minimal ems_db stand-in. No sqlite, no network."""
    def __init__(self):
        self.job = {"canon_key": "k", "display_name": "K", "metadata": {}}
        self.links = [{"link_value": "card1"}]
    LINK_TRELLO = "trello_card"
    def get_job(self, _k): return self.job
    def get_links(self, _k, _t): return self.links
    def children_of(self, _k): return []
    def upsert_job(self, **kw):
        self.job["metadata"] = kw.get("metadata") or {}
        return "k"


def _wire(monkeypatch, desc):
    """Install fake ems_db + trello_client; return (db, sent)."""
    import sys, types
    db = _FakeDB()
    sent = {}
    tc = types.SimpleNamespace(
        # job_settings reads only the desc, so it uses the lean fetch.
        get_card_lite=lambda cid, **kw: {"desc": desc},
        get_card=lambda cid, **kw: {"desc": desc},
        update_card_desc=lambda cid, d: (sent.update(desc=d), {"id": cid})[1],
        parse_card_desc=__import__("trello_client").parse_card_desc,
    )
    monkeypatch.setitem(sys.modules, "ems_db", db)
    monkeypatch.setitem(sys.modules, "trello_client", tc)
    return db, sent


def test_first_save_only_writes_fields_that_differ_from_the_card(monkeypatch):
    """The dangerous case. Our stored copy is EMPTY before the first save,
    so diffing against it made every field look edited and rewrote every
    line — flattening `[addr](mailto:addr)` and
    `[XactAnalysis SP > Detail](url)` into bare text on cards nobody had
    even edited. Diff against the CARD instead."""
    _db, sent = _wire(monkeypatch, CARD)
    vals = js.from_card(CARD)
    vals["deductible"] = "1500"
    res = js.save("k", vals)
    assert res["wrote_to_card"] == ["deductible"]
    before, after = CARD.splitlines(), sent["desc"].splitlines()
    assert [(a, b) for a, b in zip(before, after) if a != b] == \
        [("Deductible:", "Deductible: 1500")]


def test_saving_unchanged_values_sends_nothing(monkeypatch):
    _db, sent = _wire(monkeypatch, CARD)
    res = js.save("k", js.from_card(CARD))
    assert res["wrote_to_card"] == []
    assert "desc" not in sent          # no PUT at all
    assert res["pushed"] is True


def test_markdown_links_survive_a_save(monkeypatch):
    _db, sent = _wire(monkeypatch, CARD)
    vals = js.from_card(CARD)
    vals["carrier"] = "Farmers"
    js.save("k", vals)
    assert "](mailto:brenda@yahoo.com" in sent["desc"]


def test_baseline_is_not_advanced_when_the_push_fails(monkeypatch):
    """If the baseline moved on a failed push, the next merge would read our
    unsent edit as already agreed and silently discard the card's value."""
    import sys, types
    db = _FakeDB()
    tc = types.SimpleNamespace(
        get_card_lite=lambda cid, **kw: {"desc": CARD},
        get_card=lambda cid, **kw: {"desc": CARD},
        update_card_desc=lambda cid, d: (_ for _ in ()).throw(
            OSError("network down")),
        parse_card_desc=__import__("trello_client").parse_card_desc,
    )
    monkeypatch.setitem(sys.modules, "ems_db", db)
    monkeypatch.setitem(sys.modules, "trello_client", tc)

    vals = js.from_card(CARD)
    vals["deductible"] = "1500"
    res = js.save("k", vals)
    assert res["pushed"] is False
    assert res["pending_push"] is True
    assert "trello_base" not in (db.job["metadata"] or {})
    # …and the edit is still saved locally rather than lost to a failed call.
    assert db.job["metadata"]["settings"]["deductible"] == "1500"


# ── child inheritance ─────────────────────────────────────────────────
# Carrier, adjuster and deductible are shared across a property's units;
# claim number and date of loss usually are not. So a child shows the
# client's values until it disagrees, and only the disagreement is stored.

class _FakeDBWithChild(_FakeDB):
    def __init__(self, parent_settings, child_settings=None):
        super().__init__()
        self.job["metadata"] = {"settings": parent_settings}
        self.child = {"name": "Unit 561-I", "parent_canon": "k",
                      "trello_card": "",
                      "metadata": {"settings": child_settings or {}}}
        self.saved = None
    def children_of(self, _k): return [self.child]
    def set_child(self, _p, _n, **kw):
        self.saved = kw.get("metadata")
        self.child["metadata"] = self.saved
        return self.child


def _wire_child(monkeypatch, parent, child=None):
    import sys
    db = _FakeDBWithChild(parent, child)
    monkeypatch.setitem(sys.modules, "ems_db", db)
    return db


def test_child_inherits_the_clients_values(monkeypatch):
    _wire_child(monkeypatch, {"carrier": "Mercury", "adjuster_name": "Pat"})
    r = js.load("k", "Unit 561-I")
    assert r["values"]["carrier"] == "Mercury"
    assert "carrier" in r["inherited"]


def test_a_value_typed_on_the_child_wins(monkeypatch):
    _wire_child(monkeypatch, {"carrier": "Mercury", "claim_number": "P-1"},
                {"claim_number": "UNIT-9"})
    r = js.load("k", "Unit 561-I")
    assert r["values"]["claim_number"] == "UNIT-9"      # its own
    assert r["values"]["carrier"] == "Mercury"          # still inherited
    assert "claim_number" not in r["inherited"]


def test_only_the_disagreement_is_stored(monkeypatch):
    """Storing an inherited value would freeze a stale copy — fixing the
    client's carrier later would leave every unit on the old one."""
    db = _wire_child(monkeypatch, {"carrier": "Mercury", "claim_number": ""})
    vals = js.from_card("")
    vals.update({"carrier": "Mercury", "claim_number": "UNIT-9"})
    js.save("k", vals, child_name="Unit 561-I")
    stored = (db.saved or {}).get("settings") or {}
    assert stored == {"claim_number": "UNIT-9"}         # carrier NOT stored


def test_correcting_the_client_flows_down_to_units(monkeypatch):
    db = _wire_child(monkeypatch, {"carrier": "Mercury"})
    vals = js.from_card("")
    vals["carrier"] = "Mercury"                  # user re-saves, no change
    js.save("k", vals, child_name="Unit 561-I")
    db.job["metadata"]["settings"]["carrier"] = "Farmers"   # client corrected
    r = js.load("k", "Unit 561-I")
    assert r["values"]["carrier"] == "Farmers"


def test_child_without_its_own_card_is_not_merged_with_the_clients(monkeypatch):
    """The client's card describes the CLIENT. Merging it into a unit would
    overwrite that unit's own claim number and DOL on every open."""
    _wire_child(monkeypatch, {"carrier": "Mercury"}, {"claim_number": "U-9"})
    r = js.load("k", "Unit 561-I")
    assert r["synced"] is False
    assert r["card_id"] == ""
    assert r["values"]["claim_number"] == "U-9"


# ── XA ID / WC Project ID ─────────────────────────────────────────────

def test_xa_id_is_read_out_of_the_xa_link():
    """The id is already in the URL (…detail.jsp?ddid=06YD7CD&…). Asking
    someone to retype it — where a typo silently points at the wrong
    assignment — would be a worse field than no field."""
    assert js.xa_id_from_link(
        "https://www.xactanalysis.com/apps/cxa/detail.jsp"
        "?ddid=06YD7CD&xlink=false&src=#d_clientpolicy") == "06YD7CD"


def test_a_link_without_an_id_yields_nothing():
    assert js.xa_id_from_link("https://www.xactanalysis.com/apps/cxa/") == ""
    assert js.xa_id_from_link("") == ""


def test_a_typed_xa_id_is_not_overwritten_by_the_link():
    """A hand-entered id beats one parsed from a URL that may point at a
    superseded assignment."""
    card = CARD + ("\n**LINKS**\n\nXactanalysis Id: MANUAL-1\n\n"
                   "Ems Xactanalysis Link: https://x/detail.jsp?ddid=FROMLINK\n")
    assert js.from_card(card)["xa_id"] == "MANUAL-1"


def test_new_id_fields_are_appended_to_a_card_that_lacks_them():
    """No live card has either key yet, so a save has to add the line
    rather than quietly discard what was typed."""
    vals = js.from_card(CARD)
    vals["wc_project_id"] = "WC-4821"
    out = js.render_desc(CARD, vals, changed_ids=["wc_project_id"])
    assert "Workcenter Project Id: WC-4821" in out
