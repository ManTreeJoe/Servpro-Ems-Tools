"""bulletin_watch.py - watch SERVPRONET (servpro.interactgo.com) for new/changed bulletin PDFs.

How it works
------------
The bulletins live in listing pages like
    /Interact/Pages/Section/ContentListing.aspx?section=3186&subsection=3445
Every result card gives us the title (with the form number), the "Last updated" date,
and a direct Download link whose url carries the PDF filename and a `fileguid`.
When HQ re-issues a bulletin the fileguid and/or the filename revision changes - so we
can spot changes by reading the listings, and only download the PDFs that actually moved.

The site is behind Servpro SSO.  Credentials are read from
    %LOCALAPPDATA%\\bulletin_watch\\credentials.json
(kept outside OneDrive on purpose) and the signed-in session is cached in a Chromium
profile under _data/browser_profile.

Commands
--------
    python bulletin_watch.py scan            # check every configured section, report changes
    python bulletin_watch.py compare-local   # site form revisions vs the local Bulletins folder
    python bulletin_watch.py report          # re-print the last report
    python bulletin_watch.py sections        # list every bulletin section on the site
    python bulletin_watch.py login           # sign in by hand (only if auto-login ever fails)
    python bulletin_watch.py map <url>       # dump the links/buttons on any page

Everything is stored in _data/ next to this script:
    browser_profile/   signed-in Chromium profile
    manifest.json      last known state of every bulletin
    snapshots/         timestamped copies of the manifest
    downloads/current/ latest copy of every PDF we've pulled
    downloads/<stamp>/ just the PDFs that were new or changed in that run
    reports/           text report per run
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urldefrag, urlencode, urlparse

try:
    from playwright.sync_api import sync_playwright
    from playwright.sync_api import Error as PWError
    from playwright.sync_api import TimeoutError as PWTimeout
except ImportError:  # pragma: no cover
    sys.exit("playwright is not installed.  Run:  pip install playwright  &&  python -m playwright install chromium")

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "_data"
PROFILE_DIR = DATA_DIR / "browser_profile"
MANIFEST = DATA_DIR / "manifest.json"
SNAP_DIR = DATA_DIR / "snapshots"
DL_DIR = DATA_DIR / "downloads"
REPORT_DIR = DATA_DIR / "reports"
CONFIG_PATH = SCRIPT_DIR / "config.json"
# Deliberately outside OneDrive so the password is never synced to the cloud.
CRED_PATH = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "bulletin_watch" / "credentials.json"

SITE = "https://servpro.interactgo.com"
LISTING = SITE + "/Interact/Pages/Section/ContentListing.aspx"

DEFAULT_CONFIG = {
    "site_url": SITE + "/",
    "local_bulletins_dir": r"X:\IE_Public\Forms_Contracts\Bulletins",
    # Bulletin listings to watch.  `python bulletin_watch.py sections` prints them all.
    "sections": [
        {"name": "National Accounts", "section": 3186, "subsection": 3445},
        {"name": "Credit & Insurance", "section": 3186, "subsection": 3710},
    ],
    "page_size": 50,
    "max_pages_per_section": 40,
    # Pull the PDF bytes for anything new/changed (hash + a local copy you can file away).
    "download_changed": True,
    "nav_timeout_ms": 45000,
    # Carrier names checked first when tagging a bulletin; anything else is learned
    # from the filenames already in the local Bulletins folder.
    "extra_carriers": [
        "AAA", "Allstate", "American Family", "American National", "Auto Club", "CSAA",
        "Chubb", "Encompass", "Erie", "Farmers", "Federated Mutual", "Geico", "Hartford",
        "Horace Mann", "Kemper", "Lemonade", "Liberty Mutual", "Mercury", "MetLife",
        "Nationwide", "Progressive", "Pure", "Safeco", "Selective", "State Farm",
        "Stillwater", "Travelers", "USAA", "Wawanesa",
    ],
}

# Servpro bulletin form numbers: 5263-SF-13, 4124-F-10, 5995-F, 20044-F-4, 5822-F-R ...
FORM_RE = re.compile(r"\b(\d{3,6})\s*-\s*(SF|F)(?:\s*-\s*(\d{1,3}))?\b", re.I)
DATE_RE = re.compile(r"Last updated\s*[\r\n]*\s*([A-Z][a-z]+\s+\d{1,2},\s+\d{4})", re.I)


# --------------------------------------------------------------------------- config / io

def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    else:
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
        print(f"[i] wrote default config -> {CONFIG_PATH}")
    return cfg


def read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def now_stamp() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")


def safe_name(text: str, fallback: str = "file") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text).strip(" .")
    return (cleaned or fallback)[:120]


def qs_get(url: str, key: str) -> str:
    return (parse_qs(urlparse(url).query).get(key) or [""])[0]


# --------------------------------------------------------------------------- browser / login

def launch(pw, headless: bool, cfg: dict):
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        return pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=headless,
            accept_downloads=True,
            viewport={"width": 1440, "height": 950},
            args=["--disable-blink-features=AutomationControlled"],
        )
    except PWError as exc:
        if "executable doesn't exist" in str(exc).lower():
            sys.exit("Chromium is missing.  Run:  python -m playwright install chromium")
        raise


def on_site(page) -> bool:
    return urlparse(page.url).netloc.lower().endswith("interactgo.com")


def goto(page, url: str, cfg: dict, settle: bool = True) -> bool:
    try:
        page.goto(url, timeout=cfg["nav_timeout_ms"], wait_until="domcontentloaded")
        if settle:
            try:
                page.wait_for_load_state("networkidle", timeout=20000)
            except PWTimeout:
                pass
        page.wait_for_timeout(600)
        return True
    except (PWTimeout, PWError) as exc:
        print(f"    ! nav failed: {str(exc).splitlines()[0][:130]}")
        return False


def load_credentials() -> dict:
    creds = read_json(CRED_PATH, {})
    return {"username": (creds.get("username") or "").strip(),
            "password": creds.get("password") or ""}


# ':visible' matters - the Servpro login form has hidden fields whose names contain "user".
USER_SEL = ("input#Username:visible, input[name='Username']:visible, input[type='email']:visible, "
            "input:not([type='hidden'])[name*='user' i]:visible, "
            "input:not([type='hidden'])[id*='user' i]:visible")
PW_SEL = "input#Password:visible, input[type='password']:visible"
SUBMIT_SEL = ("button[name='button'][value='login'], button[type='submit']:visible, "
              "input[type='submit']:visible, button:visible:has-text('Log In'), "
              "button:visible:has-text('Sign In')")


def auto_login(page, cfg: dict) -> bool:
    creds = load_credentials()
    if not creds["username"] or not creds["password"]:
        print(f"[!] no credentials saved yet -> {CRED_PATH}")
        return False

    print("[i] signing in ...")
    try:
        user_box = page.locator(USER_SEL).first
        user_box.wait_for(state="visible", timeout=15000)
        user_box.fill(creds["username"])

        pw_box = page.locator(PW_SEL).first
        if pw_box.count():
            pw_box.fill(creds["password"])
        else:  # two-step form: username first, password on the next screen
            page.keyboard.press("Enter")
            pw_box = page.locator(PW_SEL).first
            pw_box.wait_for(state="visible", timeout=15000)
            pw_box.fill(creds["password"])

        submit = page.locator(SUBMIT_SEL).first
        if submit.count():
            submit.click()
        else:
            page.keyboard.press("Enter")
    except (PWTimeout, PWError) as exc:
        print(f"[!] could not fill the login form: {str(exc).splitlines()[0][:140]}")
        return False

    for _ in range(30):  # SSO bounces through a few redirects
        page.wait_for_timeout(1000)
        if on_site(page):
            print("[OK] signed in.")
            return True
    print(f"[!] still not on the site after login (url: {page.url})")
    return False


def ensure_login(page, cfg: dict, interactive: bool = False) -> bool:
    """Get us onto the real site.  Handles 'still mid-redirect' as well as a real login form."""
    for _ in range(6):
        if on_site(page):
            return True
        # Only treat it as a login form once the password box is actually rendered;
        # otherwise we're still bouncing through the SAML redirects.
        if page.locator(PW_SEL).first.count():
            break
        page.wait_for_timeout(2000)
    if on_site(page):
        return True
    if auto_login(page, cfg):
        return True
    if interactive:
        print("\nFinish signing in in the browser window (MFA, prompts, etc.).")
        input("  press Enter when you can see the SERVPRONET site > ")
        return on_site(page)
    return False


def open_site(pw, cfg: dict, headless: bool, interactive: bool = False):
    """Launch a browser, land on the site signed in.  Returns (ctx, page) or (ctx, None)."""
    ctx = launch(pw, headless=headless, cfg=cfg)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    goto(page, cfg["site_url"], cfg)
    if not ensure_login(page, cfg, interactive=interactive):
        return ctx, None
    return ctx, page


# --------------------------------------------------------------------------- listing scrape

# One entry per result card on a ContentListing page.
CARDS_JS = r"""
() => {
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  return Array.from(document.querySelectorAll('.card-content')).map(c => {
    const link = c.querySelector('header a');
    const title = clean(c.querySelector('header h5')?.innerText || link?.innerText || '');
    const summary = clean(c.querySelector('.sub-pre')?.innerText || '').slice(0, 300);

    // 'Last updated <date>' sits on a wrapper above .card-content
    let root = c;
    for (let i = 0; i < 5 && root.parentElement; i++) {
      root = root.parentElement;
      if (/last updated/i.test(root.innerText || '')) break;
    }
    const m = (root.innerText || '').match(/Last updated\s*\n?\s*([A-Z][a-z]+\s+\d{1,2},\s+\d{4})/i);

    const attachments = Array.from(c.querySelectorAll('span.attachment')).map(s => {
      const dl = s.querySelector('a[href*="Uploader.ashx"]');
      if (!dl) return null;
      const label = clean(Array.from(s.querySelectorAll('a'))
                          .find(a => !a.href.includes('Uploader.ashx'))?.innerText || '');
      return { label, url: dl.href };
    }).filter(Boolean);

    return { title, docUrl: link ? link.href : '', summary,
             lastUpdated: m ? m[1] : '', attachments };
  });
}
"""


def listing_url(sec: dict, offset: int, limit: int) -> str:
    return LISTING + "?" + urlencode({
        "section": sec["section"], "subsection": sec["subsection"],
        "q": "", "offset": offset, "limit": limit, "orderByDirection": "dateDesc",
    })


def normalize_doc_url(url: str) -> str:
    """Strip the utm_* tracking junk so the same bulletin always has the same key."""
    doc_id = qs_get(url, "id")
    return f"{SITE}/Interact/Pages/Content/Document.aspx?id={doc_id}" if doc_id else urldefrag(url)[0]


def scrape_section(page, sec: dict, cfg: dict) -> list[dict]:
    out, seen_docs = [], set()
    limit = cfg["page_size"]
    for pageno in range(cfg["max_pages_per_section"]):
        url = listing_url(sec, pageno * limit, limit)
        if not goto(page, url, cfg):
            break
        try:
            cards = page.evaluate(CARDS_JS) or []
        except PWError as exc:
            print(f"    ! read failed: {str(exc).splitlines()[0][:120]}")
            break

        fresh = [c for c in cards if normalize_doc_url(c.get("docUrl", "")) not in seen_docs]
        for card in fresh:
            seen_docs.add(normalize_doc_url(card.get("docUrl", "")))
            card["section"] = sec["name"]
            out.append(card)
        print(f"    page {pageno + 1}: {len(cards)} cards ({len(fresh)} new)  total {len(out)}")
        if len(cards) < limit or not fresh:
            break
    return out


# --------------------------------------------------------------------------- carriers / forms

def known_carriers(cfg: dict) -> list[str]:
    """Curated carrier names first, then names inferred from the local filenames."""
    curated = [n.strip() for n in cfg.get("extra_carriers", []) if n.strip()]
    learned = set()
    local = Path(cfg["local_bulletins_dir"])
    if local.is_dir():
        for f in local.iterdir():
            if not f.is_file():
                continue
            stem = FORM_RE.sub(" ", f.stem)
            stem = re.sub(r"[_\-#().0-9]+", " ", stem)
            words = [w for w in stem.split() if len(w) > 2]
            if words:
                learned.add(" ".join(words[:2]).strip())
    lower_curated = {n.lower() for n in curated}
    # longest first inside each group, so "American Family" beats "American"
    return (sorted(curated, key=len, reverse=True)
            + sorted({n for n in learned if len(n) > 2 and n.lower() not in lower_curated},
                     key=len, reverse=True))


def guess_carrier(text: str, carriers: list[str]) -> str:
    low = (text or "").lower()
    for name in carriers:
        if name.lower() in low:
            return name
    # fall back to the words before the form number, e.g. "Charter Senior Living # 20235-F"
    head = FORM_RE.split(text or "")[0].strip(" -#\u2013")
    return head[:40] or "(unclassified)"


def form_parts(text: str):
    m = FORM_RE.search(text or "")
    if not m:
        return None
    return m.group(1), m.group(2).upper(), int(m.group(3) or 0)


def form_number(text: str) -> str:
    parts = form_parts(text)
    if not parts:
        return ""
    base, kind, rev = parts
    return f"{base}-{kind}" + (f"-{rev}" if rev else "")


# --------------------------------------------------------------------------- scan

def build_records(cards: list[dict], carriers: list[str]) -> dict:
    """One record per PDF attachment (or per page when a bulletin has no attachment)."""
    items = {}
    for card in cards:
        doc_url = normalize_doc_url(card.get("docUrl", ""))
        doc_id = qs_get(card.get("docUrl", ""), "id")
        title = card.get("title", "")
        base = {
            "title": title,
            "section": card.get("section", ""),
            "doc_url": doc_url,
            "doc_id": doc_id,
            "last_updated": card.get("lastUpdated", ""),
            "summary": card.get("summary", ""),
            "carrier": guess_carrier(title, carriers),
        }
        atts = card.get("attachments") or []
        if not atts:
            items[f"doc:{doc_id or title}"] = dict(base, filename="", pdf_url="", fileguid="",
                                                   form=form_number(title), has_pdf=False)
            continue
        for att in atts:
            url = att.get("url", "")
            filename = qs_get(url, "filename") or Path(urlparse(url).path).name
            guid = qs_get(url, "fileguid")
            key = f"file:{guid}" if guid else f"doc:{doc_id}:{filename}"
            items[key] = dict(base, filename=filename, pdf_url=url, fileguid=guid, has_pdf=True,
                              attachment_label=att.get("label", ""),
                              form=form_number(f"{filename} {att.get('label','')} {title}"))
    return items


def cmd_scan(args, cfg: dict) -> int:
    carriers = known_carriers(cfg)
    stamp = now_stamp()
    cards: list[dict] = []

    with sync_playwright() as pw:
        ctx, page = open_site(pw, cfg, headless=not args.headed, interactive=args.headed)
        if page is None:
            ctx.close()
            print(f"\n[X] Not signed in.  Check {CRED_PATH}  or run:  python bulletin_watch.py login")
            return 2

        for sec in cfg["sections"]:
            print(f"\n[{sec['name']}]")
            cards += scrape_section(page, sec, cfg)

        found = build_records(cards, carriers)
        print(f"\n[i] {len(cards)} bulletins, {len(found)} tracked items")

        first_run = not MANIFEST.exists()
        prev_items = read_json(MANIFEST, {"items": {}}).get("items", {})
        new, changed, items = diff(found, prev_items, stamp)

        if first_run and not getattr(args, "fetch_all", False):
            print(f"\n[i] First run - recording {len(found)} bulletins as the baseline, no downloads.")
            print("    From now on only new/changed bulletins get downloaded.")
            print("    Want an exact local copy of every current PDF (better diffs later)?")
            print("      python bulletin_watch.py mirror")
        elif cfg["download_changed"] and (new or changed):
            fetch_pdfs(ctx, new + changed, stamp, cfg)
        ctx.close()

    removed = [rec for key, rec in prev_items.items() if key not in items]
    manifest = {"generated": stamp, "site": cfg["site_url"], "items": items}
    write_json(MANIFEST, manifest)
    write_json(SNAP_DIR / f"manifest_{stamp}.json", manifest)

    report = build_report(stamp, items, new, changed, removed)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / f"report_{stamp}.txt").write_text(report, encoding="utf-8")
    print("\n" + report)
    print(f"[i] report -> {REPORT_DIR / f'report_{stamp}.txt'}")
    if new or changed:
        print(f"[i] PDFs of new/changed bulletins -> {DL_DIR / stamp}")
    return 1 if (new or changed or removed) else 0


def diff(found: dict, prev_items: dict, stamp: str):
    """Split what we found into new / changed, carrying forward the history fields."""
    new, changed, items = [], [], {}
    prev_by_doc: dict[str, list] = {}
    for key, old in prev_items.items():
        prev_by_doc.setdefault(old.get("doc_id", ""), []).append(old)

    for key, rec in found.items():
        old = prev_items.get(key)
        rec = dict(rec)
        rec["first_seen"] = (old or {}).get("first_seen", stamp)
        rec["last_seen"] = stamp
        rec["last_changed"] = (old or {}).get("last_changed", stamp)
        for carry in ("sha256", "size", "file"):
            if old and old.get(carry):
                rec.setdefault(carry, old[carry])

        if old is None:
            # A re-issued bulletin gets a new fileguid; match it back to the same page
            # so we report "changed" (with the old revision) instead of a bare "new".
            siblings = [o for o in prev_by_doc.get(rec.get("doc_id", ""), []) if o.get("has_pdf")]
            if siblings and rec.get("has_pdf"):
                prior = siblings[0]
                rec["prev_filename"] = prior.get("filename", "")
                rec["prev_form"] = prior.get("form", "")
                rec["prev_last_updated"] = prior.get("last_updated", "")
                rec["prev_file"] = prior.get("file", "")
                rec["prev_sha256"] = prior.get("sha256", "")
                rec["first_seen"] = prior.get("first_seen", stamp)
                rec["last_changed"] = stamp
                rec["change"] = "new PDF uploaded"
                changed.append(rec)
            else:
                new.append(rec)
        else:
            reasons = []
            if rec.get("filename") != old.get("filename"):
                reasons.append(f"filename {old.get('filename','')} -> {rec.get('filename','')}")
            if rec.get("last_updated") != old.get("last_updated"):
                reasons.append(f"updated {old.get('last_updated','?')} -> {rec.get('last_updated','?')}")
            if rec.get("title") != old.get("title"):
                reasons.append("title changed")
            if reasons:
                rec["change"] = "; ".join(reasons)
                rec["prev_filename"] = old.get("filename", "")
                rec["prev_last_updated"] = old.get("last_updated", "")
                rec["prev_file"] = old.get("file", "")
                rec["prev_sha256"] = old.get("sha256", "")
                rec["last_changed"] = stamp
                changed.append(rec)
        items[key] = rec
    return new, changed, items


def find_previous_copy(rec: dict, cfg: dict) -> Path | None:
    """The version we had before: our own last download first, then the X:\\ Bulletins folder."""
    prev_name = rec.get("prev_file") or rec.get("prev_filename") or rec.get("file")
    if prev_name:
        cand = DL_DIR / "current" / safe_name(prev_name)
        if cand.is_file():
            return cand

    local = Path(cfg["local_bulletins_dir"])
    if not local.is_dir():
        return None
    parts = form_parts(f"{rec.get('prev_form','')} {rec.get('form','')} {rec.get('filename','')} {rec.get('title','')}")
    if not parts:
        return None
    base, kind, _ = parts
    best = None
    for f in local.iterdir():
        if not f.is_file() or f.suffix.lower() != ".pdf":
            continue
        fp = form_parts(f.name)
        if fp and fp[0] == base and fp[1] == kind:
            if best is None or fp[2] > best[0]:
                best = (fp[2], f)
    return best[1] if best else None


def pdf_text(path: Path) -> list[str]:
    """Plain text per line, for diffing.  Returns [] if the text can't be pulled."""
    try:
        import pdfplumber
    except ImportError:
        return []
    try:
        with pdfplumber.open(str(path)) as pdf:
            text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    except Exception as exc:  # pdfplumber raises all sorts on odd files
        return [f"<<could not read {path.name}: {exc.__class__.__name__}>>"]
    # PDFs encoded as cp1252 come out as "SERVPROÂ®" - drop the stray byte so diffs read clean.
    text = text.replace("Â", "")
    return [ln.rstrip() for ln in text.splitlines() if ln.strip()]


