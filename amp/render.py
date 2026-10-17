"""Turn the written stories into the issue page and the archive page.

The page's <link>, <style> and <script> blocks are copied byte-for-byte from
template/issue-template.html, so every issue looks exactly like the earlier ones.
All model text is HTML-escaped; only **bold** is turned into markup.
"""
from __future__ import annotations

import datetime as dt
import html
import pathlib
import re

from . import util


class Template:
    def __init__(self, path: pathlib.Path):
        src = path.read_text(encoding="utf-8")
        self.links = "\n".join(re.findall(r"^<link [^>]*>$", src, re.M))
        # Anchor at line starts: the CSS comments mention "<style>" and "<script>" too.
        self.style = re.search(r"^<style>$.*?^</style>$", src, re.S | re.M).group(0)
        self.script = re.search(r"^<script>$.*?^</script>$", src, re.S | re.M).group(0)

    def page(self, title: str, main_html: str, with_script: bool = True) -> str:
        return (
            "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            "<meta name=\"color-scheme\" content=\"light dark\">\n"
            f"<title>{esc(title)}</title>\n{self.links}\n{self.style}\n</head>\n<body>\n"
            f"{main_html}\n" + (self.script + "\n" if with_script else "") + "</body>\n</html>\n"
        )


def esc(s) -> str:
    return html.escape(str(s or ""), quote=True)


def rich(s) -> str:
    """Escape text, then allow **bold** only."""
    out = esc(util.squash(str(s or "")))
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)


def authors_short(names: list[str]) -> str:
    if not names:
        return ""
    if len(names) <= 5:
        return ", ".join(names)
    return ", ".join(names[:4]) + " … " + names[-1]


def _figure(fig: dict, no: int) -> str:
    bars = fig["bars"]
    top = max(float(b["value"]) for b in bars)
    rows = []
    for b in bars:
        pct = 0 if top <= 0 else 100 * float(b["value"]) / top
        style = f"width:{pct:.1f}%" + (";background:var(--lamp)" if b.get("highlight") else "")
        rows.append(
            f'<div class="bar-row"><div class="bar-head"><span>{rich(b["label"])}</span>'
            f'<span class="v">{esc(b.get("value_text") or b["value"])}</span></div>'
            f'<div class="track"><div class="fill" style="{style}"></div></div></div>')
    caption = rich(fig.get("caption", ""))
    unit = esc(fig.get("unit", ""))
    return (
        f'<figure>\n<div class="fig-title"><span class="label">Fig {no}</span>{rich(fig["title"])}</div>\n'
        f'<div class="bars">\n' + "\n".join(rows) + "\n</div>\n"
        f"<figcaption>{caption} Bars drawn to scale ({unit}); values from the paper.</figcaption>\n</figure>")


def _envelope(env: dict) -> str:
    vars_html = "; ".join(f"<strong>{esc(v.get('symbol'))}</strong> = {rich(v.get('meaning'))}"
                          for v in env.get("variables") or [])
    worked = f" {rich(env.get('worked'))}" if env.get("worked") else ""
    return (
        '<div class="envelope">\n<div class="label">Back of the envelope</div>\n'
        f'<p class="eq">{esc(env.get("equation"))}</p>\n<p>{vars_html}.{worked}</p>\n</div>')


