"""Estimating board split its single TBA + Service Call lanes into
Program / Non-Program / Storm columns (2026-06-24). The APA routing must
COMBINE every variant back into the one section — and produce an
identical, program-agnostic sub — so the split never fragments the APA.
"""
import apa_web
import apa_logic as apa


_TBA_LANES = [
    " TO BE ASSIGNED - PROGRAM ",      # note board's stray spaces
    "TO BE ASSIGNED - Non-Program",
    "TO BE ASSIGNED - STORM",
]
_SVC_LANES = [
    "SERVICE CALLS - Program",
    "SERVICE CALL - Non-Program",
    "SERIVCE CALLS - STORM",            # board typo "SERIVCE"
]


def test_all_tba_variants_combine_to_one_section_and_sub():
    api = apa_web.Api()
    secs = {api._suggest_section_for_lane(l) for l in _TBA_LANES}
    subs = {api._suggest_sub_for_lane(l, apa.SEC_EST_TBA) for l in _TBA_LANES}
    assert secs == {apa.SEC_EST_TBA}      # every variant → one section
    assert subs == {"To Be Assigned"}     # identical clean sub (combined)


def test_all_service_call_variants_combine_to_one_section_and_sub():
    api = apa_web.Api()
    secs = {api._suggest_section_for_lane(l) for l in _SVC_LANES}
    subs = {api._suggest_sub_for_lane(l, apa.SEC_EST_SERVICE_CALL)
            for l in _SVC_LANES}
    assert secs == {apa.SEC_EST_SERVICE_CALL}
    assert subs == {"Service Call"}
