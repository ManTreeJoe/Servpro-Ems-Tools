"""INITIAL PAPERWORK ticks on a FORM, not on any file in DOCS.

The tick fired whenever something landed in EMS/DOCS. A dry report is a
reading, not paperwork — importing one ticked INITIAL PAPERWORK, and the
checklist then said the intake was done on a job with nothing signed.

The four that count are the intake forms: ATP, CIF, CER, COS. Scope has
its own checklist item and so does the photo report, so neither belongs
here.
"""
import pytest

import audit_logic as al


@pytest.mark.parametrize("name", [
    "ATP signed.pdf",
    "Auth to Perform - Abbott.pdf",
    "Customer Info Form.pdf",
    "CIF.pdf",
    "Customer Equip Responsibility.pdf",
    "CER.pdf",
    "Cert of Satisfaction.pdf",
    "COS 8-19-26.pdf",
])
def test_the_intake_forms_count(name):
    assert al.is_initial_paperwork(name) is True


@pytest.mark.parametrize("name", [
    "Dry Report.pdf",              # the one that prompted this
    "Drying Report 8-19-26.pdf",
    "moisture log.xlsx",
    "Scope.pdf",                   # its own checklist item
    "Initial Photo Report.pdf",    # its own checklist item
    "photo.jpg",
    "",
])
def test_everything_else_does_not(name):
    assert al.is_initial_paperwork(name) is False


def test_any_of_a_batch():
    """An import drops several files; one real form is enough."""
    assert al.any_initial_paperwork(["Dry Report.pdf", "moisture.xlsx",
                                     "ATP.pdf"]) is True
    assert al.any_initial_paperwork(["Dry Report.pdf",
                                     "moisture.xlsx"]) is False
    assert al.any_initial_paperwork([]) is False


def test_the_web_import_gates_the_tick_on_a_form():
    """The live path: audit_web fires wc_docs_imported, which ticks
    INITIAL PAPERWORK. It used to fire on docs_count alone."""
    import io, os
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "audit_web.py"), encoding="utf-8").read()
    i = src.index('_ev.append("wc_docs_imported")')
    before = src[max(0, i - 400):i]
    assert "any_initial_paperwork" in before, (
        "the tick must be gated on an actual intake form")


def test_the_tk_dialog_agrees():
    """Two paths, one rule — otherwise the same job ticks differently
    depending on which tool touched it."""
    import io, os
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "process_card_dialog.py"),
        encoding="utf-8").read()
    assert "_has_initial_forms(docs)" in src
    assert "is_initial_paperwork" in src
