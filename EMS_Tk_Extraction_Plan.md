# Tk → logic extraction plan

**Goal:** web panels import logic modules, never `*_gui.py`. Today the live web
app imports `run_audit_gui` (16 calls to one function), `snapshot_gui`,
`apa_monitor_gui`, etc. — dragging tkinter + thousands of lines of dead UI into
the live app and welding web code to "retired" Tk files.

## Safe mechanic (per function)
1. Create a logic-only module (NO `import tkinter`).
2. Move the function/constant there verbatim.
3. In the old `*_gui.py`, replace the definition with `from <logic> import foo`
   — a re-export shim. Tk UI + any other caller keep working unchanged.
4. Repoint the `*_web.py` import at the logic module.
5. Run the full test suite after each module; add a characterization test for
   anything currently untested.

Each step stays a small, reversible, green-tests diff — no big-bang rewrite.

## Target modules (grouped by what web actually calls)

### apa_logic.py  ← apa_monitor_gui  (LOW risk)
SECTION_ORDER, SEC_FINAL_UPLOADS, SEC_INITIAL_UPLOADS, SEC_EST_SERVICE_CALL,
_BUILTIN_SET, strip_status_from_text, doc_path_for_today, _franchise_key,
parse_existing_doc, write_doc

### job_notes_logic.py  ← job_notes_gui  (LOW risk)
STAGES, parse_stages, save_note, load_note, list_saved_notes,
find_any_note_for_client, expected_files, clean_trello_paste, _notes_path

### snapshot_logic.py  ← snapshot_gui  (MEDIUM — pdf/reportlab, no tk)
parse_scope, parse_comments, detect_first_visit, fill_pdf, build_scope_pdf,
apply_snapshot_field_rules, append_overflow_pages

### run_doc.py (+ fold into audit_logic.py)  ← run_audit_gui  (HIGHEST value & care)
_find_run_doc_for_date (16x), audit_jobs (5x), enrich_with_sharepoint,
_append_sp_manifest_originals, _extract_stage_from_folder_name,
_extract_date_from_folder_name, _activity_labels_from_run_doc,
WC_DOCUMENTS_RE, WC_ATTACHMENTS_RE, DOWNLOADS

### small/quick batch  (LOW)
multi_unit_gui: list_unit_subfolders, discover_multi_unit_properties
daily_photos_gui: make_folders, _photo_folder_path
cheat_sheet_gui: parse_markdown
initial_upload_queue: _fetch_queue_from_trello, TRACKED_CHECKLISTS,
  _items_dict, _find_checklist, LANE_LABEL_BY_LIST_ID

## Sequence (payoff ÷ risk)
1. apa_logic + job_notes_logic — prove the pattern, immediate decoupling.
2. small/quick batch.
3. snapshot_logic — verify each fn is UI-free first (messagebox-on-error →
   refactor to raise/return).
4. run_doc.py last — audit_jobs / enrich_with_sharepoint pull a chain of private
   helpers; extract the whole cluster together, not piecemeal. Kills the 16-call
   coupling and lets the 8K-line file become deletable.

## Gotchas
- Transitive helpers: moving audit_jobs means moving everything it calls inside
  run_audit_gui. Extract by cluster, not single function.
- Hidden UI calls: a few "logic" fns may pop a messagebox on error — refactor to
  raise/return so the logic module stays tkinter-free; the web caller renders the
  error itself.

## Done when
`grep "import.*_gui" *_web.py` returns nothing; tests green; Tk files hold only
UI + re-export shims (deletable whenever Tk is formally retired).
