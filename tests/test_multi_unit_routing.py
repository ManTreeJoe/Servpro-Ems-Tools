"""Multi-unit SP/WC auto-routing in run_audit_gui.

Locks the disambiguation behavior for Action Property Management →
Villaigo, which has multiple `Unit 104` subfolders for different
insureds (Straub / Mendoza / Mendiola). Routing must use the SP folder's
insured-name tokens to pick the right one.
"""
import run_audit_gui as rag


def _opts_for_villaigo_unit_104():
    """The three Unit 104 sub-folders Action Property Mgmt has in real
    life — one per insured, all sharing the same unit number."""
    return [
        {"unit_num": 104,
         "unit_name": "Unit 104 - 95043 Straub, Christine",
         "label": "Villaigo / Unit 104 - 95043 Straub, Christine"
                  " / EMS / PICS",
         "path": r"X:\fake\Villaigo\Unit 104 - 95043 Straub, Christine"
                  r"\EMS\PICS"},
        {"unit_num": 104,
         "unit_name": "Unit 104 - 97798 Mendoza, Katherine",
         "label": "Villaigo / Unit 104 - 97798 Mendoza, Katherine"
                  " / EMS / PICS",
         "path": r"X:\fake\Villaigo\Unit 104 - 97798 Mendoza, Katherine"
                  r"\EMS\PICS"},
        {"unit_num": 104,
         "unit_name": "Unit 104-97820- Mendiola, Mary",
         "label": "Villaigo / Unit 104-97820- Mendiola, Mary"
                  " / EMS / PICS",
         "path": r"X:\fake\Villaigo\Unit 104-97820- Mendiola, Mary"
                  r"\EMS\PICS"},
    ]


def _score_routing(sp_folder_name, options):
    """Apply the same scoring rule _copy_match uses and return the
    winning option (or None when no auto-route should fire)."""
    from multi_unit_gui import parse_unit_token
    sp_unit = parse_unit_token(sp_folder_name)
    if sp_unit is None:
        return None
    unit_opts = [o for o in options if o.get("unit_num") == sp_unit]
    if not unit_opts:
        return None
    sp_tokens = rag._name_tokens_for_unit_match(sp_folder_name)
    scored = []
    for o in unit_opts:
        opt_tokens = rag._name_tokens_for_unit_match(
            o.get("unit_name") or "")
        overlap = len(sp_tokens & opt_tokens)
        pics_pref = 1 if (o.get("label") or "").rstrip().endswith(
            "PICS") else 0
        scored.append((overlap, pics_pref, o))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    best_overlap, _, best_opt = scored[0]
    if len(unit_opts) == 1 or best_overlap > 0:
        return best_opt
    return None


def test_mendiola_unit_104_routes_to_mendiola_folder():
    opts = _opts_for_villaigo_unit_104()
    winner = _score_routing("Mendiola unit 104 Demo 5-10-26", opts)
    assert winner is not None
    assert "Mendiola" in winner["unit_name"]


def test_mendoza_unit_104_routes_to_mendoza_folder():
    opts = _opts_for_villaigo_unit_104()
    winner = _score_routing("Mendoza Unit 104 Demo", opts)
    assert winner is not None
    assert "Mendoza" in winner["unit_name"]


def test_straub_unit_104_routes_to_straub_folder():
    opts = _opts_for_villaigo_unit_104()
    winner = _score_routing("Christine Straub - Unit 104 Initial", opts)
    assert winner is not None
    assert "Straub" in winner["unit_name"]


def test_unknown_insured_falls_back_to_picker():
    # When the SP folder's insured tokens match NONE of the unit
    # folders' insureds, we must NOT auto-route — better to fall back
    # to the user's combobox than silently pick the wrong family.
    opts = _opts_for_villaigo_unit_104()
    winner = _score_routing("Smith unit 104 Demo", opts)
    assert winner is None


def test_single_unit_104_still_auto_routes_without_name_match():
    # If only ONE folder has unit_num=104 (single-unit-104 property),
    # auto-route regardless of name overlap — there's no ambiguity.
    opts = [_opts_for_villaigo_unit_104()[0]]  # just Straub
    winner = _score_routing("Smith unit 104 Demo", opts)
    assert winner is not None
    assert "Straub" in winner["unit_name"]


def test_apt_token_also_routes():
    # "Apt 104" must parse as unit 104 the same way "Unit 104" does.
    opts = _opts_for_villaigo_unit_104()
    winner = _score_routing("Mendiola Apt 104 Demo", opts)
    assert winner is not None
    assert "Mendiola" in winner["unit_name"]


def test_stopwords_dont_inflate_match():
    # If we didn't drop 'unit' / 'apt' / 'apartment' from the token
    # set, every unit name would overlap with every SP folder name on
    # the word 'unit' alone. Verify a no-name-match SP folder still
    # produces zero overlap.
    sp_tokens = rag._name_tokens_for_unit_match(
        "Demo pics Unit 104 apartment")
    # No insured name in the folder. Only 'demo' and 'pics' should
    # contribute (>= 3 chars, alphabetic, not in stopwords).
    assert "demo" in sp_tokens
    assert "pics" in sp_tokens
    assert "unit" not in sp_tokens
    assert "apartment" not in sp_tokens
