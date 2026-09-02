# Franchise Performance Scorecard Requirements

This is the source-of-truth transcription of the SERVPRO Water scorecard supplied on 2026-09-01. Linguar Hub must retain the raw milestone, count, task, and survey facts used by these calculations. It must not store only the final score.

## Reporting rule

Calculate job, franchise, owner, state, and national results independently. An owner result is not the average of its franchise results.

## Weighted metrics

| Metric | Calculation | Authoritative source | Current coverage |
|---|---|---|---|
| Contact Time | Dispatch to contact, in hours | Xactimate/XA | Missing authoritative contact timestamp |
| Onsite Time | Dispatch to site inspected, in hours | Xactimate/XA | Missing authoritative site-inspected timestamp |
| Total Cycle Time | Later of dispatch or Xact assigned, through Final Audit Complete | Xactimate/XA + Linguar Hub | Partial lifecycle/final-audit signals; vendor dates still required |
| Zero Rejection Files | Completed files with zero XTrack rejections / WorkCenter completed files | XTrack + WorkCenter | Connector required |
| Billing Disputes | Supplied definition conflicts with supplied higher-is-better score thresholds | Salesforce + WorkCenter | Local dispute tracker is partial; official denominator and formula confirmation required |
| Conversion Rate | WorkCenter completed jobs / National Account leads with XA Transaction ID | WorkCenter + Xactimate/XA | XA ID is stored; authoritative WorkCenter completion required |
| Survey Score | NPS 70% + COS 30%; one available measure receives 100% | SurveyMonkey / data warehouse | Connector required |
| Client Delta | ClaimXperience, Farmers 4-day upload, and Allstate 5-day upload | ClaimX + Xactimate/XA + WorkCenter | Connector required; CompanyCam video is not a substitute for ClaimX |

## Required raw job facts

- `dispatch_at`
- `xact_assigned_at`
- `contact_at`
- `site_inspected_at`
- `nonzero_estimate_uploaded_at`
- `final_audit_completed_at`
- `workcenter_completed_at`
- XA Transaction ID and WorkCenter project ID
- XTrack rejection count
- billing-dispute count and official eligibility population
- NPS and COS survey results
- ClaimX task assigned/completed and qualifying video count
- carrier/client program, franchise, and owner scope
- source system, source record ID, observed time, and revision history for every imported fact

## Scoring

The exact 1–5 thresholds and all eight supplied weight distributions are implemented in `franchise_scorecard.py`. Missing Survey, Billing Dispute, or Client Delta metrics select the matching supplied fallback distribution. There is no supplied fallback when a core SLA, rejection, or conversion metric is missing; the app must show the scorecard as incomplete rather than inventing a score.

## Billing-dispute decision needed

The reference calculation describes a numerator of jobs with at least one dispute, while the scoring table gives the best score at 100%. Those cannot both describe a dispute rate. Until SERVPRO confirms whether the displayed percentage is a dispute-free/compliance rate, Linguar Hub may display an imported official result but must not derive it from local counts.
