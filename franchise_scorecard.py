"""SERVPRO water franchise scorecard rules supplied by the user.

This is deliberately a pure calculation module.  Source adapters will feed it
raw job facts from Xactimate/XA, WorkCenter, XTrack, Salesforce, SurveyMonkey,
ClaimX, and Linguar Hub.  Keeping collection outside this module means the
same scoring rules work for a job, franchise, owner, state, or national rollup
without teaching the calculator how any vendor stores data.
"""
from __future__ import annotations

from copy import deepcopy


METRIC_ORDER = (
    "contact", "onsite", "cycle", "zero_rejections",
    "billing_disputes", "conversion", "survey", "client_delta",
)

METRICS = {
    "contact": {
        "label": "Contact Time", "unit": "hours", "direction": "lower",
        "start": "dispatch_at", "end": "contact_at", "source": "Xactimate/XA",
    },
    "onsite": {
        "label": "Onsite Time", "unit": "hours", "direction": "lower",
        "start": "dispatch_at", "end": "site_inspected_at", "source": "Xactimate/XA",
    },
    "cycle": {
        "label": "Total Cycle Time", "unit": "days", "direction": "lower",
        "start": "max(dispatch_at, xact_assigned_at)",
        "end": "final_audit_completed_at", "source": "Xactimate/XA + Linguar Hub",
    },
    "zero_rejections": {
        "label": "Zero Rejection Files", "unit": "percent", "direction": "higher",
        "numerator": "completed jobs with zero XTrack rejections",
        "denominator": "jobs completed in WorkCenter", "source": "XTrack + WorkCenter",
    },
    "billing_disputes": {
        "label": "Billing Disputes", "unit": "percent", "direction": "higher",
        "source": "Salesforce + WorkCenter",
        "calculation_status": "needs_confirmation",
        "warning": (
            "The supplied calculation counts jobs with a dispute, but the supplied "
            "score table awards 5 at 100%. The calculator therefore accepts the "
            "positive percentage printed by the official scorecard and does not "
            "derive this percentage until SERVPRO confirms whether it is dispute-free rate."
        ),
    },
    "conversion": {
        "label": "Conversion Rate", "unit": "percent", "direction": "higher",
        "numerator": "jobs completed in WorkCenter",
        "denominator": "National Account leads with an XA Transaction ID",
        "source": "WorkCenter + Xactimate/XA",
    },
    "survey": {
        "label": "Survey Score", "unit": "rating", "direction": "higher",
        "calculation": "NPS 70% + COS 30%; use the available result at 100% when only one exists",
        "source": "SurveyMonkey / SERVPRO data warehouse",
    },
    "client_delta": {
        "label": "Client Delta", "unit": "percent", "direction": "higher",
        "source": "ClaimX + Xactimate/XA + WorkCenter",
        "submetrics": {
            "claimxperience": "Allstate completed video task / completed Allstate jobs assigned the task",
            "farmers_4_day_upload": "Farmers jobs with onsite-to-nonzero estimate upload under 4 days / completed Farmers jobs assigned the task",
            "allstate_5_day_upload": "Allstate jobs with dispatch-to-nonzero estimate upload under 5 days / completed Allstate jobs with a measured result",
        },
    },
}


WEIGHT_PROFILES = {
    "standard": (2.5, 2.5, 30.0, 30.0, 7.5, 7.5, 10.0, 10.0),
    "no_client_delta": (2.8, 2.8, 33.3, 33.3, 8.3, 8.3, 11.1, None),
    "no_billing_disputes": (2.7, 2.7, 32.4, 32.4, None, 8.1, 10.9, 10.8),
    "no_survey": (2.8, 2.8, 33.4, 33.4, 8.0, 8.3, None, 11.0),
    "no_survey_no_billing": (3.0, 3.0, 36.4, 36.4, None, 9.1, None, 12.1),
    "no_survey_no_client_delta": (3.1, 3.1, 37.5, 37.5, 9.4, 9.4, None, None),
    "no_billing_no_client_delta": (3.0, 3.0, 36.4, 36.4, None, 9.1, 12.1, None),
    "no_billing_no_client_delta_no_survey": (3.4, 3.4, 41.4, 41.4, None, 10.4, None, None),
}

