"""
fill_snapshot.py — dev/test harness for the snapshot-handoff PDF filler.

Not used by the launcher at runtime; the production filler lives in snapshot_gui.
This script lets you eyeball field placement against the bundled fillable PDF
template by writing a sample-data PDF.

Run:
    python fill_snapshot.py [output.pdf]

Default output: <snapshot_output>/Barber_Robert_Snapshot.pdf using the
template + output dir from config.json.
"""
import os
import sys

import pdfrw

import config as _config

SUBTYPE_KEY = '/Subtype'
WIDGET_SUBTYPE_KEY = '/Widget'

def fmt_techs(names, is_initials=False):
    """Max 2 techs. If initials mode, return as-is. If >2, show First +N."""
    if is_initials:
        return names[0] if names else ""
    if len(names) <= 2:
        return ", ".join(names)
    return f"{names[0]} +{len(names) - 1}"

def fill_pdf(input_path, output_path, data):
    template = pdfrw.PdfReader(input_path)
    for page in template.pages:
        annots = page.get('/Annots')
        if not annots:
            continue
        for annot in annots:
            if annot.get(SUBTYPE_KEY) == WIDGET_SUBTYPE_KEY:
                key = annot.get('/T')
                if key:
                    key_str = key[1:-1]
                    if key_str in data:
                        annot.update(pdfrw.PdfDict(
                            V=pdfrw.objects.pdfstring.PdfString.encode(data[key_str]),
                            AP=pdfrw.PdfDict()
                        ))
    template.Root.AcroForm.update(pdfrw.PdfDict(NeedAppearances=pdfrw.PdfObject('true')))
    pdfrw.PdfWriter().write(output_path, template)
    print(f"Saved: {output_path}")

data = {
    # --- HEADER ---
    "insured_job":          "Robert Barber",
    "carrier_claim":        "AAA / 017746090",
    "date_of_loss":         "3/28/26",
    "first_site_visit":     "3/30/26",
    "cause_category_class": "Water / Hot Slab Leak",
    "subs_used":            "Y",

    # --- SUB/VENDOR LOG (external contractors only, one row per event) ---
    "sub_date_1":     "3/31/26",  "sub_weekday_1": "Tuesday",
    "sub_activity_1": "Asbestos & Lead Testing - Billed Ins",
    "sub_techs_1":    "Safeguard",

    "sub_date_2":     "4/10/26",  "sub_weekday_2": "Friday",
    "sub_activity_2": "Alarm Wire Repair - Billed Servpro",
    "sub_techs_2":    "ADT",

    "sub_date_3":     "4/17/26",  "sub_weekday_3": "Friday",
    "sub_activity_3": "Mold Clearance Testing - Billed Ins",
    "sub_techs_3":    "Safeguard",

    "sub_date_4":     "4/20/26",  "sub_weekday_4": "Monday",
    "sub_activity_4": "Mold Clearance - Passed",
    "sub_techs_4":    "Safeguard",

    # --- DAILY JOB LOG (on-site work only) ---
    "log_date_1":     "3/30/26",  "log_weekday_1": "Monday",
    "log_activity_1": "Initial Inspection - slab leak, EQ placed",
    "log_techs_1":    fmt_techs(["FB"], is_initials=True),

    "log_date_2":     "4/6/26",   "log_weekday_2": "Monday",
    "log_activity_2": "Contents - offsite packout",
    "log_techs_2":    "Wendy +2",

    "log_date_3":     "4/9/26",   "log_weekday_3": "Thursday",
    "log_activity_3": "Demo (First day) - alarm wire cut, referred to ADT",
    "log_techs_3":    fmt_techs(["Cesar", "Robert"]),

    "log_date_4":     "4/10/26",  "log_weekday_4": "Friday",
    "log_activity_4": "Demo (completed) ADT alarm repair done",
    "log_techs_4":    fmt_techs(["Cesar", "Robert"]),

    "log_date_5":     "4/11/26",  "log_weekday_5": "Saturday",
    "log_activity_5": "Monitor - moisture still present",
    "log_techs_5":    fmt_techs(["Pablo"], is_initials=False),

    "log_date_6":     "4/13/26",  "log_weekday_6": "Monday",
    "log_activity_6": "Monitor - EQ picked up, ready for mold prep",
    "log_techs_6":    fmt_techs(["ML"], is_initials=True),

    "log_date_7":     "4/15/26",  "log_weekday_7": "Wednesday",
    "log_activity_7": "Mold Prep",
    "log_techs_7":    fmt_techs(["Danny", "Vince"]),

    "log_date_8":     "4/20/26",  "log_weekday_8": "Monday",
    "log_activity_8": "Teardown - clearance passed, job closed",
    "log_techs_8":    fmt_techs(["ML"], is_initials=True),
}

if __name__ == "__main__":
    cfg = _config.load()
    template = cfg.get("snapshot_template",
                       r"X:\IE_Public\Front Operation\snapshot_handoff_fillable.pdf")
    out_dir  = cfg.get("snapshot_output", os.path.expanduser("~/Downloads"))
    default_out = os.path.join(out_dir, "Barber_Robert_Snapshot.pdf")
    output = sys.argv[1] if len(sys.argv) > 1 else default_out
    fill_pdf(template, output, data)