def write_comparison(recs: list[dict], out_dir: Path, cfg: dict) -> None:
    """Write old/ vs new/ side by side plus a readable text diff of what actually changed."""
    import difflib

    lines = ["OLD vs NEW comparison", "=" * 68,
             "old/  = the copy you had (previous download, else the X:\\ Bulletins folder)",
             "new/  = what is on SERVPRONET right now", ""]
    pairs = 0
    for rec in recs:
        new_file = out_dir / "new" / rec["file"] if rec.get("file") else None
        if not new_file or not new_file.is_file():
            continue
        title = rec.get("title") or rec.get("filename", "")
        lines += ["-" * 68, f"{rec.get('carrier','?')}: {title}",
                  f"  new: {rec.get('filename','')}   ({rec.get('size',0):,} bytes)"]

        old_src = find_previous_copy(rec, cfg)
        if old_src is None:
            lines += ["  old: (no earlier copy found - nothing to compare against)", ""]
            continue

        old_dst = out_dir / "old" / safe_name(old_src.name)
        old_dst.parent.mkdir(parents=True, exist_ok=True)
        old_dst.write_bytes(old_src.read_bytes())
        rec["compared_against"] = str(old_src)
        pairs += 1
        lines.append(f"  old: {old_src.name}   ({old_src.stat().st_size:,} bytes)   from {old_src.parent}")

        if hashlib.sha256(old_src.read_bytes()).hexdigest() == rec.get("sha256"):
            lines += ["  -> byte-identical, only the listing metadata changed", ""]
            continue

        a, b = pdf_text(old_src), pdf_text(new_file)
        if not a and not b:
            lines += ["  -> text could not be extracted (install pdfplumber for text diffs)", ""]
            continue
        diff = [d for d in difflib.unified_diff(a, b, fromfile="old", tofile="new", lineterm="", n=1)
                if not d.startswith(("---", "+++"))]
        if not diff:
            lines += ["  -> same text, different file (re-saved / formatting only)", ""]
            continue
        added = sum(1 for d in diff if d.startswith("+"))
        removed = sum(1 for d in diff if d.startswith("-"))
        lines.append(f"  -> text changed: {added} lines added, {removed} removed")
        lines += ["  " + d for d in diff[:200]]
        if len(diff) > 200:
            lines.append(f"  ... {len(diff) - 200} more diff lines")
        lines.append("")

    (out_dir / "COMPARE.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"[i] old/new comparison ({pairs} pairs) -> {out_dir / 'COMPARE.txt'}")


def fetch_pdfs(ctx, recs: list[dict], stamp: str, cfg: dict) -> None:
    """Download the bulletins that moved into their own folder, keeping the old copy beside it."""
    cur_dir = DL_DIR / "current"
    out_dir = DL_DIR / stamp
    new_dir = out_dir / "new"
    cur_dir.mkdir(parents=True, exist_ok=True)
    new_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "old").mkdir(parents=True, exist_ok=True)

    targets = [r for r in recs if r.get("pdf_url")]
    print(f"\n[i] downloading {len(targets)} new/changed PDFs -> {new_dir}")
    for i, rec in enumerate(targets, 1):
        try:
            resp = ctx.request.get(rec["pdf_url"], timeout=cfg["nav_timeout_ms"])
        except PWError as exc:
            rec["error"] = str(exc).splitlines()[0][:160]
            print(f"    ! {rec.get('filename','?')}: {rec['error']}")
            continue
        if not resp.ok:
            rec["error"] = f"HTTP {resp.status}"
            print(f"    ! {rec.get('filename','?')}: {rec['error']}")
            continue
        body = resp.body()
        rec["sha256"] = hashlib.sha256(body).hexdigest()
        rec["size"] = len(body)
        fname = safe_name(rec.get("filename") or f"bulletin_{i}")
        if not fname.lower().endswith(".pdf"):
            fname += ".pdf"
        rec["file"] = fname
        (new_dir / fname).write_bytes(body)
        print(f"    . {i:>3}/{len(targets)}  {len(body):>9,}b  {fname}")

    # Compare BEFORE refreshing current/, so the old copies are still there.
    write_comparison(targets, out_dir, cfg)
    for rec in targets:
        if rec.get("file") and (new_dir / rec["file"]).is_file():
            (cur_dir / rec["file"]).write_bytes((new_dir / rec["file"]).read_bytes())


