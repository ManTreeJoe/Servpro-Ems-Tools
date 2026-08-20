"""Render `rename_job_folders --json` as a page you can check before applying.

Every name is set in monospace, because on this page the defects ARE the
characters: a doubled comma in `CRANKSHAW, LAURA & , JEFFREY`, a trailing
space, `Abel-Farmers` carrying a carrier it shouldn't. In proportional
type none of that is visible, and this page exists to be checked.

Ordered by how much attention a row needs, not alphabetically: anything
that can't safely proceed sits at the top.
"""
import html
import io

E = html.escape


def write(d, path):
    rows = d.get("rows") or []
    collide = [r for r in rows if r.get("collides")]
    suspect = [r for r in rows if r.get("suspect") and not r.get("collides")]
    unlinked = [r for r in rows if not r.get("linked")
                and not r.get("collides") and not r.get("suspect")]
    from_card = [r for r in rows
                 if r.get("source") == "card" and not r.get("collides")
                 and not r.get("suspect") and r.get("linked")]
    cleanup = [r for r in rows
               if r.get("source") != "card" and not r.get("collides")
               and not r.get("suspect") and r.get("linked")]

    o = []
    A = o.append
    A("<title>Folder Rename Review</title>")
    A(STYLE)
    A('<header class="top">')
    A('<p class="eyebrow">Job folders &middot; dry run</p>')
    A("<h1>Folder Rename Review</h1>")
    A('<p class="lede">Nothing here has been renamed. Each row shows what a '
      "folder is called now and what it would become &mdash; the Trello "
      "card&rsquo;s client name, minus the carrier.</p>")
    A('<div class="rule"></div>')
    A('<dl class="stats">')
    for label, val, cls in (
            ("would rename", len(rows), ""),
            ("from a card", len(from_card), ""),
            ("cleanup only", len(cleanup), ""),
            ("collisions", len(collide), "bad" if collide else ""),
            ("wrong client", len(suspect), "bad" if suspect else ""),
            ("no folder link", len(unlinked), "warn" if unlinked else ""),
            ("folders scanned", d.get("folders", 0), "")):
        A(f'<div class="{cls}"><dt>{E(label)}</dt><dd>{val}</dd></div>')
    A("</dl>")
    A('<p class="caveat"><strong>How to read this.</strong> '
      '<span class="tag card">card</span> means the new name came from the '
      "job&rsquo;s Trello card, which is the record that carries the "
      "client&rsquo;s canonical spelling. "
      '<span class="tag clean">cleanup</span> means there was no card to '
      "copy, so only the obvious defects were fixed &mdash; shouting, a "
      "stray carrier, a doubled comma. A folder whose name already matches "
      "is not listed at all.</p>")
    A('<p class="caveat">Renaming a folder also updates its '
      "<code>folder_path</code> link in the same step. Without that the job "
      "still points at the old path and every lookup silently misses, which "
      "is a worse outcome than a messy name.</p>")
    A('<div class="bar" id="bar">'
      '<span class="tally"><b id="n-keep">0</b> keep</span>'
      '<span class="tally"><b id="n-skip">0</b> skip</span>'
      '<span class="tally"><b id="n-edit">0</b> edited</span>'
      '<span class="spacer"></span>'
      '<button class="act" id="copy">Copy for Claude</button>'
      '<button class="act ghost" id="reset">Reset</button>'
      '</div>')
    A("</header><main>")

    if suspect:
        A(section("Looks like a DIFFERENT client &mdash; will be skipped",
                  suspect,
                  "The new name shares no distinctive word with the old "
                  "one, so the folder probably resolved to the wrong job. "
                  "Renaming would hand one client's folder another "
                  "client's name, which is worse than a messy name. These "
                  "are never applied.", "bad", default="skip"))
    if collide:
        A(section("Collisions &mdash; will be skipped", collide,
                  "Two folders want the same name. Renaming either would "
                  "merge two jobs' files into one directory, so these are "
                  "left alone for you to settle by hand.", "bad",
                  default="skip"))
    if unlinked:
        A(section("No folder link in the database", unlinked,
                  "These would be renamed on disk, but no job currently "
                  "points at them, so there is no link to update. Safe, "
                  "but worth a glance — an unlinked job folder is "
                  "usually one nothing can find.", "warn"))
    if from_card:
        A(section("Taken from the Trello card", from_card,
                  "The card names the client; the folder drops the carrier."))
    if cleanup:
        A(section("Cleanup only — no card to copy", cleanup,
                  "Defects fixed in place. Nothing was invented."))
    A("</main>")
    A(f'<footer><p>{d.get("cards_read", 0)} Trello cards read &middot; '
      f'{d.get("folders", 0)} folders scanned &middot; dry run, nothing '
      f"renamed.</p></footer>")
    A(SCRIPT)
    io.open(path, "w", encoding="utf-8").write("\n".join(o))


