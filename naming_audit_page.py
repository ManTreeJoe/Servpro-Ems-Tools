"""Render `commercial_naming_audit` to a self-contained page.

Names are set in monospace throughout, because on this page the defects
ARE the characters — the doubled space in "Menifee Union School District
 1.23.26", the trailing space in "Menifee School District- Freedom Crest ",
"Elementry" misspelled, "(Bell Mountain C8. )". In proportional type none
of that is visible, which would make the page a worse tool than the
folder listing it replaces.
"""
import html
import io

E = html.escape


def _conf(sc):
    if sc >= 0.6:
        return "hi", "firm"
    if sc >= 0.35:
        return "mid", "likely"
    return "lo", "check"


def write(d, path):
    ps = d["parents"]
    jobs = [j for p in ps for j in p["jobs"]]
    nofold = sum(1 for j in jobs if not j["od_now"])
    nocc = sum(1 for j in jobs if not j["cc_now"])
    check = sum(1 for j in jobs
                if (j["od_now"] and j["od_score"] < 0.35)
                or (j["cc_now"] and j["cc_score"] < 0.35))
    orph = sum(len(p["orphan_folders"]) for p in ps)

    o = []
    A = o.append
    A("<title>Three-System Naming Audit</title>")
    A(STYLE)
    A('<header class="top">')
    A('<p class="eyebrow">Commercial &amp; multi-site jobs</p>')
    A("<h1>Three-System Naming Audit</h1>")
    A('<p class="lede">Every commercial job is named three times &mdash; in '
      "the job folder, on the Trello card, and in CompanyCam &mdash; and "
      "almost never the same way twice. The card is the source: it is the "
      "only record carrying all four fields.</p>")
    A('<div class="rule"></div>')
    A('<dl class="stats">')
    for label, val in (("live jobs", len(jobs)), ("clients", len(ps)),
                       ("no folder", nofold), ("no cc project", nocc),
                       ("needs a look", check),
                       ("folders, no card", orph)):
        A(f"<div><dt>{E(label)}</dt><dd>{val}</dd></div>")
    A("</dl>")
    A('<div class="key"><h2>Parent &ndash; Site &ndash; Room &ndash; Date</h2>'
      '<p class="note">Four fields; each system shows the ones it needs. A '
      "field the job doesn&rsquo;t have is simply left out.</p>"
      '<table class="conv">'
      '<tr><th>Trello</th><td class="m">Menifee Union School District - '
      "Callie Kirkpatrick Elementary - Room 9 - 6/9/26</td></tr>"
      '<tr><th>Folder</th><td class="m">Callie Kirkpatrick Elementary - '
      "Room 9 - 8.14.26</td></tr>"
      '<tr><th>CompanyCam</th><td class="m">Callie Kirkpatrick Elementary - '
      "Room 9</td></tr>"
      '<tr><th>No rooms</th><td class="m">Coreland Company - Dicks Sporting '
      "Goods - 3/19/26</td></tr>"
      '</table><p class="note">The folder sits inside the client folder '
      "already, so it drops the client. CompanyCam drops the date too "
      "&mdash; the project is the place, not the visit.</p>"
      '<h2 class="second">Name &ndash; Insurance &ndash; Claim</h2>'
      '<p class="note">A household with more than one claim uses a '
      "different arrangement: the insurer appears on Trello only, and "
      "CompanyCam keeps the name.</p>"
      '<table class="conv">'
      '<tr><th>Trello</th><td class="m">Nathan Bupte - AAA - 1st Claim'
      "</td></tr>"
      '<tr><th>Folder</th><td class="m">1st Claim</td></tr>'
      '<tr><th>CompanyCam</th><td class="m">Nathan Bupte - 1st Claim'
      "</td></tr></table></div>")
    A('<p class="caveat"><strong>On the matching.</strong> Folders and '
      "CompanyCam projects are tied to a card by comparing site, room and "
      "date after removing the client name. Room numbers count as identity "
      '&mdash; <span class="m">Room 9</span> never matches '
      '<span class="m">Room 33</span> &mdash; because without that rule two '
      "Kirkpatrick jobs were assigned each other&rsquo;s photos. Weak "
      'matches say <span class="chip lo">check</span> rather than pretending '
      "to be settled. Closed work (LOGS, AR, Recon Closeout) is left "
      "out.</p>")
    A("</header><main>")

    for p in sorted(ps, key=lambda x: -len(x["jobs"])):
        A('<section class="client">')
        A(f'<h2>{E(p["parent"])}</h2>')
        n = len(p["jobs"])
        A(f'<p class="count">{n} live {"job" if n == 1 else "jobs"}</p>')
        for j in p["jobs"]:
            A('<article class="job">')
            A(f'<h3 class="m">{E(j["want_folder"] or j["card"])}</h3>')
            A(f'<p class="lane">{E(j["board"])} &middot; {E(j["lane"])}</p>')
            if j.get("kind") == "unclear":
                # The card names an insurer and nothing else, on a client
                # that has several claim folders. Which claim this card is
                # simply isn't in the data.
                A('<p class="ask"><strong>Which claim is this?</strong> The '
                  'card gives only the insurer, and this client has more '
                  'than one claim folder. Add the claim number to the card '
                  '&mdash; <span class="m">'
                  f'{E(j["card"])} - 1st Claim</span> &mdash; and the '
                  'folder and project follow from it.</p>')
                A(f'<p class="cardnow m">{E(j["card"])}</p>')
                A("</article>")
                continue
            A('<table class="cmp"><tbody>')
            for label, now, want, sc in (
                    ("Trello", j["card"], j["want_trello"], 1.0),
                    ("Folder", j["od_now"], j["want_folder"], j["od_score"]),
                    ("CompanyCam", j["cc_now"], j["want_cc"], j["cc_score"])):
                if not now:
                    A(f"<tr><th>{label}</th>"
                      '<td class="none">nothing found</td>'
                      '<td><span class="chip lo">create</span></td></tr>'
                      '<tr class="want"><th></th>'
                      f'<td class="m tgt">{E(want)}</td>'
                      '<td class="tag">name it</td></tr>')
                    continue
                same = " ".join(now.split()) == " ".join(want.split())
                cls, lab = _conf(sc)
                chip = ('<span class="chip hi">as wanted</span>' if same
                        else f'<span class="chip {cls}">{lab}</span>')
                A(f"<tr><th>{label}</th>"
                  f'<td class="m {"ok" if same else "bad"}">{E(now)}</td>'
                  f"<td>{chip}</td></tr>")
                if not same:
                    A('<tr class="want"><th></th>'
                      f'<td class="m tgt">{E(want)}</td>'
                      '<td class="tag">rename to</td></tr>')
            A("</tbody></table></article>")
        if p["orphan_folders"]:
            A('<div class="orphans"><h4>Folders with no live card</h4>'
              '<p class="note">Most will be finished work. Any that '
              "isn&rsquo;t needs a card.</p><ul>")
            for f in p["orphan_folders"]:
                A(f'<li class="m">{E(f)}</li>')
            A("</ul></div>")
        A("</section>")
    A("</main>")
    A(f'<footer><p>Built from the job share, all Trello boards and '
      f'{d["totals"]["projects"]} CompanyCam projects. Read-only &mdash; '
      f"nothing was renamed.</p></footer>")
    io.open(path, "w", encoding="utf-8").write("\n".join(o))


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
body{
  margin:0; background:var(--ground); color:var(--ink);
  font-family:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
  font-size:16px; line-height:1.55;
  padding:clamp(1.5rem,4vw,4rem) clamp(1rem,4vw,3rem) 4rem;
}
.m{font-family:ui-monospace,"SFMono-Regular","Cascadia Mono",Consolas,
   "Liberation Mono",monospace; font-size:.86em; letter-spacing:-.01em;
   white-space:pre-wrap; word-break:break-word;}
