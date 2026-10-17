"""Offline end-to-end test: fake Europe PMC + fake model, real everything else.

    python tests/run_offline.py

Builds an issue from a FICTIONAL test paper into tests/out/ (the real docs/ folder
is not touched) and checks the number-check, repair, move numbering and quiz logic.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import run as run_mod  # noqa: E402
from amp import llm as llm_mod, numcheck  # noqa: E402

OUT = ROOT / "tests" / "out"

# ------------------------------------------------------------ fake Europe PMC

def record(i, cat, title, journal, date, preprint=False):
    return {
        "id": f"PPR{9000 + i}" if preprint else f"{40000000 + i}",
        "source": "PPR" if preprint else "MED",
        "pmcid": None if preprint else f"PMC99{i:05d}",
        "doi": f"10.9999/test.{cat}.{i}",
        "title": title,
        "abstractText": f"<h4>Abstract</h4>FICTIONAL TEST RECORD for {cat}. " + "We built and tested a thing. " * 30,
        "journalInfo": {"journal": {"title": journal}, "volume": "21"},
        "bookOrReportDetails": {"publisher": "bioRxiv"} if preprint else None,
        "pageInfo": "100-110",
        "firstPublicationDate": date,
        "pubTypeList": {"pubType": ["preprint"] if preprint else ["research-article", "Journal Article"]},
        "authorList": {"author": [
            {"lastName": "Alpha"}, {"lastName": "Beta"}, {"lastName": "Gamma"}, {"lastName": "Delta"},
            {"lastName": "Epsilon"}, {"lastName": "Zeta", "authorAffiliationDetailsList": {
                "authorAffiliation": [{"affiliation": "Dept. of Bioengineering, Test University, Boston, USA"}]}}]},
        "citedByCount": 10,
    }


CATS = {
    "microparticles-drug-delivery": "hydrogel microparticles",
    "antibody-delivery": "high-concentration antibody",
    "biomaterials-tissue": "tissue engineering",
    "cellular-agriculture": "cultivated meat",
    "graded-materials": "functionally graded",
}
SEARCH_LOG = []


def fake_get_json(url, params=None, **kw):
    if "api.biorxiv.org" in url:
        return {"collection": []}
    q = params["query"]
    SEARCH_LOG.append(q)
    for i, (cat, phrase) in enumerate(CATS.items()):
        if f'"{phrase}"' in q:
            pre = "SRC:PPR" in q
            recs = [record(i * 10 + j + (5 if pre else 0), cat,
                           f"Test paper {j} on {phrase}" + (" (preprint)" if pre else ""),
                           ["Nature Communications", "Science Advances", "Biomaterials"][j],
                           "2026-10-0" + str(5 + j), preprint=pre) for j in range(3)]
            recs.append(dict(record(i * 10 + 9, cat, "A review of everything", "Biomaterials", "2026-10-06"),
                             pubTypeList={"pubType": ["review-article"]}))
            return {"hitCount": len(recs), "resultList": {"result": recs}}
    return {"hitCount": 0, "resultList": {"result": []}}


def jats(title):
    filler = ("The particles were washed three times in PBS and stored at 4 °C until use. "
              "All measurements were made in triplicate on independent batches. ") * 60
    return f"""<?xml version="1.0"?>
