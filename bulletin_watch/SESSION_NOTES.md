# Bulletin Watch — session notes, 2026-07-30

Everything from the build session in one place: what got built, what we learned about the
SERVPRONET site (reusable for any future Playwright work against it), and the CRM/GPT plan.

Companion docs: `README.md` (how to use it) · memory `project_bulletin_watch`.

---

## 1. What was built

A Playwright watcher that checks SERVPRONET for new/re-issued bulletin PDFs and diffs the new
version against the copy you already have.

```
Desktop\Notes\bulletin_watch\
    bulletin_watch.py      the script (single file, ~900 lines)
    config.json            sections + paths (auto-created on first run)
    Check Bulletins.bat    double-click runner: scan + compare-local
    README.md              usage
    SESSION_NOTES.md       this file
    _data/
        manifest.json      last known state of all 666 bulletins
        snapshots/         timestamped manifest copies
        reports/           text report per scan
        downloads/         current/ mirror + per-scan new/old/COMPARE.txt
        updates/           per-run new/old/COMPARE.txt from compare-local --download
        browser_profile/   signed-in Chromium profile
```

**Status: working and verified.** Baseline scan captured 666 bulletins; a second scan correctly
reported 0 new / 0 changed (so it won't cry wolf); download + diff tested on 3 real bulletins.

### Results from the first run

Three files in `X:\IE_Public\Forms_Contracts\Bulletins` are a revision behind:

| Local file | Site has |
|---|---|
| `4124-F-10 American Family.pdf` | `AFICS Bulletin 4124-F-11.pdf` |
| `CBRE_Facility Source 5647-F-2.pdf` | `CBRE Facility Source #5647-F-3.pdf` |
| `Lemonade - 5807-F-2.pdf` | `Lemonade - 5807-F-3.pdf` |

The Lemonade diff shows a real procedural change, not just a date bump:

```
-B.9. Invoicing and Payment Procedures: Lemonade Insurance will issue payment to
+B.9. Invoicing and Payment Procedures: Franchises will receive an email from HQ
+when uploaded job file is approved. The Franchise will then email the job file documents
+to the Lemonade adjuster and help@lemonade.com. ...
```

### Commands

```
python bulletin_watch.py scan                      # what changed since last time (exit 1 = changed, 0 = clean)
python bulletin_watch.py compare-local             # which of YOUR files are outdated
python bulletin_watch.py compare-local --download  # pull newer + diff vs your copies
python bulletin_watch.py compare-local --show-missing
python bulletin_watch.py mirror                    # one-time: all 666 PDFs (~150MB)
python bulletin_watch.py report                    # re-print last report
python bulletin_watch.py sections                  # list every bulletin section on the site
python bulletin_watch.py login                     # sign in by hand
python bulletin_watch.py map <url>                 # dump links/buttons on any page (debugging)
python bulletin_watch.py scan --headed             # watch it work
```

### Design decisions made

- **First run records a metadata baseline, no downloads.** Downloading all 666 PDFs on run one
  took too long to be a sane default; `mirror` does it on demand.
- **`compare-local` hides the 650 bulletins you don't keep locally** behind `--show-missing` —
  the site carries every national account, you only file the ones you run.
- **Nothing is ever written to `X:\`.** Filing an approved bulletin stays a manual decision.

---

## 2. SERVPRONET site reference (reusable for future Playwright work)

### Login — SAML SSO

`https://servpro.interactgo.com/` redirects to
`https://idsrv.servpronet.com/Account/Login?ReturnUrl=/saml/sso/login?requestId=...`

Form fields: `input#Username`, `input#Password`, submit `button[name="button"][value="login"]`.
No MFA prompt on this account — plain username/password worked headless.

**Gotcha that cost time:** the login page has hidden inputs whose names contain "user" —
`ShouldCreateTrainingUser` is one, and it appears *before* `#Username` in the DOM. A locator like
`input[name*='user' i]` + `.first` resolves to the hidden field and `wait_for(state="visible")`
times out. Selectors must filter to visible:

```python
USER_SEL = ("input#Username:visible, input[name='Username']:visible, input[type='email']:visible, "
            "input:not([type='hidden'])[name*='user' i]:visible, "
            "input:not([type='hidden'])[id*='user' i]:visible")
```

**Second gotcha:** right after `goto()`, you may still be mid-SAML-redirect, so a host check says
"not logged in" when you actually are. Don't treat it as a login form until a *visible password
box* exists; otherwise wait and re-check. That's what `ensure_login()` does.

**Session:** `launch_persistent_context(user_data_dir=...)` keeps you signed in across runs, so
most runs never touch the login page at all. Credentials live in
`%LOCALAPPDATA%\bulletin_watch\credentials.json` — outside OneDrive on purpose, so the password
is never synced to the cloud.

### Site structure

It's an **Interact** intranet (interactsoftware.com). URL patterns:

```
/Interact/Pages/Section/Default.aspx?Section=<N>          section landing page
/Interact/Pages/Section/ContentListing.aspx?section=<N>&subsection=<M>
                                                          paginated content listing
/Interact/Pages/Content/Document.aspx?id=<N>              one bulletin page
/Utilities/Uploads/Handler/Uploader.ashx?area=composer&filename=<name>.pdf&fileguid=<GUID>
                                                          direct PDF download
```

Bulletins live under **Section 3186**. Sub-sections that matter:

| subsection | name |
|---|---|
| **3445** | **National Accounts Bulletins** ← the carrier bulletins |
| **3710** | **Credit & Insurance Bulletins** |
| 4577 | Weekly Bulletin Digest |
| 3735 / 3733 / 3726 | Accounting / Administration / Audit |
| 3712 / 3727 / 3669 | Commercial Large Loss / Legal / Field Ops |
| 3688 / 3689 / 3725 | SERVPRO Source / Preferred Vendor / Training |

(`python bulletin_watch.py sections` prints the full list copy-paste ready.)

Listing pagination: `&offset=0&limit=50&orderByDirection=dateDesc`. National Accounts is
**14 pages / 664 bulletins**. Stop when a page returns fewer than `limit` cards.

### Listing card anatomy — the key discovery

Each result is a `div.card-content`:

```html
<div class="card-content">
  <header><a href="/Interact/Pages/Content/Document.aspx?id=26611"><h5>Charter Senior Living # 20235-F</h5></a></header>
  <footer class="details">
    <div class="sub-pre main-text">summary text…</div>
    <span class="attachment">
      <a href="…Document.aspx?id=26611&attachment=beeb459f-…">Charter Senior Living # 20235-F</a>
      <a href="/Utilities/Uploads/Handler/Uploader.ashx?area=composer&filename=Charter+Senior+Living+%23+20235-F.pdf&fileguid=beeb459f-2fa0-4dda-9f63-a7c527ca95a5"
         title="Download"><i class="ii ii-download"></i></a>
    </span>
  </footer>
</div>
```

Plus `Last updated <Month D, YYYY>` on a wrapper *above* `.card-content` (walk up ~5 parents).

**Why this matters:** the listing alone gives title + form number + last-updated date + PDF
filename + `fileguid`. A re-issue changes the fileguid and usually the revision suffix, so
change detection needs **~15 page loads**, not 666 PDF downloads. Bytes are pulled only for what
actually moved.

### Page-load timing

`wait_until="domcontentloaded"` is not enough — the home page yielded 3 links that way and 166
after `wait_for_load_state("networkidle")`. Always settle on networkidle (with a timeout guard)
before reading the DOM.

---

## 3. Form-number canon

The join key between site bulletins and your local filenames:

```python
FORM_RE = re.compile(r"\b(\d{3,6})\s*-\s*(SF|F)(?:\s*-\s*(\d{1,3}))?\b", re.I)
```

Matches `5263-SF-13`, `4124-F-10`, `5995-F` (rev 0), `20044-F-4`, `5822-F-R`.
`X:\...\Bulletins\4124-F-10 American Family.pdf` → base `4124`, kind `F`, rev `10`. Site rev
higher than local rev = you're outdated. Carrier names are matched from a curated list first,
then names learned from your existing filenames.

---

## 4. Old-vs-new comparison

Any run that downloads produces:

```
_data/updates/<stamp>/    (or _data/downloads/<stamp>/ from a scan)
    new/          the PDFs currently on SERVPRONET
    old/          the copy you had — previous download, else the matching X:\ file
    COMPARE.txt   readable line-by-line diff of the PDF text
```

Text extraction is `pdfplumber` (already installed) → `difflib.unified_diff`. Byte-identical
files are reported as "only the listing metadata changed" rather than diffed. The `Â` artifact
from cp1252-encoded PDFs is stripped so diffs read clean.

Ordering matters in the code: comparison runs **before** `downloads/current/` is refreshed,
otherwise the old copy is gone by the time you want to diff it.

---

## 5. Environment notes

- Playwright **1.59.0**, Python **3.12.10**, Chromium 1217 installed — all already present.
- `pdfplumber` present; `pypdf`/`PyPDF2`/`fitz` absent.
- `scan` exits **1** when something changed, **0** when nothing did — ready for Task Scheduler.
  (Not scheduled yet — open item.)

---

## 6. CRM + GPT integration plan

The framing that works is the reverse of how it's usually asked: you don't put the CRM *into*
GPT. You expose a **tool layer** over your data and let the model call it. The model brings
language; your code stays the source of truth. `ems_db` (SQLite), Trello sync, `notes_tracker`
and now the bulletin manifest are all already there.

**Three ways to connect, ranked for our constraints:**

1. **MCP server over `ems_db` — start here.** `ems_mcp.py` exposing read-only tools:
   `find_job(name)`, `job_timeline(canon_key)`, `missing_items(job)`, `bulletin_status(carrier)`.
   Works with Claude Code the day it's written — no IT ticket, no hosting, no Azure. MCP is an
   open protocol OpenAI also supports, so one server serves whichever model we land on.
2. **Function calling inside EMS Tools** — same tool definitions, called from the app with an API
   key, so the copilot lives in the panel instead of a chat window. Where we end up for
   auto-drafted notes and next-actions. Same work as #1 plus a key and a UI.
3. **Custom GPT with Actions** — needs a public HTTPS endpoint reaching our data. With no Azure
   and the DB on an on-prem share, skip it.

**The blocker to raise before building.** Job data is customer PII, claim numbers, and adjuster
correspondence. Routing that to a third-party API is a bigger disclosure than the Azure AD
approval IT already refused, so assume the same conversation is required, and that consumer
ChatGPT is off the table (API/enterprise tiers don't train on your data; consumer does by
default). Two ways through: get API use approved explicitly, or run a local model via Ollama for
anything touching customer records — which matches the on-device idea already in the CRM notes.

**Concrete first move: pilot on the bulletins.** That corpus is 666 documents of pure company
policy with **zero customer PII** — carrier guidelines, invoicing procedures, pricing rules. It
can go to any model with nothing to disclose. Extract text with pdfplumber (already used for the
diffs), store in a SQLite **FTS5** table keyed by form number, expose one tool:
`search_bulletins(carrier, question)`. Then *"what does Farmers require for antimicrobial
approval?"* or *"what changed in the Lemonade bulletin?"* gets answered with a citation instead
of someone opening six PDFs. It proves the whole pattern — retrieval, tool layer, model on top —
with no privacy exposure, and the tool layer is the same one job data plugs into once approval
lands.

---

## 7. Open items / next steps

- [ ] **`search_bulletins` pilot** — pdfplumber extract → SQLite FTS5 → MCP tool (offered, not started).
- [ ] **Schedule it** — Task Scheduler weekly; `scan` already exits 1 on change.
- [ ] Decide whether to run `mirror` (~150MB) so diffs work for accounts not filed locally.
- [ ] Fold into the EMS suite proper (it's standalone today) — a Hygiene section for
      "bulletin revisions available" would fit the existing tracker pattern.
- [ ] Watch more sections? Only National Accounts + Credit & Insurance are configured.
- [ ] The 3 outdated local bulletins are downloaded and diffed but **not** copied to `X:\` — still
      needs a human decision.