.top{max-width:62rem; margin:0 auto 3.5rem;}
.eyebrow{margin:0 0 .4rem; font-family:ui-monospace,Consolas,monospace;
  font-size:.72rem; letter-spacing:.16em; text-transform:uppercase;
  color:var(--ink-3);}
h1{margin:0 0 .6rem; font-size:clamp(2rem,5vw,2.9rem); line-height:1.1;
  font-weight:600; letter-spacing:-.02em; text-wrap:balance;}
.lede{margin:0; max-width:58ch; color:var(--ink-2); font-size:1.05rem;}
.rule{height:2px; background:var(--accent); width:3.5rem; margin:1.6rem 0;}
.stats{display:grid; gap:1px; margin:0 0 2rem;
  grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));
  background:var(--line); border:1px solid var(--line);
  border-radius:3px; overflow:hidden;}
.stats>div{background:var(--panel); padding:.85rem 1rem;}
.stats dt{font-family:ui-monospace,Consolas,monospace; font-size:.66rem;
  letter-spacing:.1em; text-transform:uppercase; color:var(--ink-3);}
.stats dd{margin:.15rem 0 0; font-size:1.7rem; font-weight:600;
  font-variant-numeric:tabular-nums;}
.key{background:var(--panel); border:1px solid var(--line);
  border-left:3px solid var(--accent); border-radius:3px;
  padding:1.1rem 1.3rem; margin-bottom:1.5rem;}
