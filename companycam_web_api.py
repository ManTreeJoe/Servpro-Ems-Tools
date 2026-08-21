"""The CompanyCam API surface, shared by every panel that renders the
job card.

`web_shared/audit_detail.js` is ONE detail card used by Audit AND
Snapshot, and it draws a "Pull CompanyCam" button. Defining these on
audit_web alone meant that button existed in Snapshot with nothing behind
it — the same trap that put a dead ⚙ Job info button there, so the fix is
the same: a mixin both inherit, not a copy in each file.

Module-level `os`, `persistence`, `audit_logic` and `config` are imported
here rather than relied on from the host module, so the mixin works in any
panel that inherits it.
"""
import os

import audit_logic
import config as _cfg
import persistence


class CompanyCamApi:
    """Mix into a panel's `Api` class. pywebview exposes inherited methods
    exactly like defined ones."""

    def _cc_card_terms(self, card_id: str):
        """(insured_name, address_hint) from a Trello card. CompanyCam
        projects are named by the INSURED — the card carries it as its
        "Insured - Carrier" title and a "Customer Name:" line in the body;
        the body value wins (it's the fuller spelling)."""
        if not card_id:
            return "", ""
        try:
            import trello_client as tc
            card = tc.get_card(card_id) or {}
        except Exception:
            return "", ""
        import re as _re
        name = (card.get("name") or "").split(" - ")[0].strip()  # drop " - Carrier"
        desc = card.get("desc") or ""
        m = _re.search(r"Customer Name:\s*(.+)", desc)
        if m and m.group(1).strip():
            name = m.group(1).strip()
        addr = ""
        m = _re.search(r"Address:\s*(.+)", desc)
        if m:
            addr = m.group(1).strip()
        return name, addr

    def _cc_resolve(self, client: str, card_id: str = ""):
        """Best CompanyCam project id for a job → (pid, matched_name). Tries
        the job name (+ graph cache), then falls back to the Trello INSURED
        name + address (projects are named by insured, and the run-doc name
        is often junk like 'Lastname/POC'). Pins the winner so the next
        lookup is a cache hit."""
        import companycam_api as cc
        try:
            pid = cc.find_project_id(client, use_graph=True,
                                     trello_card=card_id) or ""
        except Exception:
            pid = ""
        if pid:
            return pid, client
        name, addr = self._cc_card_terms(card_id)
        if name and name.lower() != (client or "").strip().lower():
            try:
                res = cc.find_project(name, address_hint=addr)
                m = res.get("match") if res.get("ok") else None
                if m:
                    try:
                        import ems_db
                        ems_db.resolve_and_link(
                            client, companycam_project=m["id"],
                            trello_card=card_id, create=True,
                            source="companycam")
                    except Exception:
                        pass
                    return m["id"], m["name"]
            except Exception:
                pass
        return "", ""

    def companycam_search(self, query: str) -> dict:
        """Manual project search for the pick-fallback — returns candidate
        projects (name/address/score) so the user can connect a job whose
        CompanyCam project is named differently than the run-doc name."""
        try:
            import companycam_api as cc
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        if not cc.is_configured():
            return {"ok": False, "error": "CompanyCam token not set"}
        try:
            res = cc.find_project(query or "")
            cands = list(res.get("candidates", []) or [])
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        # Photo count per candidate, and drop the dead ones.
        #
        # Two projects for one loss routinely carry the SAME name — the
        # Bell Mountain pair were both "Menifee Union School District
        # (Bell Mountain ) - 8/14", identical address, and one of them
        # 404s because it was deleted while still appearing in search
        # results. Name and address alone make that choice a coin flip;
        # "151 photos" against "gone" makes it obvious, and the count is
        # what a person is really picking by.
        #
        # Capped: this is an API call per candidate, and nobody reads
        # past the first handful.
        for c in cands[:8]:
            pid = str(c.get("id") or "")
            if not pid:
                continue
            try:
                photos = cc.list_project_photos(pid, per_page=100, max_pages=2)
                c["photo_count"] = len(photos or [])
                c["approx"] = len(photos or []) >= 200
            except Exception:
                # A project that cannot be read is not a choice — say so
                # rather than offering it as though it were fine.
                c["unavailable"] = True
        return {"ok": True, "candidates": cands}

    def companycam_configured(self) -> dict:
        """Whether a CompanyCam token is set — lets a panel hide a
        CompanyCam option entirely rather than offer one that can only
        fail (the New Loss dialog uses this)."""
        try:
            import companycam_api as cc
            return {"ok": True, "configured": bool(cc.is_configured())}
        except Exception as ex:
            return {"ok": False, "configured": False, "error": str(ex)}

    def companycam_pin(self, client: str, project_id: str,
                       card_id: str = "") -> dict:
        """Remember a manually-picked CompanyCam project for a job so every
        future probe/pull is a cache hit."""
        if not (client and project_id):
            return {"ok": False, "error": "missing client / project"}
        project_id = str(project_id)
        try:
            import ems_db
            ems_db.resolve_and_link(
                client, companycam_project=project_id,
                trello_card=card_id, create=True, source="companycam")
            # Drop any OTHER CompanyCam link on this job, or the pin does
            # nothing at all.
            #
            # `job_links` is keyed on (job, type, VALUE), so pinning a
            # different project ADDS a row rather than replacing one — and
            # `get_link` returns the OLDEST match. So once an auto-match
            # had written the wrong project, every later pin was recorded
            # and then ignored, and the job resolved to the first answer
            # forever. That is why Bell Mountain kept reading as empty:
            # 112272489 (0 photos) was cached ahead of 112251669 (29).
            #
            # A job has exactly ONE CompanyCam project, so picking one is
            # a replacement, not an addition. (Trello cards are
            # deliberately many-per-job, which is why this is not done
            # for them.)
            # If this half fails, the pin is RECORDED AND IGNORED — the
            # old link keeps winning and the user is told it worked. It
            # used to swallow the error and still return ok:True, which
            # is the exact "half-applied, reported green" failure the pin
            # is meant to fix. Say so instead.
            removed, problem = [], ""
            try:
                job = ems_db.find_job_by_name(client)
                if not job:
                    problem = (f"pinned, but no job named {client!r} to pin it "
                               f"to — the old project may still win")
                else:
                    ck = job["canon_key"]
                    for ln in (ems_db.get_links(ck, ems_db.LINK_COMPANYCAM)
                               or []):
                        val = str(ln.get("link_value") or "")
                        if val and val != project_id:
                            ems_db.remove_link(ck, ems_db.LINK_COMPANYCAM, val)
                            removed.append(val)
                    # Prove it: re-read what the resolver will actually
                    # see, rather than trusting that the writes landed.
                    now = ems_db.get_link(ck, ems_db.LINK_COMPANYCAM)
                    if str(now or "") != project_id:
                        problem = (f"pin did not take — the job still "
                                   f"resolves to {now or 'nothing'}")
            except Exception as ex:
                problem = f"could not clear the old project: {ex}"
            if problem:
                try:
                    import ems_log
                    ems_log.error("companycam", f"pin {client!r} -> "
                                                f"{project_id}: {problem}")
                except Exception:
                    pass
                return {"ok": False, "project_id": project_id,
                        "replaced": removed, "error": problem}
            return {"ok": True, "project_id": project_id,
                    "replaced": removed}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def companycam_probe(self, client: str, card_id: str = "") -> dict:
        """New-photo count + the uploaders (creator_name) for a job, without
        downloading — so the UI can show the count + pre-fill the tech picker.
        Resolves the project by job name AND the Trello insured name."""
        if not client:
            return {"ok": False, "error": "no client"}
        try:
            import companycam_api as cc
        except Exception as ex:
            return {"ok": False, "error": f"companycam_api unavailable: {ex}"}
        if not cc.is_configured():
            return {"ok": False, "error": "CompanyCam token not set"}
        pid, mname = self._cc_resolve(client, card_id)
        if not pid:
            return {"ok": True, "matched": False, "count": 0, "uploaders": []}
        try:
            pr = cc.probe_new(pid)
            out = {"ok": True, "matched": True, "matched_name": mname,
                   "count": pr.get("count", 0),
                   "project_id": pid,
                   "uploaders": pr.get("uploaders", [])}
            if not out["count"]:
                out["alternates"] = self._cc_alternates(pid)
            return out
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def _cc_alternates(self, pid: str) -> list:
        """Other projects at the same address that DO have photos.

        One job can end up with two CompanyCam projects under different
        names, and the photos live on only one. Observed on Bell
        Mountain: "Menifee Union School District (Bell Mountain ) - 8/14"
        (0 photos) and "Bell Mountain Middle School" (29), both at
        28525 La Piedra Rd. The name match was exact and correct — it
        just landed on the empty one, so the pull reported no photos for
        a job that plainly had them.

        Only consulted when the matched project is EMPTY, so the normal
        path costs nothing. Suggested, never switched to automatically:
        which project is right is a judgement about the job, and the
        photos are the evidence to judge on.
        """
        try:
            import companycam_api as cc
            proj = cc.get_project(pid)
            if not proj or not proj.get("address"):
                return []
            out = []
            for sib in cc.siblings_at_address(proj["address"], pid, limit=4):
                try:
                    # Two pages is plenty to say "this one has the photos"
                    # without walking a huge project to count exactly.
                    photos = cc.list_project_photos(
                        sib["id"], per_page=100, max_pages=2) or []
                except Exception:
                    continue
                if not photos:
                    continue
                sib = dict(sib)
                sib["count"] = len(photos)
                sib["approx"] = len(photos) >= 200
                out.append(sib)
            out.sort(key=lambda s: -s["count"])
            return out
        except Exception:
            return []

    def _cc_contents_dir(self, client: str) -> str:
        r"""The job's CONTENTS folder — where contents-tagged photos go.

        Derived from the resolved PICS path rather than re-resolving the
        job, so the two can never point at different jobs. PICS sits at
        `<job>\EMS\PICS`, so stripping the trailing PICS and the EMS
        above it lands back on the job root.

        Contents work is filed under `<job>\CONTENTS` by the office (99
        live folders) and that is where the audit's contents check looks;
        a photo tagged Contents left in `EMS\PICS\Contents` sits
        somewhere nothing reads.
        """
        pics = self._cc_pics_dir(client)
        if not pics:
            return ""
        parts = os.path.normpath(pics).split(os.sep)
        while parts and parts[-1].strip().upper() in ("PICS", "EMS"):
            parts.pop()
        if not parts:
            return ""
        return os.path.join(os.sep.join(parts), "CONTENTS")


    def _cc_docs_dir(self, client: str) -> str:
        r"""The job's `EMS\DOCS` folder — where Scope-tagged photos go.

        A scope is paperwork. Left in PICS it sat among the stage folders,
        which is not where anyone filing or reading paperwork looks, and
        the audit's document checks never saw it.

        Derived from the resolved PICS path so the two can never point at
        different jobs: PICS is `<job>\EMS\PICS`, so its sibling is
        `<job>\EMS\DOCS`.
        """
        pics = self._cc_pics_dir(client)
        if not pics:
            return ""
        parts = os.path.normpath(pics).split(os.sep)
        if parts and parts[-1].strip().upper() == "PICS":
            parts.pop()
        if not parts:
            return ""
        return os.path.join(os.sep.join(parts), "DOCS")

    def _cc_pics_dir(self, client: str) -> str:
        """The job's PICS folder, or "" when the job folder isn't resolved.

        The pinned path is NOT always the job root. Pinning a subfolder is
        how an unknown job gets attached by hand, and appending EMS\\PICS
        to a path that already ends in one built
        `…\\EMS\\PICS\\EMS\\PICS` — which was then returned WITHOUT
        checking it exists, so every photo read as missing and a pull
        would have filed them into a folder nobody would ever look in.

        So: if the pin is already inside a PICS tree, use that PICS root.
        """
        import config as _cfg
        base = (_cfg.load() or {}).get("audit_base") or ""
        try:
            path = persistence.get_folder_path(client) or ""
        except Exception:
            path = ""
        if not path:
            try:
                p, _bn, _yr = audit_logic.try_resolve_folder_by_terms(
                    base, [client])
                path = p or ""
            except Exception:
                path = ""
        if not path or not os.path.isdir(path):
            return ""

        # Already in a PICS tree? Walk back up to the PICS root itself —
        # pulls organise into <stage>\<tech date>\<room> BELOW it, so
        # anything deeper would nest a second layout inside the first.
        parts = os.path.normpath(path).split(os.sep)
        for i in range(len(parts) - 1, -1, -1):
            if parts[i].strip().upper() == "PICS":
                return os.sep.join(parts[:i + 1])

        pics = os.path.join(path, "EMS", "PICS")
        if os.path.isdir(pics):
            return pics
        alt = os.path.join(path, "PICS")
        if os.path.isdir(alt):
            return alt
        # Neither exists yet — a first pull legitimately creates one, so
        # hand back the intended path rather than refusing.
        return pics

    def companycam_verify(self, client: str, card_id: str = "") -> dict:
        """Compare the job folder against CompanyCam, photo by photo.

        The high-water mark only records what has been SEEN, so a folder
        that was emptied — or a download that failed — still reports "no
        new photos" while photos are genuinely absent. This ignores the
        watermark and diffs by photo id, which is what the folder actually
        contains.

        Returns counts plus a per-photo breakdown so the dialog can show
        WHAT is missing (room / stage / who took it / when), not just how
        many.
        """
        if not client:
            return {"ok": False, "error": "no client"}
        try:
            import companycam_api as cc
        except Exception as ex:
            return {"ok": False, "error": f"companycam_api unavailable: {ex}"}
        if not cc.is_configured():
            return {"ok": False, "error": "CompanyCam token not set"}
        pid, mname = self._cc_resolve(client, card_id)
        if not pid:
            return {"ok": True, "matched": False,
                    "error": f"No CompanyCam project matched '{client}'"}
        pics = self._cc_pics_dir(client)
        if not pics:
            return {"ok": False,
                    "error": "No job folder — pin/find the folder first"}
        try:
            v = cc.verify_project(pid, pics)
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        if not v.get("ok"):
            return {"ok": False, "error": v.get("error") or "verify failed"}
        # Describe each missing photo so the operator can sanity-check the
        # list before downloading anything.
        missing = []
        try:
            cc.attach_tags(v.get("missing_photos") or [])
        except Exception:
            pass
        import datetime as _d
        for p in (v.get("missing_photos") or []):
            room, stage, qual = "", "", ""
            try:
                room, stage, qual = cc.classify_tags(p.get("tags"))
            except Exception:
                pass
            when = ""
            try:
                if p.get("captured_at"):
                    when = _d.datetime.fromtimestamp(
                        int(p["captured_at"])).strftime("%m/%d %I:%M%p")
            except Exception:
                pass
            missing.append({
                "id": p.get("id"), "when": when,
                "who": p.get("creator_name") or "",
                "stage": stage, "room": room, "qualifier": qual,
                "dest": os.path.join(*[x for x in (stage, room, qual) if x])
                        if (stage or room or qual) else "(top level)",
            })
        return {"ok": True, "matched": True, "matched_name": mname,
                "project_id": pid, "pics": pics,
                "total": v.get("total", 0), "present": v.get("present", 0),
                "missing": v.get("missing", 0),
                "extra_files": v.get("extra_files", 0),
                "missing_photos": missing}

    def companycam_pull_missing(self, client: str, tech: str = "",
                                card_id: str = "",
                                dest_subfolder: str = "") -> dict:
        """Download whatever the folder is missing, ignoring the watermark.

        `companycam_pull_one` asks "anything newer than last time?"; this
        asks "does the folder hold everything?" — the question that matters
        after a folder is cleaned out or a pull half-failed.
        """
        if not client:
            return {"ok": False, "error": "no client"}
        try:
            import companycam_api as cc
        except Exception as ex:
            return {"ok": False, "error": f"companycam_api unavailable: {ex}"}
        pid, _m = self._cc_resolve(client, card_id)
        if not pid:
            return {"ok": False,
                    "error": f"No CompanyCam project matched '{client}'"}
        pics = self._cc_pics_dir(client)
        if not pics:
            return {"ok": False,
                    "error": "No job folder — pin/find the folder first"}
        try:
            os.makedirs(pics, exist_ok=True)
        except OSError:
            pass
        stage = (dest_subfolder or "").strip()
        if stage.upper() == "AUTO":
            stage = ""
        try:
            r = cc.pull_missing_photos(pid, pics, subfolder=stage,
                                       contents_dir=self._cc_contents_dir(client),
                                       docs_dir=self._cc_docs_dir(client),
                                       tech=(tech or "")) or {}
            return {"ok": True, "pulled": r.get("downloaded", 0),
                    "skipped": r.get("skipped", 0), "pics": pics,
                    "rooms": r.get("rooms", {}), "stages": r.get("stages", {})}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def companycam_plan_pull(self, client: str, tech: str = "",
                             card_id: str = "",
                             dest_subfolder: str = "") -> dict:
        """What a pull would bring in, grouped by shoot — day, what was
        done, how many, and where it lands.

        "142 photos missing" can't be acted on: 142 photos is usually four
        or five separate visits, and you may want yesterday's demo but not
        a re-shoot of the initial. One row per (stage, tech + date), so the
        choice is per shoot.
        """
        if not client:
            return {"ok": False, "error": "no client"}
        try:
            import companycam_api as cc
        except Exception as ex:
            return {"ok": False, "error": f"companycam_api unavailable: {ex}"}
        pid, _m = self._cc_resolve(client, card_id)
        if not pid:
            return {"ok": False,
                    "error": f"No CompanyCam project matched '{client}'"}
        pics = self._cc_pics_dir(client)
        if not pics:
            return {"ok": False,
                    "error": "No job folder — pin/find the folder first"}
        stage = (dest_subfolder or "").strip()
        if stage.upper() == "AUTO":
            stage = ""
        try:
            r = cc.plan_pull(pid, pics, subfolder=stage, tech=(tech or ""),
                             contents_dir=self._cc_contents_dir(client),
                             docs_dir=self._cc_docs_dir(client))
            if r.get("ok"):
                r["pics"] = pics
                self._suggest_stages_from_run_doc(client, r.get("groups"))
            return r
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def _suggest_stages_from_run_doc(self, client: str, groups) -> None:
        """Fill `suggested_stage` on every shoot CompanyCam left untagged,
        from what the run doc says that client was scheduled for that day.

        Untagged shoots otherwise put the whole job on the user to
        remember — days later, for a visit they may not have been on. The
        run doc recorded it at the time.

        Advisory only: it pre-selects a dropdown the user can change. It
        is never applied on its own, because filing photos under the wrong
        stage hides them somewhere nobody looks. Best-effort throughout —
        a missing run doc must not break the pull.
        """
        if not groups:
            return
        try:
            import run_doc
        except Exception:
            return
        cache = {}
        for g in groups:
            if (g.get("stage") or "") not in ("", "(no stage tag)"):
                continue          # CompanyCam already said what this is
            day = (g.get("date") or "").strip()
            if not day:
                continue
            if day not in cache:
                try:
                    cache[day] = run_doc.suggest_pics_stage(day, client) or ""
                except Exception:
                    cache[day] = ""
            if cache[day]:
                g["suggested_stage"] = cache[day]
                g["suggested_from"] = "run doc"

    def companycam_pull_assigned(self, client: str, assignments: list,
                                 tech: str = "", card_id: str = "") -> dict:
        """Pull the ticked shoots, each into the stage chosen for IT.

        One stage for a whole project is wrong whenever a job has more than
        one visit — Gary Mongue's 181 untagged photos are eight shoots by
        six techs across six dates, and they are not all "Initial". So the
        caller sends [{photo_ids: [...], stage: "Demo"}, …] and each group
        is pulled with its own destination.
        """
        if not client:
            return {"ok": False, "error": "no client"}
        groups = [g for g in (assignments or []) if (g or {}).get("photo_ids")]
        if not groups:
            return {"ok": False, "error": "nothing selected"}
        try:
            import companycam_api as cc
        except Exception as ex:
            return {"ok": False, "error": f"companycam_api unavailable: {ex}"}
        pid, _m = self._cc_resolve(client, card_id)
        if not pid:
            return {"ok": False,
                    "error": f"No CompanyCam project matched '{client}'"}
        pics = self._cc_pics_dir(client)
        if not pics:
            return {"ok": False,
                    "error": "No job folder — pin/find the folder first"}

        pulled = skipped = 0
        errors = []
        for g in groups:
            ids = [str(i) for i in (g.get("photo_ids") or []) if str(i).strip()]
            if not ids:
                continue
            stage = (g.get("stage") or "").strip()
            if stage.upper() == "AUTO":
                stage = ""
            # A tech typed on the row OVERRIDES CompanyCam's creator.
            # The creator is whoever's phone took the shot, which isn't
            # always who the folder should be filed under.
            row_tech = (g.get("tech") or "").strip()
            try:
                r = cc.pull_new_photos(
                    pid, pics, since_epoch=None, subfolder=stage,
                    tech=(row_tech or tech or ""), only_ids=ids,
                    force_tech=bool(row_tech),
                    contents_dir=self._cc_contents_dir(client),
                    docs_dir=self._cc_docs_dir(client),
                    # Never advance past shoots deliberately skipped —
                    # they'd fall behind the mark and go unpullable.
                    advance_watermark=False) or {}
                pulled += r.get("downloaded", 0)
                skipped += r.get("skipped", 0)
                if r.get("failed"):
                    errors.append(f"{stage or 'untagged'}: "
                                  f"{r['failed']} failed to download"
                                  f"{' — ' + r['error'] if r.get('error') else ''}")
            except Exception as ex:
                # One bad shoot must not lose the others already pulled.
                errors.append(f"{stage or 'untagged'}: {ex}")
        return {"ok": True, "pulled": pulled, "skipped": skipped,
                "pics": pics, "error": "; ".join(errors)}

    def _cc_emit(self, event: str, payload: dict) -> None:
        """Push a CustomEvent to the panel. Best-effort — a pull must never
        fail because the window it was launched from has gone away.

        Deliberately uses the instance-free `_emit_js_all` rather than
        `self._emit`: Snapshot's Api has no `_emit` at all, and a
        per-instance emit silently no-ops when `self._window` is None,
        which would strand the UI on "Pulling…" with no completion event
        ever arriving. `_emit_js_all` targets every open window and
        forwards into the content iframe, where the listeners actually
        live — the same reason `do_import` uses it.
        """
        import json as _json
        js = ("window.dispatchEvent(new CustomEvent(" + _json.dumps(event)
              + ", {detail: " + _json.dumps(payload) + "}));")
        try:
            import audit_web
            audit_web._emit_js_all(js)
        except Exception:
            pass

    def companycam_pull_assigned_bg(self, client: str, assignments: list,
                                    tech: str = "", card_id: str = "") -> dict:
        """Start the pull on a background thread and return immediately.

        A pull is minutes of downloading over someone else's API. Awaiting
        it held the dialog open and the panel unusable for the whole time,
        behind a button that said "Pulling…" and gave no idea how far along
        it was. The work is identical; only the waiting changes.

        Progress arrives as `companycam:pull-progress` events (one per
        shoot) and a final `companycam:pull-done` carrying exactly what
        `companycam_pull_assigned` returns, so the UI reports the outcome
        the same either way.
        """
        if not client:
            return {"ok": False, "error": "no client"}
        groups = [g for g in (assignments or []) if (g or {}).get("photo_ids")]
        if not groups:
            return {"ok": False, "error": "nothing selected"}
        total = sum(len(g.get("photo_ids") or []) for g in groups)

        def _run():
            done = 0
            try:
                # One event per SHOOT, not per photo: enough to show
                # movement without a message per download.
                for i, g in enumerate(groups, 1):
                    self._cc_emit("companycam:pull-progress", {
                        "client": client, "i": i, "n": len(groups),
                        "stage": (g.get("stage") or "").strip() or "untagged",
                        "done": done, "total": total,
                    })
                    done += len(g.get("photo_ids") or [])
                res = self.companycam_pull_assigned(
                    client, groups, tech, card_id) or {}
            except Exception as ex:
                res = {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
            res["client"] = client
            self._cc_emit("companycam:pull-done", res)

        try:
            from web_helpers import run_bg
            run_bg(_run)
        except Exception as ex:
            return {"ok": False, "error": f"couldn't start: {ex}"}
        return {"ok": True, "started": True, "groups": len(groups),
                "total": total}

    def companycam_pull_groups(self, client: str, photo_ids: list,
                               tech: str = "", card_id: str = "",
                               dest_subfolder: str = "") -> dict:
        """Pull ONLY the shoots ticked in the preview, all into one stage.
        Superseded by `companycam_pull_assigned`; kept for callers that
        genuinely want a single destination."""
        if not client:
            return {"ok": False, "error": "no client"}
        ids = [str(i) for i in (photo_ids or []) if str(i).strip()]
        if not ids:
            return {"ok": False, "error": "nothing selected"}
        try:
            import companycam_api as cc
        except Exception as ex:
            return {"ok": False, "error": f"companycam_api unavailable: {ex}"}
        pid, _m = self._cc_resolve(client, card_id)
        if not pid:
            return {"ok": False,
                    "error": f"No CompanyCam project matched '{client}'"}
        pics = self._cc_pics_dir(client)
        if not pics:
            return {"ok": False,
                    "error": "No job folder — pin/find the folder first"}
        stage = (dest_subfolder or "").strip()
        if stage.upper() == "AUTO":
            stage = ""
        try:
            r = cc.pull_new_photos(
                pid, pics, since_epoch=None, subfolder=stage,
                tech=(tech or ""), only_ids=ids,
                contents_dir=self._cc_contents_dir(client),
                docs_dir=self._cc_docs_dir(client),
                # The watermark must NOT advance past shoots deliberately
                # skipped, or they go invisible to the next "anything new?"
                # check and become silently unpullable.
                advance_watermark=False) or {}
            return {"ok": True, "pulled": r.get("downloaded", 0),
                    "skipped": r.get("skipped", 0), "pics": pics}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def companycam_pull_one(self, client: str, dest_subfolder: str = "",
                            tech: str = "", card_id: str = "") -> dict:
        """Pull NEW CompanyCam photos for ONE job into its PICS folder (into
        `dest_subfolder` stage if given), named with `tech`. Only new photos
        (per-project water-mark), so it's safe to re-run."""
        if not client:
            return {"ok": False, "error": "no client"}
        try:
            import companycam_api as cc
        except Exception as ex:
            return {"ok": False, "error": f"companycam_api unavailable: {ex}"}
        if not cc.is_configured():
            return {"ok": False,
                    "error": "CompanyCam token not set (Settings → CompanyCam)"}
        import config as _cfg
        base = (_cfg.load() or {}).get("audit_base") or ""
        path = ""
        try:
            path = persistence.get_folder_path(client) or ""
        except Exception:
            path = ""
        if not path:
            try:
                p, _bn, _yr = audit_logic.try_resolve_folder_by_terms(base, [client])
                path = p or ""
            except Exception:
                path = ""
        if not path or not os.path.isdir(path):
            return {"ok": False,
                    "error": "No job folder — pin/find the folder first"}
        pics = os.path.join(path, "EMS", "PICS")
        if not os.path.isdir(pics):
            alt = os.path.join(path, "PICS")
            pics = alt if os.path.isdir(alt) else pics
        try:
            os.makedirs(pics, exist_ok=True)
        except OSError:
            pass
        pid, _mname = self._cc_resolve(client, card_id)
        if not pid:
            return {"ok": False,
                    "error": f"No CompanyCam project matched '{client}'"}
        stage = (dest_subfolder or "").strip()
        if stage.upper() == "AUTO":
            stage = ""
        try:
            r = cc.pull_new_photos(
                pid, pics, subfolder=stage, tech=(tech or ""),
                contents_dir=self._cc_contents_dir(client),
                docs_dir=self._cc_docs_dir(client)) or {}
            return {"ok": True, "pulled": r.get("downloaded", 0),
                    "skipped": r.get("skipped", 0), "pics": pics,
                    "stage": stage}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def companycam_sync(self, dry: bool = False) -> dict:
        """Bulk-pull NEW CompanyCam photos into each ACTIVE job's PICS folder.
        Active = today's run-doc jobs. On-demand; pulls only new photos (per-
        project high-water mark), so re-running is safe. `dry` matches without
        downloading — returns the new-photo count per job."""
        try:
            import companycam_api as cc
        except Exception as ex:
            return {"ok": False, "error": f"companycam_api unavailable: {ex}"}
        if not cc.is_configured():
            return {"ok": False,
                    "error": "CompanyCam token not set (Settings → CompanyCam)"}
        names = []
        try:
            doc = _find_run_doc_for_date(_dt.date.today())
            if doc:
                jobs, _rd = _state_hub.parse_run_doc(doc)
                seen = set()
                for j in jobs:
                    n = (j.get("client") or "").strip()
                    if n and n.lower() not in seen:
                        seen.add(n.lower())
                        names.append(n)
        except Exception as ex:
            return {"ok": False, "error": f"run-doc read failed: {ex}"}
        if not names:
            return {"ok": True, "total": 0, "results": [],
                    "note": "No active jobs in today's run-doc"}
        import config as _cfg
        base = (_cfg.load() or {}).get("audit_base") or ""
        results, total = [], 0
        for name in names:
            path = ""
            try:
                path = persistence.get_folder_path(name) or ""
            except Exception:
                path = ""
            if not path:
                try:
                    p, _bn, _yr = audit_logic.try_resolve_folder_by_terms(base, [name])
                    path = p or ""
                except Exception:
                    path = ""
            if not path or not os.path.isdir(path):
                results.append({"job": name, "matched": False, "reason": "no folder"})
                continue
            pics = os.path.join(path, "EMS", "PICS")
            if not os.path.isdir(pics):
                alt = os.path.join(path, "PICS")
                pics = alt if os.path.isdir(alt) else pics
            if not dry:
                try:
                    os.makedirs(pics, exist_ok=True)
                except OSError:
                    pass
            pid = ""
            try:
                pid = cc.find_project_id(name, use_graph=False) or ""
            except Exception:
                pid = ""
            if not pid:
                results.append({"job": name, "matched": False,
                                "reason": "no CompanyCam project"})
                continue
            if dry:
                try:
                    cnt = cc.count_new_photos(pid)
                except Exception:
                    cnt = 0
                results.append({"job": name, "matched": True, "new": cnt})
                total += cnt
                continue
            try:
                r = cc.pull_new_photos(pid, pics) or {}
                dl = r.get("downloaded", 0)
                results.append({"job": name, "matched": True, "pulled": dl,
                                "skipped": r.get("skipped", 0)})
                total += dl
            except Exception as ex:
                results.append({"job": name, "matched": True, "error": str(ex)})
        return {"ok": True, "total": total, "results": results}

