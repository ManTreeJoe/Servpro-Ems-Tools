import pytest

from franchise_scorecard import combined_score, score, specification, weight_profile
from kpi_web import Api


@pytest.mark.parametrize("metric,value,expected", [
    ("contact", 5, 5), ("contact", 20, 4), ("contact", 60, 3),
    ("contact", 70, 2), ("contact", 71, 1),
    ("onsite", 1.99, 5), ("onsite", 2, 4), ("onsite", 3.75, 4),
    ("onsite", 4.5, 3), ("onsite", 5, 2), ("onsite", 5.01, 1),
    ("cycle", 6.99, 5), ("cycle", 7, 4), ("cycle", 9, 3),
    ("cycle", 10, 3), ("cycle", 12, 2), ("cycle", 12.01, 1),
    ("zero_rejections", 90, 5), ("zero_rejections", 85, 4),
    ("billing_disputes", 100, 5), ("billing_disputes", 79.9, 1),
    ("conversion", 90, 5), ("conversion", 60, 2),
    ("survey", 9, 4), ("survey", 6.9, 1),
    ("client_delta", 95, 4), ("client_delta", 84.9, 1),
])
def test_score_thresholds_match_supplied_table(metric, value, expected):
    assert score(metric, value) == expected


def test_standard_weight_profile_matches_supplied_distribution():
    profile = weight_profile({
        "contact", "onsite", "cycle", "zero_rejections",
        "billing_disputes", "conversion", "survey", "client_delta",
    })
    assert profile["name"] == "standard"
    assert profile["weights"]["cycle"] == 30.0
    assert profile["weights"]["zero_rejections"] == 30.0
    assert sum(profile["weights"].values()) == 100.0


def test_missing_survey_and_client_delta_uses_exact_fallback_profile():
    profile = weight_profile({
        "contact", "onsite", "cycle", "zero_rejections",
        "billing_disputes", "conversion",
    })
    assert profile["name"] == "no_survey_no_client_delta"
    assert profile["weights"]["cycle"] == 37.5
    assert "survey" not in profile["weights"]
    assert "client_delta" not in profile["weights"]


def test_combined_score_calculates_each_metric_then_weights_it():
    result = combined_score({
        "contact": 4.6, "onsite": 3.9, "cycle": 3.0,
        "zero_rejections": 100, "billing_disputes": 100,
        "conversion": 90, "survey": 10, "client_delta": 100,
    })
    assert result["profile"] == "standard"
    assert result["breakdown"]["contact"]["score"] == 5
    assert result["breakdown"]["onsite"]["score"] == 3
    assert 1 <= result["score"] <= 5


def test_billing_formula_ambiguity_is_not_hidden():
    metric = specification()["metrics"]["billing_disputes"]
    assert metric["calculation_status"] == "needs_confirmation"
    assert "confirms" in metric["warning"]


def test_kpi_interface_exposes_same_scorecard_specification():
    result = Api().franchise_scorecard_spec()
    assert result["metric_order"] == [
        "contact", "onsite", "cycle", "zero_rejections",
        "billing_disputes", "conversion", "survey", "client_delta",
    ]
    assert len(result["weight_profiles"]) == 8
