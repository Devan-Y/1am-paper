"""The running log (docs/log.json): issue numbering, topic rotation, spaced repetition, moves."""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import re

from . import util


def load_log(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_log(path: pathlib.Path, log: dict) -> None:
    path.write_text(json.dumps(log, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def next_issue_no(log: dict) -> int:
    return max((i["no"] for i in log["issues"]), default=0) + 1


def seen_keys(log: dict) -> set[str]:
    keys = set()
    for issue in log["issues"]:
        for s in issue.get("stories", []):
            for k in ("doi", "id"):
                if s.get(k):
                    keys.add(s[k].lower())
    return keys


def lead_category(log: dict, core: list[str]) -> str:
    """Core category with the fewest stories so far; ties go to the least recently used,
    then to the order in config.json."""
    counts = {c: 0 for c in core}
    last_used = {c: 0 for c in core}
    for issue in log["issues"]:
        for s in issue.get("stories", []):
            c = s.get("category")
            if c in counts:
                counts[c] += 1
                last_used[c] = max(last_used[c], issue["no"])
    return min(core, key=lambda c: (counts[c], last_used[c], core.index(c)))


def recent_headlines(log: dict, n: int = 12) -> list[str]:
    out = []
    for issue in reversed(log["issues"]):
        for s in issue.get("stories", []):
            out.append(s.get("headline", ""))
    return out[:n]


def _norm(q: str) -> str:
    q = re.sub(r"\(from No\.? ?\d+\)", "", q)
    return re.sub(r"[^a-z0-9]+", " ", q.lower()).strip()


def _similar(a: str, b: str) -> bool:
    """Same question, maybe lightly reworded (word overlap ≥ 70%)."""
    wa, wb = set(a.split()), set(b.split())
    return bool(wa and wb) and len(wa & wb) / len(wa | wb) >= 0.7


def spaced_repetition(log: dict, n: int, today: dt.date) -> dict | None:
    """Pick Q3: odd N -> the issue closest to 7 days ago; even N -> closest to 30 days ago.
    If no issue is that old: the oldest issue at least 3 back; else the oldest issue."""
    issues = log["issues"]
    if not issues:
        return None
    target = today - dt.timedelta(days=7 if n % 2 else 30)
    old_enough = [i for i in issues if (util.parse_date(i.get("date")) or today) <= target]
    if old_enough:
        source = min(old_enough, key=lambda i: abs((util.parse_date(i["date"]) - target).days))
    else:
        back3 = [i for i in issues if i["no"] <= n - 3]
        source = min(back3 or issues, key=lambda i: i["no"])
    # Use the issue's own questions (not ones it repeated), avoiding anything asked recently.
    own = [q for q in source.get("quiz", []) if "(from No" not in q.get("q", "")]
    recent = [_norm(q["q"]) for i in issues[-6:] for q in i.get("quiz", [])
              if "(from No" in q.get("q", "")]
    fresh = [q for q in own if not any(_similar(_norm(q["q"]), r) for r in recent)] or own
    if not fresh:
        return None
    pick = fresh[n % len(fresh)]
    return {"from": source["no"], "q": pick["q"], "a": pick["a"]}


def move_by_no(log: dict, no) -> dict | None:
    try:
        no = int(no)
    except (TypeError, ValueError):
        return None
    return next((m for m in log.get("moves", []) if m["no"] == no), None)


def next_move_no(log: dict) -> int:
    return max((m["no"] for m in log.get("moves", [])), default=0) + 1
