Pick tonight's two papers for issue No. {{N}} ({{DATE}}).

RULES
- Lead story: {{LEAD_RULE}}
- Second story: {{SECOND_RULE}} Its category must differ from the lead's category.
- Choose for the creativity and transferability of the core idea first, importance second. A clever mechanism, an elegant experimental design, or a surprising way of using physics or chemistry beats an incremental improvement.
- Prefer strong journals and labs. Avoid papers that are mostly surveys, clinical outcome statistics, or bioinformatics resources.
- Avoid repeating the topic of these recent stories: {{RECENT}}

CANDIDATES (all have open-access full text; abstracts are trimmed)
{{CANDIDATES}}

Reply with this JSON object only:
{
  "lead": ["<id of your first choice>", "<backup>", "<second backup>"],
  "second": ["<id of your first choice>", "<backup>", "<second backup>"],
  "why": "<one sentence: the clever idea in your lead pick>"
}
Use ids exactly as written (like "c7"). List up to 3 ids per slot, best first. No id may appear in both lists.