def build_report(stamp: str, items: dict, new: list, changed: list, removed: list) -> str:
    lines = [f"SERVPRONET bulletin scan  {stamp}", "=" * 68,
             f"tracked: {len(items)}   new: {len(new)}   changed: {len(changed)}   gone: {len(removed)}", ""]

    def block(title, recs, show_change=False):
        if not recs:
            return
        lines.append(f"--- {title} ({len(recs)}) ---")
        for r in sorted(recs, key=lambda x: (x.get("carrier", ""), x.get("title", ""))):
            form = f"  [{r['form']}]" if r.get("form") else ""
            lines.append(f"  {r.get('carrier','?')}: {r.get('title','(untitled)')}{form}")
            if r.get("last_updated"):
                lines.append(f"      last updated {r['last_updated']}")
            if show_change and r.get("change"):
                lines.append(f"      {r['change']}")
            if r.get("filename"):
                lines.append(f"      {r['filename']}")
            if r.get("doc_url"):
                lines.append(f"      {r['doc_url']}")
            if r.get("error"):
                lines.append(f"      !! {r['error']}")
        lines.append("")

    block("NEW BULLETINS", new)
    block("CHANGED", changed, show_change=True)
    block("NO LONGER LISTED", removed)
    if not (new or changed or removed):
        lines += ["No changes since the last scan.", ""]

    lines.append("--- current inventory ---")
    by_sec: dict[str, list] = {}
    for rec in items.values():
        by_sec.setdefault(rec.get("section") or "?", []).append(rec)
    for sec in sorted(by_sec):
        lines.append(f"  {sec} ({len(by_sec[sec])})")
        for rec in sorted(by_sec[sec], key=lambda r: r.get("title", "")):
            mark = "" if rec.get("has_pdf") else "   (no pdf attached)"
            lines.append(f"      - {rec.get('title','')}{mark}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- compare to local folder

def download_updates(recs: list[dict], cfg: dict) -> Path | None:
    """Pull the newer site PDFs into their own folder and diff each against the copy you have."""
    stamp = now_stamp()
    out_dir = DATA_DIR / "updates" / stamp
    new_dir = out_dir / "new"
    new_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "old").mkdir(parents=True, exist_ok=True)

    print(f"\n[i] downloading {len(recs)} newer bulletins -> {new_dir}")
    with sync_playwright() as pw:
        ctx, page = open_site(pw, cfg, headless=True)
        if page is None:
            ctx.close()
            print("[X] not signed in.")
            return None
        for rec in recs:
            if not rec.get("pdf_url"):
                continue
            try:
                resp = ctx.request.get(rec["pdf_url"], timeout=cfg["nav_timeout_ms"])
                if not resp.ok:
                    print(f"    ! {rec.get('filename','?')}: HTTP {resp.status}")
                    continue
                body = resp.body()
            except PWError as exc:
                print(f"    ! {rec.get('filename','?')}: {str(exc).splitlines()[0][:120]}")
                continue
            fname = safe_name(rec.get("filename") or "bulletin")
            if not fname.lower().endswith(".pdf"):
                fname += ".pdf"
            rec["file"] = fname
            rec["sha256"] = hashlib.sha256(body).hexdigest()
            rec["size"] = len(body)
            (new_dir / fname).write_bytes(body)
            print(f"    . {len(body):>9,}b  {fname}")
        ctx.close()

    write_comparison(recs, out_dir, cfg)
    print(f"[i] new PDFs : {new_dir}")
    print(f"[i] old PDFs : {out_dir / 'old'}")
    return out_dir


