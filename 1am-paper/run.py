"""The 1 A.M. Paper: make tonight's issue.

  python run.py                 make an issue (needs OPENROUTER_API_KEY)
  python run.py --mode check    test the paper search and full-text download only
                                (no model calls, nothing written)

Pipeline: Europe PMC search -> code ranks candidates -> Nemotron picks two ->
code downloads full text -> Nemotron writes each story as JSON -> code checks every
number against the paper -> Nemotron writes the linking thread -> code builds the page,
the log and the archive.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import sys

from amp import europepmc as epmc
from amp import llm as llm_mod
from amp import numcheck, render, state, util

ROOT = pathlib.Path(__file__).resolve().parent
DOCS = ROOT / "docs"
PROMPTS = ROOT / "prompts"


def log(msg: str = "") -> None:
    print(msg, flush=True)


def prompt(name: str, **values) -> str:
    text = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


def system_prompt() -> str:
    reader = os.environ.get("READER_PROFILE") or (PROMPTS / "reader_profile.md").read_text(encoding="utf-8")
    return prompt("reader", READER=reader.strip())


# ------------------------------------------------------------------ candidates

def gather(cfg, the_log, today, n, deps):
    core = cfg["core_categories"]
    wildcard = n % 4 == 0
    sunday = today.weekday() == 6
    target = "wildcard" if wildcard else state.lead_category(the_log, core)
    seen = state.seen_keys(the_log)
    cats = core + (["wildcard"] if wildcard else [])

    def collect(days):
        start = today - dt.timedelta(days=days)
        pools = {}
        for c in cats:
            pools[c] = epmc.find_candidates(cfg, c, start, today, seen, get_json=deps["get_json"], log=log)
            log(f"  {c:30s} {len(pools[c]):3d} candidates ({days} days)")
        return pools

    log(f"Searching Europe PMC (lead category: {target}{', wildcard night' if wildcard else ''}"
        f"{', Sunday classic' if sunday else ''})")
    pools = collect(cfg["recent_days"])
    widened = False
    total = sum(len(v) for v in pools.values())
    if total < cfg["min_candidates_before_widening"] or len(pools[target]) < 2:
        log(f"Only {total} candidates; widening to {cfg['widen_days']} days")
        pools = collect(cfg["widen_days"])
        widened = True
    classics = {}
    if sunday:
        cutoff = today - dt.timedelta(days=3 * 365)
        for c in core:
            if c != target:
                classics[c] = epmc.find_classics(cfg, c, cutoff, seen, get_json=deps["get_json"], log=log)[:2]
    return {"target": target, "wildcard": wildcard, "sunday": sunday, "pools": pools,
            "classics": classics, "widened": widened}


def shortlist(cfg, g):
    picks = list(g["pools"][g["target"]][:12])
    for c, papers in g["pools"].items():
        if c != g["target"]:
            picks += papers[:5]
    for papers in g["classics"].values():
        picks += papers
    ids = {}
    for i, p in enumerate(picks, 1):
        ids[f"c{i}"] = p
    return ids


def describe(cid, p, cfg):
    kind = "[classic] " if p.classic else ""
    cat = cfg["categories"][p.category]["kicker"]
    venue = f"{p.journal} (preprint)" if p.is_preprint else p.journal
    return (f"{cid} | {kind}{cat} | {venue} | {p.pub_date} | {p.title}\n"
            f"    {util.truncate_words(p.abstract, 90)}")


# ------------------------------------------------------------------ selection

def choose(cfg, g, ids, the_log, n, today, llm):
    if g["wildcard"]:
        lead_rule = ("must be a candidate in the Wildcard category: a creative idea from outside his usual "
                     "fields (soft robotics, materials science, physics, ecology, mechanical engineering) "
                     "whose thinking move transfers to his work.")
    else:
        kick = cfg["categories"][g["target"]]["kicker"]
        lead_rule = (f"prefer the {kick} category (it is due in the rotation), unless a candidate in "
                     f"another category is clearly more inventive.")
    second_rule = ("must be a [classic] candidate: an older, famously clever paper." if g["classics"]
                   else "any category, recent paper.")
    text = prompt("select", N=n, DATE=today.isoformat(), LEAD_RULE=lead_rule, SECOND_RULE=second_rule,
                  RECENT="; ".join(state.recent_headlines(the_log)) or "none yet",
                  CANDIDATES="\n".join(describe(cid, p, cfg) for cid, p in ids.items()))

    def validate(obj):
        probs = []
        for k in ("lead", "second"):
            v = obj.get(k)
            if isinstance(v, str):
                obj[k] = v = [v]
            if not v or not all(x in ids for x in v):
                probs.append(f'"{k}" must list candidate ids from the list (got {v!r})')
        return probs

    try:
        obj, _ = llm.ask_json([{"role": "system", "content": system_prompt()},
                               {"role": "user", "content": text}], validate=validate, max_tokens=8000)
        log(f"Model picked lead {obj['lead']} and second {obj['second']}: {obj.get('why', '')}")
        return obj["lead"], obj["second"]
    except llm_mod.ModelError as e:
        log(f"  ! selection by model failed ({e}); falling back to the code ranking")
        return [], []


def resolve(cfg, g, ids, lead_ids, second_ids, deps):
    """Turn ranked ids into two papers that really have usable full text."""
    tried = set()

    def ok(p):
        if p.key in tried:
            return None
        tried.add(p.key)
        xml = epmc.fetch_fulltext_xml(p, get_text=deps["get_text"], get_json=deps["get_json"])
        if not xml:
            log(f"  - no full text: {p.title[:70]}")
            return None
        try:
            parsed = epmc.parse_jats(xml)
        except Exception as e:
            log(f"  - full text unreadable ({e}): {p.title[:70]}")
            return None
        words = epmc.body_words(parsed)
        if words < cfg["min_body_words"]:
            log(f"  - full text too short ({words} words): {p.title[:70]}")
            return None
        log(f"  + full text OK ({words} words): {p.title[:70]}")
        return parsed

    def unique(papers):
        out, keys = [], set()
        for p in papers:
            if p.key not in keys:
                keys.add(p.key)
                out.append(p)
        return out

    all_ranked = sorted(ids.values(), key=lambda p: p.score, reverse=True)
    lead_order = unique([ids[i] for i in lead_ids] + list(g["pools"][g["target"]]) + all_ranked)
    lead = None
    for p in lead_order[:10]:
        if p.classic:
            continue
        parsed = ok(p)
        if parsed:
            lead = (p, parsed)
            break
    if not lead:
        raise RuntimeError("no lead candidate had usable open-access full text")

    if g["classics"]:
        fallback = [p for ps in g["classics"].values() for p in ps]
    else:
        fallback = all_ranked
    second_order = [p for p in unique([ids[i] for i in second_ids] + fallback)
                    if p.category != lead[0].category and (p.classic or not g["classics"])]
    second = None
    for p in second_order[:10]:
        parsed = ok(p)
        if parsed:
            second = (p, parsed)
            break
    if not second:
        raise RuntimeError("no second candidate (different category) had usable full text")
    return lead, second


# ------------------------------------------------------------------ writing

def _clean_story(obj: dict) -> dict:
    if isinstance(obj.get("problem"), str):
        obj["problem"] = [obj["problem"]]
    for k in ("what_they_did", "stats", "terms"):
        if not isinstance(obj.get(k), list):
            obj[k] = []
    obj["what_they_did"] = [x for x in obj["what_they_did"] if isinstance(x, dict)]
    obj["stats"] = [x for x in obj["stats"] if isinstance(x, dict)]
    fig = obj.get("figure")
    if fig is not None and not isinstance(fig, dict):
        obj["figure"] = None
    elif isinstance(fig, dict):
        fig["bars"] = [b for b in (fig.get("bars") or []) if isinstance(b, dict)]
    if not isinstance(obj.get("move"), dict):
        obj["move"] = {}
    if not isinstance(obj.get("quiz"), dict):
        obj["quiz"] = {}
    env = obj.get("envelope")
    if env is not None and not (isinstance(env, dict) and env.get("equation")):
        obj["envelope"] = None
    return obj


def validate_story(obj: dict) -> list[str]:
    obj = _clean_story(obj)
    probs = []
    for k in ("headline", "your_turn", "trick_name", "trick", "for_your_work", "limits"):
        if not isinstance(obj.get(k), str) or not obj[k].strip():
            probs.append(f'"{k}" is missing or empty')
    if not obj.get("problem"):
        probs.append('"problem" is missing')
    steps = obj.get("what_they_did") or []
    if len(steps) < 3 or not all(isinstance(s, dict) and s.get("text") for s in steps):
        probs.append('"what_they_did" needs 3 to 6 items, each {"title", "text"}')
    if not obj.get("stats"):
        probs.append('"stats" needs 2 or 3 items')
    if not obj["move"].get("name") or not obj["move"].get("how"):
        probs.append('"move" needs "name" and "how"')
    if not obj["quiz"].get("q") or not obj["quiz"].get("a"):
        probs.append('"quiz" needs "q" and "a"')
    fig = obj.get("figure")
    if fig:
        bars = fig.get("bars") or []
        try:
            vals = [float(b["value"]) for b in bars]
            if not (2 <= len(bars) <= 6) or min(vals) < 0 or max(vals) <= 0:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            probs.append('"figure.bars" needs 2 to 6 bars with numeric "value" ≥ 0 (or set "figure": null)')
    return probs


def write_story(cfg, the_log, n, slot, paper, parsed, g, llm):
    is_lead = slot == "lead"
    moves = "\n".join(f'{m["no"]}. {m["name"]} {m["gist"]}' for m in the_log.get("moves", [])) or "(none yet)"
    if paper.category == "wildcard":
        note = "This is the WILDCARD: an idea from outside his fields. Use 'for_your_work' to explain concretely how the move transfers to his work."
        topic_note = " (here: name the outside field, e.g. Soft robotics)"
    elif paper.classic:
        note = "This is a CLASSIC: an older, famously clever paper. Explain why the idea was clever when it appeared."
        topic_note = ""
    else:
        note = ""
        topic_note = ""
    text = prompt(
        "story", SLOT_NAME="LEAD" if is_lead else "SECOND", N=n, SLOT_NOTE=note,
        TITLE=paper.title, JOURNAL=paper.journal, PUB_DATE=paper.pub_date,
        PREPRINT_NOTE=" — PREPRINT, not yet peer reviewed" if paper.is_preprint else "",
        AUTHORS=render.authors_short(paper.authors), AFFILIATION=paper.last_author_affiliation or "unknown",
        PAPER_TEXT=epmc.paper_text_for_model(parsed, cfg["max_fulltext_words"]),
        MOVES=moves, WORDS="420" if is_lead else "280", TOPIC_NOTE=topic_note,
        PROBLEM_WORDS="90" if is_lead else "60", TRICK_WORDS="110" if is_lead else "80",
        STEPS="4 to 6" if is_lead else "3 to 4", STATS="2 to 3" if is_lead else "2",
        SURPRISE_RULE=("Optional: one surprising finding with its number (max 60 words), or empty string"
                       if is_lead else "empty string"),
    )
    messages = [{"role": "system", "content": system_prompt()}, {"role": "user", "content": text}]
    story, convo = llm.ask_json(messages, validate=validate_story)
    story = _clean_story(story)

    # Number check against the whole paper (not just the trimmed text the model saw).
    meta_text = " ".join([paper.title, paper.abstract, paper.pub_date, paper.journal, paper.volume, paper.pages])
    source_nums = numcheck.numbers_in(parsed["all_text"] + " " + meta_text)
    bad = numcheck.unmatched(story, source_nums)
    if bad:
        listing = "\n".join(f"- {field}: {', '.join(nums)}" for field, nums in bad.items())
        log(f"  · {sum(map(len, bad.values()))} numbers not found in the paper; asking for a fix")
        try:
            fixed, _ = llm.ask_json(convo + [{"role": "user", "content": prompt("repair", UNMATCHED=listing)}],
                                    validate=validate_story)
            fixed = _clean_story(fixed)
            if sum(map(len, numcheck.unmatched(fixed, source_nums).values())) < sum(map(len, bad.values())):
                story = fixed
        except llm_mod.ModelError as e:
            log(f"  ! repair failed: {e}")

    # Anything still unverified: drop it from stat tiles and figure bars; flag it elsewhere.
    bad = numcheck.unmatched(story, source_nums)
    dropped = []
    if bad:
        keep_stats = [s for i, s in enumerate(story["stats"]) if f"stats[{i}]" not in bad]
        dropped += [s.get("value", "") for i, s in enumerate(story["stats"]) if f"stats[{i}]" in bad]
        story["stats"] = keep_stats
        fig = story.get("figure")
        if fig:
            bars = [b for i, b in enumerate(fig["bars"]) if f"figure.bars[{i}]" not in bad]
            if len(bars) < len(fig["bars"]):
                dropped.append("figure bars")
            fig["bars"] = bars
            if len(bars) < 2:
                story["figure"] = None
                dropped.append("figure")
    remaining = {k: v for k, v in numcheck.unmatched(story, source_nums).items()}
    checked = numcheck.count_checked(story)
    return story, {"checked": checked, "unmatched": remaining, "dropped": dropped}


def write_thread(n, lead, second, llm):
    def move_text(s):
        return f'{s["move_name"]} {s["move"].get("how", "")}'
    text = prompt("thread", N=n, LEAD_HEADLINE=lead["headline"], LEAD_TRICK_NAME=lead["trick_name"],
                  LEAD_TRICK=lead["trick"], LEAD_MOVE=move_text(lead),
                  SECOND_HEADLINE=second["headline"], SECOND_TRICK_NAME=second["trick_name"],
                  SECOND_TRICK=second["trick"], SECOND_MOVE=move_text(second))

    def validate(obj):
        return [f'"{k}" is missing' for k in ("h1", "intro", "one_line", "takeaway")
                if not isinstance(obj.get(k), str) or not obj[k].strip()]
    try:
        obj, _ = llm.ask_json([{"role": "system", "content": system_prompt()},
                               {"role": "user", "content": text}], validate=validate, max_tokens=6000)
        return obj
    except llm_mod.ModelError as e:
        log(f"  ! thread failed ({e}); using a plain fallback")
        return {"h1": lead["move_name"].rstrip("."), "intro": f'{lead["trick_name"]}, and {second["trick_name"]}.',
                "one_line": lead["move_name"], "takeaway": lead["move_name"]}


# ------------------------------------------------------------------ main

def run(mode: str, deps: dict, force: bool = False) -> dict:
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    log_path = DOCS / "log.json"
    the_log = state.load_log(log_path)
    now = deps.get("now") or util.local_now(cfg["timezone"])
    today = now.date() if isinstance(now, dt.datetime) else now
    n = state.next_issue_no(the_log)
    log(f"The 1 A.M. Paper · issue No. {n} · {today.isoformat()} · mode={mode}")

    if mode == "full" and not force and any(i.get("date") == today.isoformat() for i in the_log["issues"]):
        log("An issue already exists for today; nothing to do (use --force to make another).")
        return {"status": "skipped"}

    g = gather(cfg, the_log, today, n, deps)

    if mode == "check":
        log("\nFull-text check (top candidate per category):")
        for c, papers in g["pools"].items():
            for p in papers[:1]:
                xml = epmc.fetch_fulltext_xml(p, get_text=deps["get_text"], get_json=deps["get_json"])
                try:
                    words = epmc.body_words(epmc.parse_jats(xml)) if xml else 0
                except Exception:
                    words = 0
                log(f"  {c:30s} {'OK ' if words >= cfg['min_body_words'] else 'NO '} {words:6d} words · "
                    f"{p.journal} · {p.title[:60]}")
        log("\nCheck finished. No model calls were made and nothing was written.")
        return {"status": "checked"}

    llm = deps["llm"]
    ids = shortlist(cfg, g)
    if len(ids) < 2:
        raise RuntimeError("fewer than 2 candidates found; nothing to write about")
    log(f"Shortlist: {len(ids)} papers")
    lead_ids, second_ids = choose(cfg, g, ids, the_log, n, today, llm)
    (lead_p, lead_parsed), (second_p, second_parsed) = resolve(cfg, g, ids, lead_ids, second_ids, deps)

    stories, checks = [], []
    next_move = state.next_move_no(the_log)
    new_moves = []
    for slot, paper, parsed in (("lead", lead_p, lead_parsed), ("second", second_p, second_parsed)):
        log(f"Writing {slot}: {paper.title[:80]}")
        s, chk = write_story(cfg, the_log, n, slot, paper, parsed, g, llm)
        existing = state.move_by_no(the_log, s["move"].get("reuse_no"))
        if existing:
            s["move_no"] = existing["no"]
            s["move_name"] = existing["name"]
            s["move_label"] = f'Invention move {existing["no"]:02d} · again'
        else:
            s["move_no"] = next_move
            s["move_name"] = s["move"]["name"].strip()
            s["move_label"] = f"Invention move {next_move:02d}"
            new_moves.append({"no": next_move, "name": s["move_name"], "gist": s["move"].get("how", ""),
                              "example": s["move"].get("example", ""), "issue": n})
            next_move += 1
        kicker = cfg["categories"][paper.category]["kicker"]
        if paper.category == "wildcard":
            kicker = f"Wildcard · {s.get('topic') or 'Outside the field'}"
        slot_name = "Lead" if slot == "lead" else "Second"
        s["slot_label"] = f"{slot_name} · Classic · {kicker}" if paper.classic else f"{slot_name} · {kicker}"
        lab = (s.get("lab") or "").strip()
        if not lab or len(lab) > 80:
            lab = f"{paper.authors[-1]} lab" if paper.authors else ""
        s["lab"] = lab
        venue = f"{paper.journal} preprint" if paper.is_preprint else paper.journal
        d = util.parse_date(paper.pub_date)
        s["kicker_meta"] = " · ".join(x for x in (venue, util.fmt_short(d) if d else paper.pub_date, lab) if x)
        stories.append(s)
        checks.append(chk)

    log("Writing the thread")
    thread = write_thread(n, stories[0], stories[1], llm)

    quiz = [dict(stories[0]["quiz"]), dict(stories[1]["quiz"])]
    rep = state.spaced_repetition(the_log, n, today)
    if rep:
        quiz.append(rep)

    # number-check note
    total = sum(c["checked"] for c in checks)
    flagged = []
    for slot, c in zip(("lead", "second"), checks):
        for field, nums in c["unmatched"].items():
            flagged += [f"{x} ({slot}, {field.split('[')[0].replace('_', ' ')})" for x in nums]
    if flagged:
        check_note = (f"Number check: {total - len(flagged)} of {total} numbers matched the papers' full text. "
                      f"Not found, verify before relying on them: {'; '.join(flagged)}.")
    else:
        check_note = f"Number check: all {total} numbers matched the papers' full text."

    access = lambda p: "preprint" if p.is_preprint else "open access"
    sources = [render.source_html(lead_p, access(lead_p)), render.source_html(second_p, access(second_p))]
    models = sorted(llm.models_used) or [llm.model]
    model_note = "Written by " + ", ".join(m.split("/")[-1] for m in models) + " via OpenRouter."

    tpl = render.Template(ROOT / "template" / "issue-template.html")
    page = render.issue_html(tpl, n=n, date=today, thread=thread, stories=stories, quiz=quiz,
                             sources=sources, check_note=check_note, archive_href="../index.html",
                             model_note=model_note, minutes=6)
    words = render.visible_words(page)
    minutes = max(3, round(words / 220))
    if minutes != 6:
        page = page.replace("· ~6 min</div>", f"· ~{minutes} min</div>", 1)

    issue_file = DOCS / "issues" / f"issue-{n:03d}.html"
    issue_file.parent.mkdir(parents=True, exist_ok=True)
    issue_file.write_text(page, encoding="utf-8")
    site = os.environ.get("SITE_URL", "").rstrip("/")
    url = f"{site}/issues/issue-{n:03d}.html" if site else f"issues/issue-{n:03d}.html"

    entry = {
        "no": n, "date": today.isoformat(), "url": url,
        "headline": thread["h1"], "takeaway": thread["takeaway"],
        "wildcard": g["wildcard"], "classic": any(p.classic for p in (lead_p, second_p)),
        "stories": [
            {"slot": slot, "headline": s["headline"], "category": p.category, "journal": p.journal,
             "pub_date": p.pub_date, "doi": p.doi or "", "id": p.id, "lab": s["lab"], "move": s["move_no"]}
            for slot, s, p in (("lead", stories[0], lead_p), ("second", stories[1], second_p))],
        "terms": list(dict.fromkeys(t for s in stories for t in s.get("terms", []) if isinstance(t, str))),
        "quiz": [{"q": quiz[0]["q"], "a": quiz[0]["a"]}, {"q": quiz[1]["q"], "a": quiz[1]["a"]}]
                + ([{"q": f'{rep["q"]} (from No. {rep["from"]})', "a": rep["a"]}] if rep else []),
        "model": models,
        "number_check": {"checked": total, "not_found": flagged},
        "words": words,
        "widened_to_30_days": g["widened"],
    }
    the_log["issues"].append(entry)
    the_log.setdefault("moves", []).extend(new_moves)
    state.save_log(log_path, the_log)
    (DOCS / "index.html").write_text(render.archive_html(tpl, the_log, cfg["categories"]), encoding="utf-8")

    notes = []
    if g["widened"]:
        notes.append("stories older than 14 days (widened to 30)")
    if flagged:
        notes.append(f"{len(flagged)} unverified number(s) flagged")
    dropped = [d for c in checks for d in c["dropped"]]
    if dropped:
        notes.append("dropped unverified " + ", ".join(dict.fromkeys(dropped)))
    if words > cfg["max_word_target"] + 150:
        notes.append(f"long issue ({words} words)")
    summary = {
        "status": "made", "no": n, "url": url, "title": f"1 A.M. Paper No. {n} is ready",
        "message": f'{stories[0]["headline"]}\n{stories[1]["headline"]}'
                   + (f"\nNote: {'; '.join(notes)}." if notes else ""),
        "requests": llm.requests,
    }
    log(f"\nDone: docs/issues/{issue_file.name} · {words} words · {llm.requests} model requests")
    for k in notes:
        log(f"  note: {k}")
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["full", "check"], default=os.environ.get("MODE") or "full")
    ap.add_argument("--force", action="store_true", help="make an issue even if today's exists")
    args = ap.parse_args(argv)
    try:  # Windows consoles: never crash on a character like "·"
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    deps ={"get_json": util.get_json, "get_text": util.get_text}
    if args.mode == "full":
        key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not key:
            log("OPENROUTER_API_KEY is not set. Add it as a repository secret (see README).")
            return 2
        cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        deps["llm"] = llm_mod.OpenRouter(
            key, os.environ.get("MODEL") or cfg["model"], cfg.get("fallback_models"),
            max_requests=cfg["max_requests_per_run"], timeout=cfg["request_timeout_s"],
            max_tokens=cfg["max_output_tokens"], temperature=cfg["temperature"], log=log)
    force = args.force or os.environ.get("FORCE", "").lower() == "true" \
        or os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    summary = run(args.mode, deps, force=force)
    (ROOT / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
