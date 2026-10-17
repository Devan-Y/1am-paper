"""Find recent open-access papers and pull their full text from Europe PMC.

Europe PMC indexes PubMed, PubMed Central (PMC) and preprint servers (bioRxiv, medRxiv,
ChemRxiv ...). Its free REST API returns metadata plus the full text (as JATS XML) for
open-access articles, so every story is written from the whole paper, never an abstract.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import html.entities as html_entities
import re
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as xml_escape
from typing import Callable

from . import util

BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"


@dataclasses.dataclass
class Paper:
    id: str
    source: str
    category: str
    title: str
    abstract: str
    journal: str
    is_preprint: bool
    pub_date: str
    doi: str | None = None
    pmcid: str | None = None
    authors: list = dataclasses.field(default_factory=list)   # last names, in order
    last_author_affiliation: str = ""
    volume: str = ""
    pages: str = ""
    tier: float = 1.0
    score: float = 0.0
    classic: bool = False
    cited_by: int = 0

    @property
    def key(self) -> str:
        return (self.doi or self.id).lower()

    @property
    def link(self) -> str:
        if self.doi:
            return f"https://doi.org/{self.doi}"
        if self.pmcid:
            return f"https://europepmc.org/article/PMC/{self.pmcid}"
        return f"https://europepmc.org/article/{self.source}/{self.id}"


# ------------------------------------------------------------------ search

def _quote(p: str) -> str:
    return '"' + p.replace('"', "") + '"'


def build_query(cat: dict, start: dt.date | None, end: dt.date | None, preprints: bool) -> str:
    any_clause = " OR ".join(f"TITLE:{_quote(p)} OR ABSTRACT:{_quote(p)}" for p in cat["any"])
    q = f"({any_clause})"
    if cat.get("and_any"):
        and_clause = " OR ".join(f"TITLE:{_quote(p)} OR ABSTRACT:{_quote(p)}" for p in cat["and_any"])
        q += f" AND ({and_clause})"
    if start and end:
        q += f" AND FIRST_PDATE:[{start.isoformat()} TO {end.isoformat()}]"
    q += " AND SRC:PPR" if preprints else " AND OPEN_ACCESS:y AND IN_EPMC:y"
    return q


def _strip_tags(s: str | None) -> str:
    return util.squash(re.sub(r"<[^>]+>", " ", s or ""))


def _journal_tier(name: str, tiers: dict) -> float:
    n = name.lower().strip().rstrip(".")
    for tier, names in tiers.items():
        if n in names:
            return float(tier)
    return 1.0


def _is_excluded(rec: dict, cfg: dict) -> bool:
    types = [t.lower() for t in (rec.get("pubTypeList") or {}).get("pubType", []) or []]
    bad = set(cfg["exclude_pub_types"])
    if any(t in bad for t in types):
        return True
    title = _strip_tags(rec.get("title")).lower()
    return any(re.search(rf"\b{w}\b", title) for w in cfg["exclude_title_words"])


def to_paper(rec: dict, category: str, cfg: dict) -> Paper | None:
    source = rec.get("source", "")
    is_preprint = source == "PPR"
    title = _strip_tags(rec.get("title"))
    abstract = _strip_tags(rec.get("abstractText"))
    if not title or not abstract:
        return None
    if is_preprint:
        journal = ((rec.get("bookOrReportDetails") or {}).get("publisher") or "Preprint").strip()
    else:
        journal = (((rec.get("journalInfo") or {}).get("journal") or {}).get("title") or "").strip()
    authors_raw = ((rec.get("authorList") or {}).get("author")) or []
    authors = [a.get("lastName") or a.get("fullName") or a.get("collectiveName") or "" for a in authors_raw]
    authors = [a for a in authors if a]
    last_aff = ""
    if authors_raw:
        affs = ((authors_raw[-1].get("authorAffiliationDetailsList") or {}).get("authorAffiliation")) or []
        if affs:
            last_aff = affs[0].get("affiliation", "")
    ji = rec.get("journalInfo") or {}
    paper = Paper(
        id=rec.get("pmcid") or rec.get("id", ""),
        source=source,
        category=category,
        title=title,
        abstract=abstract,
        journal=journal,
        is_preprint=is_preprint,
        pub_date=rec.get("firstPublicationDate") or rec.get("firstIndexDate") or "",
        doi=(rec.get("doi") or "").lower() or None,
        pmcid=rec.get("pmcid"),
        authors=authors,
        last_author_affiliation=last_aff,
        volume=str(ji.get("volume") or ""),
        pages=str(rec.get("pageInfo") or ""),
        cited_by=int(rec.get("citedByCount") or 0),
    )
    if is_preprint:
        paper.id = rec.get("id", paper.id)
        paper.tier = 1.5
    else:
        paper.tier = _journal_tier(journal, cfg["journal_tiers"])
    return paper


def search(query: str, page_size: int = 50, sort: str | None = None,
           get_json: Callable = util.get_json) -> list[dict]:
    params = {"query": query, "resultType": "core", "format": "json", "pageSize": page_size}
    if sort:
        params["sort"] = sort
    data = get_json(f"{BASE}/search", params, timeout=60)
    return ((data.get("resultList") or {}).get("result")) or []


def find_candidates(cfg: dict, category: str, start: dt.date, end: dt.date,
                    seen_keys: set, get_json: Callable = util.get_json,
                    log: Callable = print) -> list[Paper]:
    cat = cfg["categories"][category]
    out: dict[str, Paper] = {}
    for preprints in (False, True):
        q = build_query(cat, start, end, preprints)
        try:
            recs = search(q, get_json=get_json)
        except Exception as e:  # one failed query should not sink the night
            log(f"  ! search failed ({category}, {'preprints' if preprints else 'journals'}): {e}")
            continue
        for rec in recs:
            if _is_excluded(rec, cfg):
                continue
            p = to_paper(rec, category, cfg)
            if not p or p.key in seen_keys or p.key in out:
                continue
            if p.tier < cat.get("min_journal_tier", 0):
                continue
            out[p.key] = p
    papers = list(out.values())
    for p in papers:
        d = util.parse_date(p.pub_date) or start
        recency = max(0.0, 1.0 - (end - d).days / max(1, (end - start).days))
        p.score = p.tier + 0.6 * recency
    papers.sort(key=lambda p: p.score, reverse=True)
    return papers


def find_classics(cfg: dict, category: str, before: dt.date, seen_keys: set,
                  get_json: Callable = util.get_json, log: Callable = print) -> list[Paper]:
    """Older, highly cited open-access papers for Sunday's 'Classic' slot."""
    cat = cfg["categories"][category]
    q = build_query(cat, dt.date(1990, 1, 1), before, preprints=False)
    try:
        recs = search(q, page_size=40, sort="CITED desc", get_json=get_json)
    except Exception as e:
        log(f"  ! classic search failed ({category}): {e}")
        return []
    papers = []
    for rec in recs:
        if _is_excluded(rec, cfg):
            continue
        p = to_paper(rec, category, cfg)
        if p and p.key not in seen_keys:
            p.classic = True
            p.score = p.tier + min(p.cited_by, 3000) / 1000
            papers.append(p)
    papers.sort(key=lambda p: p.score, reverse=True)
    return papers