def cmd_compare_local(args, cfg: dict) -> int:
    items = read_json(MANIFEST, {"items": {}}).get("items", {})
    if not items:
        print("[X] no manifest yet - run a scan first.")
        return 2
    local_dir = Path(cfg["local_bulletins_dir"])
    if not local_dir.is_dir():
        print(f"[X] local folder not reachable: {local_dir}")
        return 2

    local_best: dict[tuple, tuple] = {}
    for f in local_dir.iterdir():
        if not f.is_file():
            continue
        parts = form_parts(f.name)
        if not parts:
            continue
        base, kind, rev = parts
        prev = local_best.get((base, kind))
        if prev is None or rev > prev[0]:
            local_best[(base, kind)] = (rev, f.name)

    outdated, missing, current = [], [], []
    for rec in items.values():
        parts = form_parts(f"{rec.get('form','')} {rec.get('filename','')} {rec.get('title','')}")
        if not parts:
            continue
        base, kind, rev = parts
        have = local_best.get((base, kind))
        if have is None:
            missing.append((f"{base}-{kind}" + (f"-{rev}" if rev else ""), rec))
        elif rev > have[0]:
            outdated.append((f"{base}-{kind}", have[1], have[0], rev, rec))
        else:
            current.append((f"{base}-{kind}", have[1]))

    print(f"local folder: {local_dir}")
    print(f"site bulletins tracked: {len(items)}\n")
    if outdated:
        print(f"--- NEWER REVISION ON THE SITE ({len(outdated)}) ---")
        for form, fname, oldrev, newrev, rec in sorted(outdated, key=lambda t: (t[0], t[1])):
            print(f"  {rec.get('carrier','?')}: {form}-{newrev} on site, you have -{oldrev or '(none)'}")
            print(f"      local: {fname}")
            print(f"      site : {rec.get('filename','')}   {rec.get('doc_url','')}")
        print()
    else:
        print("--- every bulletin you keep locally is at the current revision ---\n")

    if outdated and args.download:
        download_updates([rec for _, _, _, _, rec in outdated], cfg)

    if missing:
        if args.show_missing:
            print(f"--- ON THE SITE, NOT IN YOUR FOLDER ({len(missing)}) ---")
            for form, rec in sorted(missing, key=lambda t: (t[0], t[1].get("title", ""))):
                print(f"  {rec.get('carrier','?')}: {form}  -  {rec.get('title','')}")
                print(f"      {rec.get('doc_url','')}")
            print()
        else:
            # The site carries every national account; you only file the ones you work.
            print(f"[i] {len(missing)} bulletins on the site aren't in your folder at all "
                  f"(mostly accounts you don't run) - see them with:  compare-local --show-missing")
    print(f"[i] up to date: {len(current)}")
    return 1 if outdated else 0


