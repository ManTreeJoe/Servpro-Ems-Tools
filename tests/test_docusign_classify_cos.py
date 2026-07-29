"""docusign_import.classify_pdf — COS detection.

The CLOSE OUT "FINAL PAPERWORK" Trello item auto-ticks ONLY when a COS
(Certificate of Satisfaction) is imported (user 2026-06-22). That gate
relies on classify_pdf returning "CoS" for the COS and NOT mis-tagging a
client name that merely contains the letters "cos" (e.g. Costales).
"""
import docusign_import as ds


def test_cos_by_template_id():
    assert ds.classify_pdf("28531_-_Certificate_of_Satisfaction.pdf") == "CoS"


def test_cos_by_full_name():
    assert ds.classify_pdf("Certificate of Satisfaction signed.pdf") == "CoS"


def test_cos_by_bare_word():
    # Hand-named files the auto-scanner / pick-a-file flow might see.
    assert ds.classify_pdf("CoS.pdf") == "CoS"
    assert ds.classify_pdf("CoS - Smith.pdf") == "CoS"


def test_client_name_containing_cos_is_not_cos():
    # Costales / cost / tacos must NOT be read as a COS.
    assert ds.classify_pdf("Costales invoice.pdf") != "CoS"
    assert ds.classify_pdf("cost breakdown.pdf") != "CoS"


def test_other_forms_unchanged():
    assert ds.classify_pdf("28001_-_Authorization_to_Perform.pdf") == "ATP"
    assert ds.classify_pdf("28501_-_Customer_Information_Form.pdf") == "CIF"
    assert ds.classify_pdf("28510_-_Customer_Equipment.pdf") == "CER"
    assert ds.classify_pdf("Summary.pdf") == "Summary"
