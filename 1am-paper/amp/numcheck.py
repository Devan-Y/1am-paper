"""Check that every number the model wrote actually appears in the paper.

Small models sometimes invent or 'round' numbers. This compares each number in the
written story against every number found in the paper's full text (body, captions,
tables). Integers 0 to 10 are skipped because they appear in every paper anyway.
"""
from __future__ import annotations

import re

_NUM = re.compile(r"(?<![\w.^])[-−–]?\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\d])|(?<![\w.^])[-−–]?\d+(?:\.\d+)?")
_EXP = re.compile(r"(\d+(?:\.\d+)?)\s*[×x]\s*10\s*\^?\s*([−\-–]?\d+)")


def _canon(tok: str) -> str | None:
    t = tok.replace(",", "").lstrip("-−–")
    try:
        return "{:.10g}".format(float(t))
    except ValueError:
        return None


def numbers_in(text: str) -> set[str]:
    text = (text or "").replace(" ", " ").replace(" ", " ")
    out = set()
    for m in _NUM.finditer(text):
        c = _canon(m.group(0))
        if c is not None:
            out.add(c)
    # Scientific notation like 3 × 10^5 also counts as its expanded value.
    for m in _EXP.finditer(text):
        try:
            mant = float(m.group(1))
            exp = int(m.group(2).replace("−", "-").replace("–", "-"))
            out.add("{:.10g}".format(mant * 10 ** exp))
        except (ValueError, OverflowError):
            pass
    return out


def _trivial(c: str) -> bool:
    try:
        v = float(c)
    except ValueError:
        return True
    return v.is_integer() and 0 <= v <= 10


def story_strings(story: dict) -> list[tuple[str, str]]:
    """(field, text) pairs for every piece of the story that is shown to the reader."""
    out = []
    for k in ("headline", "your_turn", "trick", "surprise", "for_your_work", "limits"):
        v = story.get(k)
        if isinstance(v, str):
            out.append((k, v))
    for k in ("problem",):
        for i, p in enumerate(story.get(k) or []):
            out.append((f"{k}[{i}]", p))
    for i, s in enumerate(story.get("what_they_did") or []):
        out.append((f"what_they_did[{i}]", f"{s.get('title', '')} {s.get('text', '')}"))
    for i, s in enumerate(story.get("stats") or []):
        out.append((f"stats[{i}]", f"{s.get('value', '')} {s.get('text', '')}"))
    fig = story.get("figure") or {}
    for i, b in enumerate(fig.get("bars") or []):
        out.append((f"figure.bars[{i}]", f"{b.get('value', '')} {b.get('value_text', '')} {b.get('label', '')}"))
    if fig.get("caption"):
        out.append(("figure.caption", fig["caption"]))
    env = story.get("envelope") or {}
    if env.get("worked"):
        out.append(("envelope.worked", env["worked"]))
    q = story.get("quiz") or {}
    for k in ("q", "a"):
        if q.get(k):
            out.append((f"quiz.{k}", q[k]))
    return out


def unmatched(story: dict, source_numbers: set[str], extra_ok: set[str] = frozenset()) -> dict[str, list[str]]:
    """{field: [numbers not found in the paper]} for numbers that matter."""
    bad: dict[str, list[str]] = {}
    for field, text in story_strings(story):
        for c in sorted(numbers_in(text)):
            if _trivial(c) or c in source_numbers or c in extra_ok:
                continue
            bad.setdefault(field, []).append(c)
    return bad


def count_checked(story: dict) -> int:
    return sum(1 for _, t in story_strings(story) for c in numbers_in(t) if not _trivial(c))