def story_html(s: dict, idx: int, fig_no: int) -> str:
    """s: story dict merged with metadata keys slot_label, kicker_meta, move_label, move_name."""
    sid = "lead" if idx == 1 else "second"
    parts = [
        f'<article class="story" id="{sid}">',
        f'  <div class="kicker"><span class="slot">{esc(s["slot_label"])}</span>'
        f'<span class="label">{esc(s["kicker_meta"])}</span></div>',
        f'  <h2>{rich(s["headline"])}</h2>',
        '  <div class="block">\n    <div class="label">The problem</div>\n'
        + "\n".join(f"    <p>{rich(p)}</p>" for p in s.get("problem") or []) + "\n  </div>",
        f'  <div class="predict" id="p{idx}">\n    <div class="label">Your turn · 10 seconds</div>\n'
        f'    <p>{rich(s["your_turn"])}</p>\n'
        f'    <button class="reveal" type="button" data-reveal="t{idx}" hidden>I\'ve guessed. Show the idea</button>\n  </div>',
        f'  <div class="trick" id="t{idx}" data-veil>',
        f'    <div class="block">\n      <div class="label">The idea · {esc(s["trick_name"])}</div>\n'
        f'      <p>{rich(s["trick"])}</p>\n    </div>',
    ]
    if s.get("envelope"):
        parts.append(_envelope(s["envelope"]))
    if s.get("figure"):
        parts.append(_figure(s["figure"], fig_no))
    steps = s.get("what_they_did") or []
    if steps:
        parts.append(
            '    <div class="block">\n      <div class="label">What they did</div>\n      <ol class="steps">\n'
            + "\n".join(f'        <li><div><span class="st">{rich(st.get("title"))}</span> {rich(st.get("text"))}</div></li>'
                        for st in steps)
            + "\n      </ol>\n    </div>")
    stats = s.get("stats") or []
    if stats:
        parts.append('    <div class="stats">\n' + "\n".join(
            f'      <div class="stat"><div class="n">{esc(x.get("value"))}</div><div class="t">{rich(x.get("text"))}</div></div>'
            for x in stats) + "\n    </div>")
    if s.get("surprise"):
        parts.append(f'    <div class="block"><p><strong>The surprise:</strong> {rich(s["surprise"])}</p></div>')
    parts.append(
        f'    <div class="move">\n      <div class="label">{esc(s["move_label"])}</div>\n'
        f'      <div class="mname">{esc(s["move_name"])}</div>\n      <p>{rich(s["move"].get("how"))}</p>\n    </div>')
    parts.append(
        '    <div class="aside">\n'
        f'      <div class="block"><div class="label">For your work</div><p>{rich(s.get("for_your_work"))}</p></div>\n'
        f'      <div class="block limits"><div class="label">Limits</div><p>{rich(s.get("limits"))}</p></div>\n'
        '    </div>')
    parts.append("  </div>\n</article>")
    return "\n".join(parts)


def source_html(p, access: str) -> str:
    year = (p.pub_date or "")[:4]
    vol = f" {esc(p.volume)}" if p.volume else ""
    pages = f", {esc(p.pages)}" if p.pages and p.volume else ""
    label = f"doi:{p.doi}" if p.doi else p.link
    return (f'<li>{esc(authors_short(p.authors))}. “{esc(p.title.rstrip("."))}.” <em>{esc(p.journal)}</em>'
            f'{vol}{pages} ({esc(year)}). <a href="{esc(p.link)}">{esc(label)}</a> ({esc(access)})</li>')


def issue_html(tpl: Template, *, n: int, date: dt.date, thread: dict, stories: list[dict],
               quiz: list[dict], sources: list[str], check_note: str, archive_href: str,
               model_note: str, minutes: int) -> str:
    q_html = []
    for i, q in enumerate(quiz, 1):
        frm = f'<div class="from">From No. {q["from"]:03d}</div>' if q.get("from") else ""
        q_html.append(
            f'  <details>\n    <summary><span class="q">Q{i}</span><span>{rich(q["q"])}{frm}'
            f'<span class="tap">Tap for answer</span></span></summary>\n'
            f'    <div class="ans">{rich(q["a"])}</div>\n  </details>')
    main = f"""<main class="wrap">

<header class="mast">
  <div class="mast-top">
    <div class="brand">The 1 A.M. Paper</div>
    <div class="issue-meta">No. {n:03d} · {esc(util.fmt_masthead(date))} · ~{minutes} min</div>
  </div>
  <div>
    <div class="label">Tonight's thread</div>
    <h1>{rich(thread["h1"])}</h1>
  </div>
  <p class="intro">{rich(thread["intro"])}</p>
</header>

{story_html(stories[0], 1, 1)}

<div class="divider"></div>

{story_html(stories[1], 2, 2 if stories[0].get("figure") else 1)}

<section class="takeaway">
  <div class="label">Tonight in one line</div>
  <p>{rich(thread["one_line"])}</p>
</section>

<section class="quiz">
  <h3>Quiz yourself</h3>
  <p class="note">Answer in your head first, then tap.</p>
{chr(10).join(q_html)}
</section>

<section class="sources">
  <div class="label">Sources</div>
  <ol>
    {chr(10).join("    " + s for s in sources).strip()}
  </ol>
  <p>{esc(check_note)}</p>
</section>

<footer class="foot">
  <span>The 1 A.M. Paper · No. {n:03d}</span>
  <a id="archive-link" href="{esc(archive_href)}">Archive &amp; move playbook →</a>
  <span>Figures are original diagrams, redrawn from reported numbers.</span>
  <span>{esc(model_note)}</span>
</footer>

</main>"""
    return tpl.page(f"1 A.M. Paper No. {n}", main)


