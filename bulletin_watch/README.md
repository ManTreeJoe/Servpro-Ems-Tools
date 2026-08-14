# Bulletin Watch

Watches the bulletin listings on SERVPRONET (`servpro.interactgo.com`) and tells you when a
carrier/national-account bulletin PDF is new or has been re-issued — then downloads the new
version into its own folder next to the old one and shows you what actually changed in the text.

Baseline as of the first run: **666 bulletins tracked**, and 3 of the ones in
`X:\IE_Public\Forms_Contracts\Bulletins` are already a revision behind.

## Everyday use

Double-click **`Check Bulletins.bat`**, or:

```
python bulletin_watch.py scan                      # what changed on the site since last time
python bulletin_watch.py compare-local             # which of YOUR files are outdated
python bulletin_watch.py compare-local --download  # pull the newer ones + diff vs your copies
python bulletin_watch.py audit-local               # full picture: behind, superseded, duplicate, unnumbered
```

`scan` exits with code 1 when something changed, 0 when nothing did — handy if you ever put it
on a schedule.

## How it detects changes

Each result card on a listing page carries the title (with the form number), a "Last updated"
date, and a download link containing the PDF filename and a `fileguid`. When HQ re-issues a
bulletin, the fileguid and usually the revision suffix change (`5807-F-2` → `5807-F-3`). So a
scan reads the listings only — fast, no downloading — and pulls PDF bytes just for the handful
that moved.

`audit-local` is the whole-folder view. `compare-local` answers "what is behind";
this also answers the three questions it cannot, each of which found something real
on 2026-08-14:

* **superseded (6)** - the folder keeps old revisions beside new ones (Hartford -11
  under -12, AAA -5 under -7). Nothing on disk says which is live.
* **same revision filed twice (1)** - `State Farm PSP 3467-F-8` and
  `State Farm Premier Service Program 3467-F-8` are one bulletin under two names.
  Not stale, just ambiguous - and deliberately NOT reported as superseded, or you
  would delete a current file.
* **unnumbered (21 of 45)** - no form number in the filename, so `compare-local`
  never sees them at all. One could be years stale and nothing would say so.
  `audit-local` at least ties them to a carrier by name.

It also flags a form number the site doesn't have, which is usually an F/SF slip in
OUR filename (`Farmers Insurance Group 5263-F-11` against the site's `5263-SF-13`).
Exit code is 1 when anything is behind, same as `scan`.

`compare-local` is the other half: it parses form numbers out of your filenames in
`X:\IE_Public\Forms_Contracts\Bulletins` (`4124-F-10 American Family.pdf` → `4124-F` rev 10)
and flags anything where the site has a higher revision.

## Old vs new

Whenever new PDFs come down (from `scan` or `compare-local --download`) you get a folder:

```
_data/updates/<timestamp>/          (or _data/downloads/<timestamp>/ from a scan)
    new/          the PDFs currently on SERVPRONET
    old/          the copies you had — your previous download, else the X:\ Bulletins file
    COMPARE.txt   a readable line-by-line diff of the PDF text
```

`COMPARE.txt` is the useful part — it shows the real edits, e.g. for Lemonade 5807-F-3:

```
-B.9. Invoicing and Payment Procedures: Lemonade Insurance will issue payment to
+B.9. Invoicing and Payment Procedures: Franchises will receive an email from HQ
+when uploaded job file is approved. The Franchise will then email the job file documents
+to the Lemonade adjuster and help@lemonade.com. ...
```

Nothing is ever written to `X:\` — copying an approved new bulletin into the shared folder
stays a manual decision.

## Login

The site is behind Servpro SSO. Credentials live in
`%LOCALAPPDATA%\bulletin_watch\credentials.json` — deliberately outside OneDrive so the
password is never synced to the cloud. The signed-in session is cached in a Chromium profile
under `_data/browser_profile`, so most runs don't log in at all.

If the password changes, edit that file. If SSO ever throws an MFA prompt the script can't get
past, run `python bulletin_watch.py login` and finish it by hand once.

## Configuration — `config.json`

```json
"sections": [
  {"name": "National Accounts",  "section": 3186, "subsection": 3445},
  {"name": "Credit & Insurance", "section": 3186, "subsection": 3710}
]
```

Those are the two that carry carrier bulletins. `python bulletin_watch.py sections` prints
every bulletin section on the site (Legal, Accounting, Field Ops, …) in copy-paste-ready form
if you want to watch more.

Other keys: `local_bulletins_dir`, `page_size` (50), `max_pages_per_section` (40),
`download_changed`, `extra_carriers` (carrier names checked first when tagging a bulletin;
anything else is learned from your local filenames).

## Other commands

```
python bulletin_watch.py report        # re-print the last scan report
python bulletin_watch.py sections      # list every bulletin section on the site
python bulletin_watch.py mirror        # one-time: download all 666 current PDFs (~150MB)
python bulletin_watch.py login         # sign in by hand
python bulletin_watch.py map <url>     # dump the links/buttons on any page (debugging)
python bulletin_watch.py scan --headed # watch it work in a visible browser
```

`mirror` is optional. Without it, "old" comes from your `X:\` folder, which only covers the
bulletins you actually file. With it, every bulletin has an exact previous copy, so diffs work
for accounts you don't keep locally.

## Files

```
bulletin_watch.py     the script
config.json           sections + paths (auto-created)
Check Bulletins.bat   double-click runner
_data/
    manifest.json     last known state of all 666 bulletins
    snapshots/        timestamped manifest copies
    reports/          text report per scan
    downloads/        current/ mirror + per-scan new/old/COMPARE.txt
    updates/          per-run new/old/COMPARE.txt from compare-local --download
    browser_profile/  signed-in Chromium profile
```

Requires `playwright` (installed) and, for the text diffs, `pdfplumber` (installed).
