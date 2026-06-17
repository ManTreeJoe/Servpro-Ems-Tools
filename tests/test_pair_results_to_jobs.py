"""audit_web._pair_results_to_jobs maps each audit result back to the
run-doc job it came from. Two tricky shapes:

  • 1→N fan-out: one run-doc line expands into several claim folders;
    every result must pair to that ONE source line (by `claim_origin`).
  • N distinct lines, same name: a property dispatched as two claim lines
    "(1s claim)" + "(2nd claim Kitchen)" — each result must pair to ITS
    OWN line so the activity chips (Demo Thursday on the 2nd claim only)
    come from the right dispatch text.
"""
from audit_web import _pair_results_to_jobs


def test_single_line_pairs_one_to_one():
    jobs = [{"client": "Joe Smith", "raw": "a"},
            {"client": "Mary Jones", "raw": "b"}]
    results = [{"client": "Joe Smith"}, {"client": "Mary Jones"}]
    paired = _pair_results_to_jobs(jobs, results)
    assert [j["client"] for j, _ in paired] == ["Joe Smith", "Mary Jones"]


def test_fanout_results_all_map_to_one_line():
    # One run-doc line → two claim-folder results (claim_origin = the line).
    jobs = [{"client": "Mansolino Sayra", "raw": "line"}]
    results = [
        {"client": "Mansolino Sayra 1st Claim",
         "claim_origin": "Mansolino Sayra", "claim_subfolder": "1st Claim"},
        {"client": "Mansolino Sayra 2nd Claim (KItchen)",
         "claim_origin": "Mansolino Sayra",
         "claim_subfolder": "2nd Claim (KItchen)"},
    ]
    paired = _pair_results_to_jobs(jobs, results)
    assert len(paired) == 2
    assert all(j is jobs[0] for j, _ in paired)


def test_two_claim_lines_pair_by_claim_number():
    # Two distinct run-doc lines, same canonical name, different claims.
    job1 = {"client": "Sayra Mansolino", "claim_hint": "1s claim",
            "raw": "(Mold After) ME"}
    job2 = {"client": "Sayra Mansolino", "claim_hint": "2nd claim Kitchen",
            "raw": "(Mold After/Demo Thur 6/11) ME"}
    jobs = [job1, job2]
    # Results may arrive in any order — pairing is by claim number.
    results = [
        {"client": "Sayra Mansolino 2nd Claim (KItchen)",
         "claim_origin": "Sayra Mansolino",
         "claim_subfolder": "2nd Claim (KItchen)"},
        {"client": "Sayra Mansolino 1st Claim",
         "claim_origin": "Sayra Mansolino", "claim_subfolder": "1st Claim"},
    ]
    paired = _pair_results_to_jobs(jobs, results)
    pmap = {r["claim_subfolder"]: j for j, r in paired}
    assert pmap["2nd Claim (KItchen)"] is job2   # Demo-Thursday line
    assert pmap["1st Claim"] is job1