def visible_words(page_html: str) -> int:
    body = re.search(r"<main.*?</main>", page_html, re.S)
    text = re.sub(r"<[^>]+>", " ", body.group(0) if body else page_html)
    return util.word_count(html.unescape(text))


# ------------------------------------------------------------------ archive

def archive_html(tpl: Template, log: dict, cats: dict) -> str:
    issues = sorted(log["issues"], key=lambda i: i["no"], reverse=True)
    rows = []
    for i in issues:
        d = util.parse_date(i.get("date"))
        when = util.fmt_masthead(d) if d else esc(i.get("date"))
        stories = "".join(
            f'<li><div><span class="st">{esc(s.get("slot", "").capitalize())}.</span> {esc(s.get("headline"))} '
            f'<span class="label">{esc(cats.get(s.get("category"), {}).get("kicker", s.get("category", "")))}</span></div></li>'
            for s in i.get("stories", []))
        rows.append(f"""<article class="story">
  <div class="kicker"><span class="slot">No. {i["no"]:03d}</span><span class="label">{esc(when)}</span></div>
  <h2><a href="{esc(i.get("url"))}" style="color:inherit;text-decoration:none">{esc(i.get("headline"))}</a></h2>
  <ol class="steps">{stories}</ol>
  <p class="label"><a href="{esc(i.get("url"))}">Read No. {i["no"]:03d} →</a></p>
</article>""")
    moves = "\n".join(
        f'''<div class="move">
  <div class="label">Invention move {m["no"]:02d} · from No. {int(m.get("issue", 0)):03d}</div>
  <div class="mname">{esc(m["name"])}</div>
  <p>{rich(m.get("gist"))}</p>
  <p style="opacity:.85"><strong>Example:</strong> {rich(m.get("example"))}</p>
</div>''' for m in sorted(log.get("moves", []), key=lambda m: m["no"]))
    main = f"""<main class="wrap">
<header class="mast">
  <div class="mast-top">
    <div class="brand">The 1 A.M. Paper</div>
    <div class="issue-meta">Archive · {len(issues)} issues · {len(log.get("moves", []))} moves</div>
  </div>
  <div>
    <div class="label">Every issue, newest first</div>
    <h1>Archive &amp; move playbook</h1>
  </div>
  <p class="intro">Each issue takes two recent papers apart: the problem, the trick, how they tested it, and the reusable invention move. The playbook below collects every move so far.</p>
</header>
{chr(10).join(rows)}
<div class="divider"></div>
<section class="quiz">
  <h3>Move playbook</h3>
  <p class="note">The thinking moves behind each issue's best idea.</p>
{moves}
</section>
<footer class="foot"><span>The 1 A.M. Paper · Archive</span><a href="log.json">Raw log (JSON) →</a></footer>
</main>"""
    return tpl.page("1 A.M. Paper Archive", main, with_script=False)