def section(title, rows, blurb, kind="", default="keep"):
    """One group. `default` is the decision every row starts on: the
    blocked groups start on `skip`, so a page nobody touches already
    describes the safe outcome."""
    o = [f'<section class="grp {kind}">',
         f"<h2>{title}</h2>",
         f'<p class="count">{len(rows)} '
         f'{"folder" if len(rows) == 1 else "folders"}</p>',
         f'<p class="blurb">{blurb}</p>',
         '<div class="rows">']
    for r in rows:
        tag = "card" if r.get("source") == "card" else "clean"
        folder = r.get("folder") or ""
        target = r.get("target") or ""
        o.append(f'<article class="row" data-folder="{E(folder)}" '
                 f'data-orig="{E(target)}" data-default="{default}">')
        o.append(f'<div class="now m">{E(folder)}</div>')
        o.append('<div class="arrow">&rarr;</div>')
        o.append(f'<input class="want m" value="{E(target)}" '
                 f'spellcheck="false" aria-label="New name for {E(folder)}"/>')
        o.append('<div class="decide">'
                 '<button class="dec" data-dec="keep">keep</button>'
                 '<button class="dec" data-dec="skip">skip</button>'
                 f'<span class="tag {tag}">{tag}</span></div>')
        o.append("</article>")
    o.append("</div></section>")
    return chr(10).join(o)