<!DOCTYPE article PUBLIC "-//NLM//DTD JATS" "x.dtd">
<article xmlns:xlink="http://www.w3.org/1999/xlink"><front><article-meta>
<title-group><article-title>{title}</article-title></title-group>
<abstract><p>FICTIONAL TEST PAPER. Charge-switching microgels raised retention to 87% versus 41% for controls.</p></abstract>
</article-meta></front>
<body>
<sec><title>Introduction</title><p>Injectable depots release 35% of cargo in the first 24 h<xref ref-type="bibr" rid="b1">12</xref>. Prior microgels reached 150 mg/mL.</p></sec>
<sec><title>Results</title>
<sec><title>Design</title><p>We screened 48 formulations at 10<sup>4</sup> particles per µL. Particle diameter was 112 ± 9 µm (n = 200).
Viscosity at 1,000 s<sup>−1</sup> was 18.5 mPa·s versus 62.3 mPa·s for the 200 mg/mL solution.</p></sec>
<sec><title>In vivo</title><p>In rats (n = 6 per group), retention at day 7 was 87% for switching microgels, 41% for static microgels and 12% for free antibody.</p>
<fig id="f1"><label>Figure 1</label><caption><p>Retention at day 7: 87%, 41% and 12%. Injection force 9.8 N versus 31.4 N.</p></caption></fig>
<table-wrap><label>Table 1</label><caption><p>Formulations</p></caption><table><tr><td>F12</td><td>2.5 wt%</td><td>pKa 5.6</td></tr></table></table-wrap>
</sec></sec>
<sec><title>Discussion</title><p>The switch point near pH 5.6 matters. {filler}</p></sec>
<sec><title>Methods</title><p>Microgels were made by droplet microfluidics at 0.5 mL/h. {filler}</p></sec>
<sec><title>Data availability</title><p>Data on request.</p></sec>
</body><back><ref-list><ref id="b1">Old paper 1999, 1234-1240.</ref></ref-list></back></article>"""


def fake_get_text(url, **kw):
    if "fullTextXML" in url:
        if "PPR" in url:
            raise RuntimeError("404")  # preprints have no full text in this test
        return jats("Fictional test paper")
    raise RuntimeError("unexpected URL " + url)


# ------------------------------------------------------------ fake model

def story_json(slot, fake_number):
    s = {
        "topic": "Drug delivery",
        "lab": "Zeta lab, Test University",
        "headline": f"Fictional {slot}: microgels that flip charge to stay put",
        "problem": ["Depots release 35% of cargo in the first 24 h, and prior microgels topped out at 150 mg/mL."],
        "your_turn": "How could a particle stay mobile in the syringe but stick once injected?",
        "trick_name": "Charge switch at pH 5.6",
        "trick": "A **pKa-tuned amine** (an amine whose protonation flips near pH 5.6) makes the microgel surface switch charge after injection.",
        "envelope": None,
        "what_they_did": [
            {"title": "Built a library.", "text": "Screened 48 formulations by droplet microfluidics at 0.5 mL/h."},
            {"title": "Sized them.", "text": "Diameter 112 ± 9 µm, n = 200 particles."},
            {"title": "Measured flow.", "text": "Viscosity at 1,000 s⁻¹ against a 200 mg/mL antibody solution."},
            {"title": "Tested in rats.", "text": "Retention at day 7, n = 6 per group, against static microgels and free antibody."},
        ],
        "figure": {"title": "Antibody left at the injection site, day 7", "unit": "% retained",
                   "bars": [{"label": "Switching microgels", "value": 87, "value_text": "87%", "highlight": True},
                            {"label": "Static microgels", "value": 41, "value_text": "41%"},
                            {"label": "Free antibody", "value": 12, "value_text": "12%"}],
                   "caption": "Rats, n = 6 per group."},
        "stats": [{"value": "18.5 mPa·s", "text": "viscosity at 1,000 s⁻¹, versus 62.3 mPa·s for the 200 mg/mL solution"},
                  {"value": "9.8 N", "text": "injection force, versus 31.4 N"},
                  {"value": fake_number, "text": "an invented number that the checker must catch"}],
        "surprise": "",
        "move": {"reuse_no": 2 if slot == "second" else None, "name": "Switch after the needle.",
                 "how": "Let the body's conditions trigger the property you only need after delivery.",
                 "example": "Charge flips at pH 5.6 after injection."},
        "for_your_work": "Could a ~100 µm particle carry a surface that switches after injection to cut injection force?",
        "limits": "Rats, n = 6 per group; 7 days only; no human tissue.",
        "quiz": {"q": f"Why did the {slot} team compare against static microgels?", "a": "To show the switch, not the particle, drove retention: 87% versus 41%."},
        "terms": ["pKa-tuned amine"],
    }
    return s


class FakeOpenRouter(llm_mod.OpenRouter):
    def __init__(self):
        super().__init__("test-key", "nvidia/nemotron-3-super-120b-a12b:free", max_requests=30, log=print)
        self.calls = []

    def _call(self, messages, max_tokens):
        self.requests += 1
        self.models_used.add(self.model)
        last = messages[-1]["content"]
        self.calls.append(last[:60])
        if last.startswith("Pick tonight's two papers"):
            # deliberately sloppy: chatter + fenced JSON
            return 'Sure.\n```json\n{"lead": ["c1", "c2"], "second": ["c13"], "why": "test"}\n```'
        if "An automatic check could not find" in last:
            slot = "lead" if "LEAD" in messages[1]["content"][:60] else "second"
            fixed = story_json(slot, "87%")
            return json.dumps(fixed)
        if last.startswith("Write the LEAD"):
            return json.dumps(story_json("lead", "37%")) + "\nHope this helps!"
        if last.startswith("Write the SECOND"):
            return json.dumps(story_json("second", "2.4-fold"))
        if "has two stories" in last:
            return '{"h1": "Switch after the needle", "intro": "Both fictional stories switch a property after delivery.", "one_line": "Let the destination flip the switch.", "takeaway": "Trigger the property where it is needed.",}'
        raise AssertionError("unexpected prompt: " + last[:80])


# ------------------------------------------------------------ run

def main():
    # unit checks on the number parser
    assert numcheck.numbers_in("10^4 cells, 1,200 rpm, pH 4.2–5.8") >= {"10", "1200", "4.2", "5.8"}
    assert "100000" in numcheck.numbers_in("3 × 10^5? no: 1 × 10^5 cells")
    assert "22" in numcheck.numbers_in("IL-22") and "293" not in numcheck.numbers_in("HEK293")

    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "issues").mkdir(parents=True)
    shutil.copy(ROOT / "docs" / "log.json", OUT / "log.json")
    run_mod.DOCS = OUT

    fake = FakeOpenRouter()
    deps = {"get_json": fake_get_json, "get_text": fake_get_text, "llm": fake,
            "now": dt.datetime(2026, 10, 16, 0, 52)}
    summary = run_mod.run("full", deps)
    print(json.dumps(summary, indent=2))

    log = json.loads((OUT / "log.json").read_text(encoding="utf-8"))
    issue = log["issues"][-1]
    assert issue["no"] == 3, issue["no"]
    cats = [s["category"] for s in issue["stories"]]
    assert cats[0] == "antibody-delivery", cats          # rotation: fewest stories so far
    assert cats[0] != cats[1]
    assert issue["stories"][1]["move"] == 2              # reused move keeps its number
    assert [m["no"] for m in log["moves"]][-1] == 5      # one new move appended
    assert "(from No. 1)" in issue["quiz"][2]["q"]       # spaced repetition from No. 1
    assert "pH __" not in issue["quiz"][2]["q"]           # not the question No. 2 already repeated
    assert all("review" not in q.lower() for q in [s["headline"] for s in issue["stories"]])
    page = (OUT / "issues" / "issue-003.html").read_text(encoding="utf-8")
    assert "37%" not in page                             # invented number removed by repair
    assert "2.4" not in page                             # invented number removed by repair
    assert "Invention move 02 · again" in page and "Invention move 05" in page
    assert "<script>" in page and "data-veil" in page
    tpl = (ROOT / "template" / "issue-template.html").read_text(encoding="utf-8")
    style = tpl[tpl.index("\n<style>") + 1:tpl.index("\n</style>") + 9]
    assert style in page, "style block must be byte-for-byte"
    print("Model calls:", fake.calls)
    print("\nAll offline checks passed. Open tests/out/issues/issue-003.html to look at it.")


if __name__ == "__main__":
    main()