.key h2{margin:0 0 .3rem; font-size:1rem; letter-spacing:.01em;}
.key h2.second{margin-top:1.4rem; padding-top:1.1rem;
  border-top:1px solid var(--line);}
.ask{margin:0 0 .6rem; padding:.7rem .9rem; border-radius:3px;
  background:var(--warn-soft); color:var(--ink-2); font-size:.88rem;}
.ask strong{color:var(--warn);}
.cardnow{margin:0; color:var(--ink-3); font-size:.84rem;}
.conv{border-collapse:collapse; width:100%; margin-top:.7rem;}
.conv th{text-align:left; vertical-align:top; padding:.3rem 1rem .3rem 0;
  white-space:nowrap; font-size:.78rem; color:var(--ink-3); font-weight:600;}
.conv td{padding:.3rem 0; color:var(--accent);}
.note{margin:.6rem 0 0; font-size:.86rem; color:var(--ink-2);}
.caveat{max-width:62ch; font-size:.9rem; color:var(--ink-2);
  border-top:1px solid var(--line); padding-top:1.1rem;}
main{max-width:62rem; margin:0 auto; display:flex; flex-direction:column;
  gap:2.8rem;}
.client{display:flex; flex-direction:column; gap:1rem;}
.client>h2{margin:0; font-size:1.35rem; font-weight:600; letter-spacing:-.01em;
  padding-bottom:.5rem; border-bottom:1px solid var(--line);}
.count{margin:-.7rem 0 0; font-family:ui-monospace,Consolas,monospace;
  font-size:.7rem; letter-spacing:.1em; text-transform:uppercase;
  color:var(--ink-3);}
.job{background:var(--panel); border:1px solid var(--line); border-radius:3px;
  padding:1rem 1.1rem; box-shadow:var(--shadow);}
.job h3{margin:0 0 .2rem; font-size:.95rem; font-weight:600;}
.lane{margin:0 0 .8rem; font-family:ui-monospace,Consolas,monospace;
  font-size:.66rem; letter-spacing:.08em; text-transform:uppercase;
  color:var(--ink-3);}
.cmp{width:100%; border-collapse:collapse; display:block; overflow-x:auto;}
.cmp th{text-align:left; white-space:nowrap; vertical-align:top;
  padding:.3rem .9rem .3rem 0; font-size:.74rem; font-weight:600;
  color:var(--ink-3); width:6.5rem;}
.cmp td{padding:.3rem 0; vertical-align:top;}
.cmp td.tag{white-space:nowrap; text-align:right; padding-left:1rem;
  font-family:ui-monospace,Consolas,monospace; font-size:.64rem;
  letter-spacing:.08em; text-transform:uppercase; color:var(--ink-3);}
.ok{color:var(--ink);} .bad{color:var(--warn);} .tgt{color:var(--accent);}
.none{color:var(--ink-3); font-style:italic; font-size:.9rem;}
tr.want td{padding-top:0;}
.chip{display:inline-block; padding:.1rem .45rem; border-radius:2px;
  font-family:ui-monospace,Consolas,monospace; font-size:.62rem;
  letter-spacing:.08em; text-transform:uppercase; white-space:nowrap;}
.chip.hi{background:var(--accent-soft); color:var(--accent);}
.chip.mid{background:var(--accent-soft); color:var(--accent); opacity:.75;}
.chip.lo{background:var(--warn-soft); color:var(--warn);}
.orphans{background:var(--panel); border:1px dashed var(--line);
  border-radius:3px; padding:.9rem 1.1rem;}
.orphans h4{margin:0; font-size:.82rem;}
.orphans ul{margin:.7rem 0 0; padding-left:1.1rem; display:flex;
  flex-direction:column; gap:.25rem;}
.orphans li{color:var(--ink-2); font-size:.84rem;}
footer{max-width:62rem; margin:3.5rem auto 0; padding-top:1.2rem;
  border-top:1px solid var(--line); color:var(--ink-3); font-size:.82rem;}
</style>"""
