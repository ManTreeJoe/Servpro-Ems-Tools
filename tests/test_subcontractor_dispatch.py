import subcontractor_dispatch as dispatch


def test_dispatch_draft_uses_job_information_and_adjuster():
    result = dispatch.compose({
        "customer_name": "Brett Baughman",
        "address": "31355 Cala Carrasco, Temecula, CA 92592",
        "phone": "(951) 972-0688 - Brett",
        "email": "biomanbio@gmail.com",
        "additional_contacts": "619-929-8557",
        "source_of_lead": "Call Center",
        "carrier": "Mercury",
        "claim_number": "CAHO-00282431",
        "adjuster_name": "Pedro Huerta",
        "adjuster_email": "phuerta@mercuryinsurance.com",
        "adjuster_number": "951-395-4955",
    }, {
        "vendor_email": "dispatch@titan-enviro.com",
        "service": "Mold clearance",
        "ready_date": "2026-08-14",
        "scope_notes": "One containment in Kitchen",
    })
    assert result["to"] == "dispatch@titan-enviro.com; phuerta@mercuryinsurance.com"
    assert result["cc"] == "EMS@servpro10100.com"
    assert result["subject"] == "Baughman, Brett - Claim Number: CAHO-00282431 - Mold Clearance"
    assert "This will be ready by 08-14-26" in result["body"]
    assert "One containment in Kitchen" in result["body"]
    assert "Insurance Company: Mercury" in result["body"]
    assert result["missing"] == []


def test_dispatch_draft_reports_essentials_without_refusing_preview():
    result = dispatch.compose({}, {})
    assert result["ok"]
    assert "subcontractor email" in result["missing"]
    assert "customer name" in result["missing"]