# ------------------------------------------------------------------ full text

def fetch_fulltext_xml(paper: Paper, get_text: Callable = util.get_text,
                       get_json: Callable = util.get_json) -> str | None:
    ids = []
    if paper.pmcid:
        ids.append(paper.pmcid)
    if paper.is_preprint and paper.id and paper.id not in ids:
        ids.append(paper.id)
    for ident in ids:
        try:
            xml = get_text(f"{BASE}/{ident}/fullTextXML", timeout=90, retries=2)
            if "<body" in xml:
                return xml
        except Exception:
            pass
    # Preprint fallback: bioRxiv / medRxiv publish JATS XML for every posted preprint.
    if paper.is_preprint and paper.doi and paper.doi.startswith("10.1101/"):
        for server in ("biorxiv", "medrxiv"):
            try:
                data = get_json(f"https://api.biorxiv.org/details/{server}/{paper.doi}/na/json",
                                timeout=60, retries=1)
                coll = data.get("collection") or []
                if coll and coll[-1].get("jatsxml"):
                    xml = get_text(coll[-1]["jatsxml"], timeout=90, retries=1)
                    if "<body" in xml:
                        return xml
            except Exception:
                continue
    return None


_SKIP = {"ref-list", "fn-group", "ack", "glossary", "app-group", "back"}


def _local(tag) -> str:
    return tag.split("}", 1)[-1] if isinstance(tag, str) else ""


def _text(el, keep_figs: bool = False) -> str:
    """Flatten an element's text. Drops citation markers; writes superscripts as ^x so
    10<sup>4</sup> stays '10^4' instead of '104'."""
    parts: list[str] = []

    def walk(e):
        tag = _local(e.tag)
        if tag in _SKIP or (not keep_figs and tag in {"fig", "table-wrap"}):
            if e.tail:
                parts.append(e.tail)
            return
        if tag == "xref" and e.get("ref-type") == "bibr":
            if e.tail:
                parts.append(e.tail)
            return
        if tag == "sup":
            inner = "".join(e.itertext()).strip()
            has_cite = any(_local(c.tag) == "xref" and c.get("ref-type") == "bibr" for c in e.iter())
            if inner and not has_cite:
                numeric_list = re.fullmatch(r"[\d,–\-\s]+", inner)
                # A bare number list after a word or period is usually an unlinked citation.
                if not numeric_list or _is_exponent_context(parts):
                    parts.append("^" + inner)
            if e.tail:
                parts.append(e.tail)
            return
        if tag == "math":  # MathML: keep its plain text
            parts.append(" " + "".join(e.itertext()) + " ")
            if e.tail:
                parts.append(e.tail)
            return
        if e.text:
            parts.append(e.text)
        for c in e:
            walk(c)
        if tag in {"p", "title", "td", "th", "tr", "caption", "label"}:
            parts.append(" ")
        if tag == "td" or tag == "th":
            parts.append("| ")
        if e.tail:
            parts.append(e.tail)

    walk(el)
    return util.squash("".join(parts))