STYLE = """<style>
:root{
  --ground:#F7F6F3; --panel:#FFFFFF; --ink:#1C1D21; --ink-2:#5A5B5E;
  --ink-3:#8A8578; --line:#E2DFD8; --accent:#0F6E5C; --accent-soft:#E6F0ED;
  --warn:#B4562A; --warn-soft:#F7EAE3; --shadow:0 1px 2px rgba(28,29,33,.06);
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --ground:#16171A; --panel:#1D1F23; --ink:#E8E6E1; --ink-2:#A6A49E;
    --ink-3:#7C7970; --line:#2C2F34; --accent:#5FBFA6; --accent-soft:#16302B;
    --warn:#E08A5C; --warn-soft:#33231B; --shadow:none;
  }
}
:root[data-theme="dark"]{
  --ground:#16171A; --panel:#1D1F23; --ink:#E8E6E1; --ink-2:#A6A49E;
  --ink-3:#7C7970; --line:#2C2F34; --accent:#5FBFA6; --accent-soft:#16302B;
  --warn:#E08A5C; --warn-soft:#33231B; --shadow:none;
}
*{box-sizing:border-box;}
body{margin:0; background:var(--ground); color:var(--ink);
  font-family:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
  font-size:16px; line-height:1.55;
  padding:clamp(1.5rem,4vw,4rem) clamp(1rem,4vw,3rem) 4rem;}
.m{font-family:ui-monospace,"SFMono-Regular","Cascadia Mono",Consolas,
   "Liberation Mono",monospace; font-size:.85em; letter-spacing:-.01em;
   white-space:pre-wrap; word-break:break-word;}
.top{max-width:64rem; margin:0 auto 3rem;}
.eyebrow{margin:0 0 .4rem; font-family:ui-monospace,Consolas,monospace;
  font-size:.72rem; letter-spacing:.16em; text-transform:uppercase;
  color:var(--ink-3);}
h1{margin:0 0 .6rem; font-size:clamp(2rem,5vw,2.9rem); line-height:1.1;
  font-weight:600; letter-spacing:-.02em; text-wrap:balance;}
.lede{margin:0; max-width:56ch; color:var(--ink-2); font-size:1.05rem;}
.rule{height:2px; background:var(--accent); width:3.5rem; margin:1.6rem 0;}
.stats{display:grid; gap:1px; margin:0 0 1.6rem;
  grid-template-columns:repeat(auto-fit,minmax(8.5rem,1fr));
  background:var(--line); border:1px solid var(--line);
  border-radius:3px; overflow:hidden;}
.stats>div{background:var(--panel); padding:.8rem 1rem;}
.stats dt{font-family:ui-monospace,Consolas,monospace; font-size:.65rem;
  letter-spacing:.1em; text-transform:uppercase; color:var(--ink-3);}
.stats dd{margin:.15rem 0 0; font-size:1.65rem; font-weight:600;
  font-variant-numeric:tabular-nums;}
.stats>div.bad dd{color:var(--warn);}
.stats>div.warn dd{color:var(--warn); opacity:.85;}
.caveat{max-width:64ch; font-size:.9rem; color:var(--ink-2);
  border-top:1px solid var(--line); padding-top:1rem; margin:0 0 .8rem;}
code{font-family:ui-monospace,Consolas,monospace; font-size:.85em;
  background:var(--accent-soft); color:var(--accent);
  padding:.05rem .3rem; border-radius:2px;}
main{max-width:64rem; margin:0 auto; display:flex; flex-direction:column;
  gap:2.6rem;}
.grp>h2{margin:0; font-size:1.3rem; font-weight:600; letter-spacing:-.01em;
  padding-bottom:.5rem; border-bottom:1px solid var(--line);}
.grp.bad>h2{border-bottom-color:var(--warn); color:var(--warn);}
.count{margin:.5rem 0 0; font-family:ui-monospace,Consolas,monospace;
  font-size:.7rem; letter-spacing:.1em; text-transform:uppercase;
  color:var(--ink-3);}
.blurb{margin:.4rem 0 1rem; font-size:.9rem; color:var(--ink-2);
  max-width:62ch;}
.rows{display:flex; flex-direction:column; gap:1px; background:var(--line);
  border:1px solid var(--line); border-radius:3px; overflow:hidden;}
.row{background:var(--panel); display:grid; align-items:baseline;
  grid-template-columns:1fr 1.6rem 1fr auto; gap:.6rem;
  padding:.6rem .9rem;}
.now{color:var(--ink-2); text-decoration:line-through;
  text-decoration-color:var(--ink-3); text-decoration-thickness:1px;}
.arrow{color:var(--ink-3); text-align:center;}
.want{color:var(--accent); font-weight:600;}
.grp.bad .want{color:var(--warn);}
.tag{font-family:ui-monospace,Consolas,monospace; font-size:.6rem;
  letter-spacing:.08em; text-transform:uppercase; white-space:nowrap;
  padding:.1rem .4rem; border-radius:2px; align-self:center;}
.tag.card{background:var(--accent-soft); color:var(--accent);}
.tag.clean{background:transparent; color:var(--ink-3);
  border:1px solid var(--line);}

.bar{position:sticky; top:0; z-index:5; display:flex; align-items:center;
  gap:.9rem; flex-wrap:wrap; margin:1.2rem 0 0; padding:.7rem .9rem;
  background:var(--panel); border:1px solid var(--line); border-radius:3px;
  box-shadow:var(--shadow);}
.tally{font-family:ui-monospace,Consolas,monospace; font-size:.72rem;
  letter-spacing:.08em; text-transform:uppercase; color:var(--ink-3);}
.tally b{font-size:1rem; color:var(--ink); font-variant-numeric:tabular-nums;}
.spacer{flex:1;}
.act{font:inherit; font-size:.82rem; padding:.35rem .8rem; cursor:pointer;
  border-radius:3px; border:1px solid var(--accent);
  background:var(--accent); color:#fff;}
.act.ghost{background:transparent; color:var(--ink-2);
  border-color:var(--line);}
.act:hover{filter:brightness(1.08);}
.act:focus-visible,.dec:focus-visible,.want:focus-visible{
  outline:2px solid var(--accent); outline-offset:2px;}
.decide{display:flex; align-items:center; gap:.35rem;}
.dec{font-family:ui-monospace,Consolas,monospace; font-size:.62rem;
  letter-spacing:.08em; text-transform:uppercase; cursor:pointer;
  padding:.15rem .45rem; border-radius:2px; border:1px solid var(--line);
  background:transparent; color:var(--ink-3);}
.row[data-dec="keep"] .dec[data-dec="keep"]{background:var(--accent);
  color:#fff; border-color:var(--accent);}
.row[data-dec="skip"] .dec[data-dec="skip"]{background:var(--warn);
  color:#fff; border-color:var(--warn);}
.row[data-dec="skip"] .now,.row[data-dec="skip"] .want{opacity:.45;}
.row[data-dec="skip"] .now{text-decoration:none;}
input.want{border:1px solid transparent; background:transparent;
  color:var(--accent); font-weight:600; padding:.15rem .3rem;
  border-radius:2px; width:100%; font-size:.85em;}
input.want:hover{border-color:var(--line);}
input.want:focus{border-color:var(--accent); background:var(--ground);
  outline:none;}
.row.edited input.want{border-color:var(--accent);}
.row.edited::after{content:"edited";
  font-family:ui-monospace,Consolas,monospace; font-size:.58rem;
  letter-spacing:.08em; text-transform:uppercase; color:var(--accent);}
footer{max-width:64rem; margin:3rem auto 0; padding-top:1.1rem;
  border-top:1px solid var(--line); color:var(--ink-3); font-size:.82rem;}
@media (max-width:640px){
  .row{grid-template-columns:1fr; gap:.15rem;}
  .arrow{text-align:left;}
  .now{text-decoration:none;}
}
</style>"""