def cmd_audit_local(args, cfg: dict) -> int:
    """Every local file against the site, grouped by FORM NUMBER.

    `compare-local` answers "what is behind". This answers the three
    questions it cannot, all of which turned up real problems in the
    folder on 2026-08-14:

      * SUPERSEDED — the folder keeps old revisions beside new ones
        (Hartford -11 under -12, AAA -5 under -7). Nothing on disk says
        which is live, so somebody eventually opens the wrong one.
      * UNNUMBERED — 21 of 45 files carry no form number at all, so
        `compare-local` never saw them. One could be years stale and
        nothing would say so. This at least ties them to a carrier.
      * NOT ON THE SITE — a local form number the site doesn't have.
        Two of the three found were an F/SF slip in OUR filename
        ("State Farm PSP 3467-F-8" against the site's 3467-SF).

    Grouping by form number rather than by file is the point: a per-file
    view reports every superseded copy as "behind" when the current
    revision is sitting right next to it.
    """
    items = read_json(MANIFEST, {"items": {}}).get("items", {})
    if not items:
        print("[X] no manifest yet - run a scan first.")
        return 2
    local_dir = Path(cfg["local_bulletins_dir"])
    if not local_dir.is_dir():
        print(f"[X] local folder not reachable: {local_dir}")
        return 2

    # Site: best revision per form. Read form + filename + title together
    # — for some carriers the revision is ONLY in the pdf filename (the
    # title is "American Family ... - 4124-F" while the file is
    # "AFICS Bulletin 4124-F-11.pdf"), and reading the title alone
    # reports that carrier as current when it is a revision behind.
    site_best: dict[tuple, tuple] = {}
    for rec in items.values():
        parts = form_parts(f"{rec.get('form','')} {rec.get('filename','')} "
                           f"{rec.get('title','')}")
        if not parts:
            continue
        base, kind, rev = parts
        prev = site_best.get((base, kind))
        if prev is None or rev > prev[0]:
            site_best[(base, kind)] = (rev, rec)

    have: dict[tuple, list] = {}
    unnumbered: list[str] = []
    for f in sorted(local_dir.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in (".pdf", ".doc", ".docx"):
            continue
        parts = form_parts(f.name)
        if parts:
            base, kind, rev = parts
            have.setdefault((base, kind), []).append((rev, f.name))
        else:
            unnumbered.append(f.name)

    behind, current, superseded, orphan = [], [], [], []
    duplicate: list = []
    for key, files in have.items():
        files.sort(reverse=True)
        newest_rev, newest_name = files[0]
        form = f"{key[0]}-{key[1]}"
        if key not in site_best:
            orphan.append((form, newest_name))
        else:
            srev, rec = site_best[key]
            if newest_rev < srev:
                behind.append((form, rec, newest_name, newest_rev, srev))
            else:
                current.append((form, rec.get("carrier", "?"), newest_rev))
        # Same revision twice is a DUPLICATE, not a superseded copy —
        # "State Farm PSP 3467-F-8" and "State Farm Premier Service
        # Program 3467-F-8" are one bulletin filed under two names.
        # Calling that superseded would send someone deleting a current
        # file.
        older = [n for r, n in files[1:] if r < newest_rev]
        dupes = [n for r, n in files[1:] if r == newest_rev]
        if older:
            superseded.append((form, newest_name, older))
        if dupes:
            duplicate.append((form, newest_name, dupes))

    print(f"local folder: {local_dir}")
    print(f"local files: {sum(len(v) for v in have.values()) + len(unnumbered)}"
          f"   site bulletins: {len(items)}\n")

    print(f"--- MISSING THE CURRENT REVISION ({len(behind)}) ---")
    for form, rec, name, mine, theirs in sorted(behind):
        print(f"  {rec.get('carrier','?')}  [{form}]   you: -{mine}   site: -{theirs}")
        print(f"      have: {name}")
        print(f"      site: {rec.get('filename','')}   {rec.get('doc_url','')}")
    if not behind:
        print("  (none - every numbered form you keep is current)")

    print(f"\n--- CURRENT ({len(current)}) ---")
    for form, carrier, rev in sorted(current):
        print(f"  {carrier[:38]:<38} {form}{'-' + str(rev) if rev else ''}")

    print(f"\n--- SUPERSEDED COPIES STILL IN THE FOLDER ({len(superseded)}) ---")
    for form, newest, olds in sorted(superseded):
        print(f"  {form}  keeping {newest}")
        for o in olds:
            print(f"      old: {o}")
    if not superseded:
        print("  (none)")

    if duplicate:
        print(f"{chr(10)}--- SAME REVISION FILED TWICE ({len(duplicate)}) ---")
        print("  Not stale, just ambiguous - two names for one bulletin.")
        for form, keep, dupes in sorted(duplicate):
            print(f"  {form}  {keep}")
            for d in dupes:
                print(f"      also: {d}")

    if orphan:
        print(f"\n--- FORM NUMBER NOT ON THE SITE ({len(orphan)}) ---")
        print("  Often an F/SF slip in OUR filename - check before assuming "
              "the bulletin is gone.")
        for form, name in sorted(orphan):
            near = [f"{b}-{k}" for (b, k) in site_best if b == form.split("-")[0]]
            print(f"  {form:<12} {name}"
                  + (f"      site has: {', '.join(near)}" if near else ""))

    carriers = known_carriers(cfg)
    print(f"\n--- NO FORM NUMBER IN THE FILENAME ({len(unnumbered)}) ---")
    print("  compare-local cannot see these at all.")
    for name in sorted(unnumbered):
        who = guess_carrier(name, carriers)
        known = any(who.lower() in (r.get("carrier", "") or "").lower()
                    for _k, (_rev, r) in site_best.items()) if who else False
        print(f"  {name[:58]:<58} -> {who if known else '(no carrier in the name)'}")

    print(f"\nsummary: {len(behind)} behind - {len(current)} current - "
          f"{len(superseded)} superseded - {len(duplicate)} duplicate - "
          f"{len(orphan)} not on site - "
          f"{len(unnumbered)} unnumbered")
    return 1 if behind else 0


# --------------------------------------------------------------------------- helper commands

def cmd_mirror(args, cfg: dict) -> int:
    """Download every tracked PDF into downloads/current so later diffs have an exact 'before'."""
    manifest = read_json(MANIFEST, {"items": {}})
    items = manifest.get("items", {})
    if not items:
        print("[X] no manifest yet - run a scan first.")
        return 2

    cur_dir = DL_DIR / "current"
    cur_dir.mkdir(parents=True, exist_ok=True)
    todo = []
    for rec in items.values():
        if not rec.get("pdf_url"):
            continue
        fname = safe_name(rec.get("filename") or "")
        if not fname.lower().endswith(".pdf"):
            fname += ".pdf"
        if not args.force and (cur_dir / fname).is_file() and rec.get("sha256"):
            continue
        todo.append((rec, fname))

    print(f"[i] mirroring {len(todo)} PDFs -> {cur_dir}  ({len(items) - len(todo)} already local)")
    with sync_playwright() as pw:
        ctx, page = open_site(pw, cfg, headless=not args.headed, interactive=args.headed)
        if page is None:
            ctx.close()
            print("[X] not signed in.")
            return 2
        for i, (rec, fname) in enumerate(todo, 1):
            try:
                resp = ctx.request.get(rec["pdf_url"], timeout=cfg["nav_timeout_ms"])
                if not resp.ok:
                    print(f"    ! {fname}: HTTP {resp.status}")
                    continue
                body = resp.body()
            except PWError as exc:
                print(f"    ! {fname}: {str(exc).splitlines()[0][:120]}")
                continue
            (cur_dir / fname).write_bytes(body)
            rec["sha256"] = hashlib.sha256(body).hexdigest()
            rec["size"] = len(body)
            rec["file"] = fname
            if i % 25 == 0 or i == len(todo):
                print(f"    . {i}/{len(todo)}")
                write_json(MANIFEST, manifest)
        ctx.close()

    write_json(MANIFEST, manifest)
    print(f"[OK] local mirror at {cur_dir}")
    return 0


def cmd_sections(args, cfg: dict) -> int:
    """List every bulletin sub-section, so you can add more to config.json."""
    with sync_playwright() as pw:
        ctx, page = open_site(pw, cfg, headless=not args.headed, interactive=args.headed)
        if page is None:
            ctx.close()
            print("[X] not signed in.")
            return 2
        goto(page, SITE + "/Interact/Pages/Section/Default.aspx?Section=3186", cfg)
        links = page.evaluate("""() => Array.from(document.querySelectorAll('a[href*="ContentListing.aspx"]'))
            .map(a => ({t: (a.innerText||'').replace(/\\s+/g,' ').trim(), h: a.href}))""")
        ctx.close()

    seen = set()
    print("bulletin sections (add the ones you want to config.json -> \"sections\"):\n")
    for l in links:
        sub = qs_get(l["h"], "subsection")
        if not sub or sub in seen or not l["t"]:
            continue
        seen.add(sub)
        print(f'  {{"name": "{l["t"]}", "section": 3186, "subsection": {sub}}},')
    return 0


def cmd_login(args, cfg: dict) -> int:
    with sync_playwright() as pw:
        ctx = launch(pw, headless=False, cfg=cfg)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        goto(page, cfg["site_url"], cfg)
        print("\nA browser window is open - signing in with the saved credentials,")
        print("otherwise sign in yourself (MFA prompts and all).")
        ok = ensure_login(page, cfg, interactive=True)
        print(f"  current url: {page.url}")
        print("[OK] session saved." if ok else "[!] still on a login page - session may not stick.")
        ctx.close()
    return 0 if ok else 2


MAP_JS = r"""
() => Array.from(document.querySelectorAll('a[href], button')).map(e => ({
  tag: e.tagName,
  label: ((e.innerText || e.title || e.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim()).slice(0, 70),
  href: e.href || ''
}))
"""


def cmd_map(args, cfg: dict) -> int:
    url = args.url or cfg["site_url"]
    with sync_playwright() as pw:
        ctx, page = open_site(pw, cfg, headless=not args.headed, interactive=args.headed)
        if page is None:
            ctx.close()
            print("[X] not signed in.")
            return 2
        goto(page, url, cfg)
        print(f"[i] {page.url}\n[i] title: {page.title()}\n")
        elems = page.evaluate(MAP_JS) or []
        ctx.close()
    for e in elems:
        tag = "PDF " if ".pdf" in e["href"].lower() or "Uploader.ashx" in e["href"] else "    "
        print(f"{tag}{e['tag']:<7} {e['label'][:65]:<65} {e['href'][:100]}")
    out = DATA_DIR / f"map_{now_stamp()}.json"
    write_json(out, elems)
    print(f"\n[i] {len(elems)} elements -> {out}")
    return 0


def cmd_report(args, cfg: dict) -> int:
    reports = sorted(REPORT_DIR.glob("report_*.txt")) if REPORT_DIR.is_dir() else []
    if not reports:
        print("[X] no reports yet - run a scan first.")
        return 2
    print(reports[-1].read_text(encoding="utf-8"))
    return 0


# --------------------------------------------------------------------------- cli

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Watch SERVPRONET for new/changed bulletin PDFs.")
    ap.add_argument("--headed", action="store_true", help="show the browser window")
    sub = ap.add_subparsers(dest="cmd")

    p_scan = sub.add_parser("scan", help="check every configured section and report changes")
    p_scan.add_argument("--fetch-all", action="store_true",
                        help="on the very first run, download every PDF instead of just recording a baseline")
    p_cmp = sub.add_parser("compare-local", help="compare site form revisions to the local Bulletins folder")
    p_cmp.add_argument("--show-missing", action="store_true",
                       help="also list site bulletins you don't keep locally at all")
    p_cmp.add_argument("--download", action="store_true",
                       help="download the newer versions into _data/updates/<stamp>/new and diff vs your copies")
    p_mir = sub.add_parser("mirror", help="download every tracked PDF once, for exact future diffs")
    p_mir.add_argument("--force", action="store_true", help="re-download even files we already have")
    sub.add_parser("audit-local",
                   help="every local file vs the site, grouped by form "
                        "number: behind, superseded, unnumbered, orphaned")
    sub.add_parser("report", help="print the most recent scan report")
    sub.add_parser("sections", help="list every bulletin section on the site")
    sub.add_parser("login", help="sign in by hand and save the session")
    p_map = sub.add_parser("map", help="dump the links/buttons on one page")
    p_map.add_argument("url", nargs="?", help="page to inspect")

    args = ap.parse_args(argv)
    cfg = load_config()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    handlers = {
        "scan": cmd_scan,
        "compare-local": cmd_compare_local,
        "audit-local": cmd_audit_local,
        "mirror": cmd_mirror,
        "report": cmd_report,
        "sections": cmd_sections,
        "login": cmd_login,
        "map": cmd_map,
    }
    return handlers[args.cmd or "scan"](args, cfg)


if __name__ == "__main__":
    sys.exit(main())