_MISSING_TO_PROFILE = {
    frozenset(): "standard",
    frozenset({"client_delta"}): "no_client_delta",
    frozenset({"billing_disputes"}): "no_billing_disputes",
    frozenset({"survey"}): "no_survey",
    frozenset({"survey", "billing_disputes"}): "no_survey_no_billing",
    frozenset({"survey", "client_delta"}): "no_survey_no_client_delta",
    frozenset({"billing_disputes", "client_delta"}): "no_billing_no_client_delta",
    frozenset({"billing_disputes", "client_delta", "survey"}):
        "no_billing_no_client_delta_no_survey",
}


def _high(value, boundaries):
    for minimum, result in boundaries:
        if value >= minimum:
            return result
    return 1


def score(metric: str, value: float) -> int:
    """Return the supplied 1–5 score for one already-aggregated metric."""
    metric = str(metric or "").strip()
    value = float(value)
    if metric == "contact":
        return 5 if value <= 5 else 4 if value <= 20 else 3 if value <= 60 else 2 if value <= 70 else 1
    if metric == "onsite":
        return 5 if value < 2 else 4 if value <= 3.75 else 3 if value <= 4.5 else 2 if value <= 5 else 1
    if metric == "cycle":
        return 5 if value < 7 else 4 if value < 9 else 3 if value <= 10 else 2 if value <= 12 else 1
    if metric == "zero_rejections":
        return _high(value, ((90, 5), (85, 4), (75, 3), (50, 2)))
    if metric == "billing_disputes":
        return _high(value, ((100, 5), (95, 4), (90, 3), (80, 2)))
    if metric == "conversion":
        return _high(value, ((90, 5), (85, 4), (75, 3), (60, 2)))
    if metric == "survey":
        return _high(value, ((10, 5), (9, 4), (8, 3), (7, 2)))
    if metric == "client_delta":
        return _high(value, ((100, 5), (95, 4), (90, 3), (85, 2)))
    raise ValueError(f"unknown scorecard metric: {metric}")


def weight_profile(available_metrics) -> dict:
    """Choose the supplied weight distribution for the metrics available."""
    available = {str(item) for item in available_metrics}
    required = set(METRIC_ORDER[:6]) - {"billing_disputes"}
    missing_required = required - available
    if missing_required:
        raise ValueError("No supplied weight profile covers missing core metrics: " +
                         ", ".join(sorted(missing_required)))
    optional = {"billing_disputes", "survey", "client_delta"}
    profile_name = _MISSING_TO_PROFILE.get(frozenset(optional - available))
    if not profile_name:
        raise ValueError("No supplied weight profile matches the available metrics")
    values = WEIGHT_PROFILES[profile_name]
    return {"name": profile_name, "weights": {
        metric: weight for metric, weight in zip(METRIC_ORDER, values)
        if weight is not None
    }}


def combined_score(values: dict) -> dict:
    """Score supplied aggregates and apply the matching official weights."""
    usable = {key: value for key, value in (values or {}).items()
              if key in METRICS and value is not None}
    profile = weight_profile(usable)
    breakdown = {}
    weighted_total = 0.0
    weight_total = 0.0
    for metric, weight in profile["weights"].items():
        result = score(metric, usable[metric])
        weighted = result * weight
        breakdown[metric] = {
            "value": float(usable[metric]), "score": result,
            "weight": weight, "weighted": round(weighted, 3),
        }
        weighted_total += weighted
        weight_total += weight
    return {
        "profile": profile["name"],
        "score": round(weighted_total / weight_total, 2) if weight_total else None,
        "weight_total": round(weight_total, 1),
        "breakdown": breakdown,
    }


def specification() -> dict:
    """JSON-safe source of truth for UI labels and future adapters."""
    return {
        "metrics": deepcopy(METRICS),
        "metric_order": list(METRIC_ORDER),
        "weight_profiles": {
            name: {metric: weight for metric, weight in zip(METRIC_ORDER, values)
                   if weight is not None}
            for name, values in WEIGHT_PROFILES.items()
        },
        "reporting_rule": (
            "Calculate each job, franchise, owner, state, and national level "
            "independently; do not average franchise totals to produce an owner total."
        ),
    }