def _is_exponent_context(parts: list[str]) -> bool:
    """True when the text right before a numeric superscript ends in a number or unit,
    e.g. '10' in 10^4 or 'cm' in cm^2 (so it is an exponent, not a citation)."""
    tail = "".join(parts[-3:]).rstrip()
    return bool(re.search(r"(\d|[a-zA-Zµ])$", tail)) and not tail.endswith((".", ","))


def _classify(heading: str) -> str:
    h = heading.lower()
    if "result" in h:
        return "results"
    if any(k in h for k in ("method", "materials", "experimental", "procedure")):
        return "methods"
    if any(k in h for k in ("discussion", "conclusion", "outlook")):
        return "discussion"
    if any(k in h for k in ("introduction", "background")):
        return "intro"
    if any(k in h for k in ("data availability", "code availability", "author contribution",
                            "competing", "funding", "acknowledg", "supplementary", "declaration",
                            "ethics", "conflict")):
        return "admin"
    return "results"  # Science/Nature-style descriptive headings are usually results


def parse_jats(xml: str) -> dict:
    """Return {'sections': [(heading, kind, text)], 'captions': [...], 'tables': [...], 'all_text': str}."""
    xml = re.sub(r'<!DOCTYPE[^>]*>', "", xml, count=1)
    # XML parsers only know 5 named entities; turn HTML ones (&nbsp; &micro; ...) into characters.
    xml = re.sub(r"&(?!(?:lt|gt|amp|quot|apos);|#)(\w+);",
                 lambda m: xml_escape(html_entities.html5.get(m.group(1) + ";", " ")), xml)
    root = ET.fromstring(xml)
    body = next((e for e in root.iter() if _local(e.tag) == "body"), None)
    abstract = next((e for e in root.iter() if _local(e.tag) == "abstract"), None)
    sections: list[tuple[str, str, str]] = []
    if abstract is not None:
        sections.append(("Abstract", "abstract", _text(abstract)))
    if body is not None:
        top_secs = [c for c in body if _local(c.tag) == "sec"]
        loose = [c for c in body if _local(c.tag) not in {"sec", "fig", "table-wrap"}]
        if loose:
            txt = util.squash(" ".join(_text(c) for c in loose))
            if txt:
                sections.append(("Main text", "results", txt))
        for sec in top_secs:
            title_el = next((c for c in sec if _local(c.tag) == "title"), None)
            heading = util.squash("".join(title_el.itertext())) if title_el is not None else "Section"
            kind = _classify(heading)
            if kind == "admin":
                continue
            content = []
            for c in sec:
                if c is title_el:
                    continue
                if _local(c.tag) == "sec":
                    sub_t = next((x for x in c if _local(x.tag) == "title"), None)
                    if sub_t is not None:
                        content.append("§ " + util.squash("".join(sub_t.itertext())) + ".")
                    content.append(_text(c))
                else:
                    content.append(_text(c))
            sections.append((heading, kind, util.squash(" ".join(content))))
    captions, tables = [], []
    for e in root.iter():
        tag = _local(e.tag)
        if tag == "fig":
            label = next((c for c in e if _local(c.tag) == "label"), None)
            cap = next((c for c in e if _local(c.tag) == "caption"), None)
            if cap is not None:
                lab = util.squash("".join(label.itertext())) if label is not None else "Figure"
                captions.append(f"{lab}: {_text(cap)}")
        elif tag == "table-wrap":
            tables.append(_text(e, keep_figs=True))
    all_text = " ".join(s[2] for s in sections) + " " + " ".join(captions) + " " + " ".join(tables)
    return {"sections": sections, "captions": captions, "tables": tables, "all_text": all_text}


def body_words(parsed: dict) -> int:
    return sum(util.word_count(t) for h, k, t in parsed["sections"] if k != "abstract")


def paper_text_for_model(parsed: dict, max_words: int) -> str:
    """Paper text in reading order, trimmed to fit: results, captions and methods are kept
    first; introduction, discussion and tables are trimmed first."""
    priority = {"abstract": 0, "results": 1, "methods": 2, "discussion": 3, "intro": 4}
    secs = parsed["sections"]
    cap_text = "\n".join(parsed["captions"])
    budget = max_words - util.word_count(cap_text)
    allowed = {}
    for i in sorted(range(len(secs)), key=lambda i: priority.get(secs[i][1], 1)):
        n = util.word_count(secs[i][2])
        take = max(0, min(n, budget))
        allowed[i] = take
        budget -= take
    out = []
    for i, (h, kind, t) in enumerate(secs):
        if allowed.get(i, 0) == 0:
            out.append(f"## {h}\n[section omitted for length]")
            continue
        words = t.split()
        if allowed[i] < len(words):
            t = " ".join(words[: allowed[i]]) + " [… rest of section trimmed]"
        out.append(f"## {h}\n{t}")
    out.append("## Figure captions\n" + cap_text)
    if budget > 200 and parsed["tables"]:
        tbl = " ".join(parsed["tables"])
        out.append("## Tables\n" + util.truncate_words(tbl, budget))
    return "\n\n".join(out)
