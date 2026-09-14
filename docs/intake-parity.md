# L OPS / EMS Tools intake parity

Both products should evolve together; this contract is the field mapping, not an automatic database sync.

| EMS Tools intake | L OPS job |
|---|---|
| insured_name | customer |
| address | property |
| phone / email | phone / email |
| date_received | jobDate |
| date_of_loss | lossDate |
| type_of_loss | lossType |
| loss_details | lossDetails |
| carrier | carrier |
| claim_number / policy_number | claimNumber / policyNumber |
| adjuster_name / adjuster_email / adjuster_number | adjusterName / adjusterEmail / adjusterPhone |
| deductible / agent_name / xa_id | deductible / agentName / xaId |
| year_built / additional_contacts | yearBuilt / additionalContacts |
| field_notes / office_notes | fieldNotes / officeNotes |

Dates persist as ISO YYYY-MM-DD; screens display MM-DD-YYYY. IDs, claim numbers, and policy numbers remain strings. Unknown payer stays Unknown; blank carrier does not mean self-pay. Daily crews belong to dated run/visit records, not permanent job contacts.

For feature changes: review the corresponding implementation in both repositories, preserve unknown fields on round-trip, add mapping/fixtures before transferring fields, and document which side is implemented. Avoid direct two-way writes until conflict handling, stable job identity, and workspace ownership are implemented and verified.

Current status: L OPS expanded intake and explicit label-based email extraction implemented. EMS Tools already has carrier parsing, Trello template cloning, folder setup, and CompanyCam provisioning; these side effects are NOT triggered by L OPS create. Its parser has additional fallback heuristics not yet ported. Keep external provisioning separate and retryable to avoid duplicate projects.

Next parity work: carry these fields through the legacy DB adapter with a dry-run comparison; align contact records and loss IDs; transfer intake templates/checklists; support duplicate detection and a separately tracked provisioning status. Existing databases have not been merged or synchronized by this change.