SCRIPT = """<script>
(function () {
  "use strict";
  // Decisions live in localStorage so a reload — or a coffee break —
  // doesn't lose an afternoon of marking up 199 rows.
  var KEY = "rename-review-v1";
  var saved = {};
  try { saved = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) {}

  var rows = Array.prototype.slice.call(document.querySelectorAll(".row"));

  function save() {
    try { localStorage.setItem(KEY, JSON.stringify(saved)); } catch (e) {}
  }

  function paint(row) {
    var k = row.dataset.folder;
    var st = saved[k] || {};
    row.dataset.dec = st.dec || row.dataset.default;
    var input = row.querySelector(".want");
    if (st.target != null) input.value = st.target;
    row.classList.toggle("edited", input.value !== row.dataset.orig);
  }

  function tally() {
    var keep = 0, skip = 0, edited = 0;
    rows.forEach(function (row) {
      if (row.dataset.dec === "skip") skip++; else keep++;
      if (row.classList.contains("edited")) edited++;
    });
    document.getElementById("n-keep").textContent = keep;
    document.getElementById("n-skip").textContent = skip;
    document.getElementById("n-edit").textContent = edited;
  }

  rows.forEach(function (row) {
    paint(row);
    row.querySelectorAll(".dec").forEach(function (b) {
      b.addEventListener("click", function () {
        var k = row.dataset.folder;
        saved[k] = saved[k] || {};
        saved[k].dec = b.dataset.dec;
        save(); paint(row); tally();
      });
    });
    var input = row.querySelector(".want");
    input.addEventListener("input", function () {
      var k = row.dataset.folder;
      saved[k] = saved[k] || {};
      saved[k].target = input.value;
      save();
      row.classList.toggle("edited", input.value !== row.dataset.orig);
      tally();
    });
  });
  tally();

  // Only the DECISIONS are copied, never the 199 rows that were left
  // alone — a report you have to scroll past the agreement to read is
  // one nobody reads.
  document.getElementById("copy").addEventListener("click", function (e) {
    var skips = [], edits = [];
    rows.forEach(function (row) {
      var now = row.dataset.folder, orig = row.dataset.orig;
      var val = row.querySelector(".want").value;
      var dec = row.dataset.dec;
      var blocked = row.dataset.default === "skip";
      if (dec === "skip" && !blocked) skips.push(now);
      if (dec === "keep" && val !== orig) edits.push(now + "  ->  " + val);
    });
    var out = ["FOLDER RENAME REVIEW"];
    out.push("skip (" + skips.length + "):");
    skips.forEach(function (s) { out.push("  " + s); });
    out.push("retarget (" + edits.length + "):");
    edits.forEach(function (s) { out.push("  " + s); });
    if (!skips.length && !edits.length) {
      out.push("  nothing changed - the proposal is good as-is");
    }
    var text = out.join(String.fromCharCode(10));
    var btn = e.currentTarget, label = btn.textContent;
    function done(ok) {
      btn.textContent = ok ? "Copied" : "Press Ctrl+C";
      setTimeout(function () { btn.textContent = label; }, 1600);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { done(true); },
                                              function () { fallback(); });
    } else { fallback(); }
    function fallback() {
      var ta = document.createElement("textarea");
      ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (err) { ok = false; }
      document.body.removeChild(ta); done(ok);
    }
  });

  document.getElementById("reset").addEventListener("click", function () {
    saved = {}; save();
    rows.forEach(function (row) {
      row.querySelector(".want").value = row.dataset.orig;
      paint(row);
    });
    tally();
  });
})();
</script>"""
