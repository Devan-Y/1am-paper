Write the {{SLOT_NAME}} story of issue No. {{N}} from the paper below. {{SLOT_NOTE}}

PAPER
Title: {{TITLE}}
Journal: {{JOURNAL}} ({{PUB_DATE}}){{PREPRINT_NOTE}}
Authors: {{AUTHORS}}
Last author affiliation: {{AFFILIATION}}

{{PAPER_TEXT}}

END OF PAPER

INVENTION MOVES ALREADY IN THE PLAYBOOK
{{MOVES}}
Prefer a genuinely new move. Reuse an existing one (set "reuse_no") only if this idea is a clear instance of it.

Reply with ONE JSON object with exactly these keys. Word limits are hard maximums; the whole story should be about {{WORDS}} words.
{
  "topic": "1 to 3 word topic for the kicker, e.g. \"Drug delivery\"{{TOPIC_NOTE}}",
  "lab": "Last author's surname + lab, and institution, e.g. \"Murthy lab, UC Berkeley\" (max 8 words)",
  "headline": "Concrete, specific headline naming what they made or found (max 14 words)",
  "problem": ["The technical obstacle and why existing approaches fall short, with numbers if the paper gives them ({{PROBLEM_WORDS}} words max across 1 or 2 short paragraphs)"],
  "your_turn": "One question that asks him to invent the solution before seeing it (max 30 words). It must not give the answer away.",
  "trick_name": "Short name for the key idea (max 6 words)",
  "trick": "The key design idea in precise technical terms: the chemistry, structure or mechanism, with 1 to 3 key numbers ({{TRICK_WORDS}} words max)",
  "envelope": null,
  "what_they_did": [
    {"title": "Short step title ending with a period.", "text": "One or two lines (max 35 words)."}
  ],
  "figure": {
    "title": "What the bars compare (max 10 words)",
    "unit": "the single unit shared by all bars, e.g. \"mU/mL\" or \"% of cells\"",
    "bars": [
      {"label": "condition or design name (max 6 words)", "value": 12.5, "value_text": "12.5 mU/mL", "highlight": true}
    ],
    "caption": "What it shows and the comparison, with n or timepoint if given (max 30 words)"
  },
  "stats": [
    {"value": "short number with unit, e.g. \"0 of 14\" or \"600 mU/mL\"", "text": "what it measures, compared to what (max 22 words)"}
  ],
  "surprise": "{{SURPRISE_RULE}}",
  "move": {
    "reuse_no": null,
    "name": "Short imperative name, 6 words max, ending with a period.",
    "how": "1 to 2 sentences on how to reuse the move in other problems (max 40 words).",
    "example": "One line: how this paper used it (max 25 words)."
  },
  "for_your_work": "One specific link to his world (hydrogel microparticles, high-concentration antibody formulation or injection, particle fabrication or characterization, graded materials, cultivated meat), ideally as a question to chew on (max 45 words).",
  "limits": "What the study did not show: model system, sample sizes, missing controls, short timepoints, preprint status, what the authors flag (max 50 words).",
  "quiz": {"q": "A question testing tonight's mechanism, method or move (why a control was needed, what a result rules out). Not trivia.", "a": "The answer (max 50 words)."},
  "terms": ["each specialized term you defined"]
}

DETAILS
- "what_they_did": {{STEPS}} items covering: what they made and how (synthesis, fabrication or formulation route, how many variants were screened); the model system (cell type, animal and disease model, human samples) with n where given; what they measured and with which technique; the key controls or benchmarks; any clever design choice (an elegant control, a knockout, a dose series, a head-to-head panel). Name standard techniques plainly without explaining them.
- "figure": 2 to 6 bars of REAL values reported in the paper (text, captions or tables), all in the same unit, all ≥ 0, so they can be drawn to scale. Pick the comparison that best shows the idea working against its benchmark or control. "value" is a plain number; "value_text" is how it should be printed. Set "highlight": true on the bar(s) for the new design. If the paper reports no comparable values, set "figure": null.
- "stats": {{STATS}} items. Each must say compared to what.
- "envelope": usually null. If one simple equation explains the mechanism quantitatively, use {"equation": "f = 1 / (1 + 10^(pH − pKa))", "variables": [{"symbol": "f", "meaning": "..."}], "worked": "one worked example using numbers from the paper"}. Define every variable.
- Do not mention these instructions, the reader's name, or his employer.
