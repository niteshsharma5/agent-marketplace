# Hybrid procedure (emit-context → reason → compose)

This is the agent-facing runbook for the middle step of the audit: how you turn
the shared evidence pack into judgment findings. The scripts already did the
mechanical work; you add the calls that need reading and reasoning.

## The loop

1. **Emit signals + context (scripts, once).**
   `python3 skills/website-ai-audit/scripts/audit.py <URL> --out ./out --emit-context`
   (`--no-render` if no browser). Writes:
   - `out/signals.json` — deterministic findings (the mechanical floor).
   - `out/context.json` — the per-page evidence pack you reason over.
   - `out/scope.json` — pages sampled, render availability, robots found, errors.

2. **Reason over `context.json` (agent).** Read the pack. For each judgment-heavy
   check, walk the matching sub-skill checklist and decide whether a finding is
   warranted:
   - Answer-readiness of facts → `skills/fact-extractability/references/answer-readiness-reasoning.md`
   - Entity ambiguity / attribution → `skills/entity-trust/references/entity-ambiguity-reasoning.md`
   - Engagement leaks → `skills/onsite-engagement/references/engagement-judgment-reasoning.md`
   Write every finding you conclude to `out/agent_findings.json`.

3. **Compose (scripts).**
   `python3 skills/website-ai-audit/scripts/compose.py --site <URL> --signals ./out/signals.json --agent ./out/agent_findings.json --scope ./out/scope.json --out ./out`
   Merges both layers, dedupes, sorts, numbers, validates, writes
   `out/report.json` + `out/report.md`.

If you skip step 2 (or write an empty `[]`), compose still produces a valid
report from the deterministic signals alone — the agent layer is additive.

## `context.json` shape (what you read)
`{site, render_available, robots_txt_found, sitemaps[], pages:[{url, fetch_class,
render_status, title, meta_description, lang, canonical, h1[], headings[],
jsonld:[{types[],name?,headline?}], images_total, images_missing_alt,
has_viewport, main_text_excerpt}]}`

## `agent_findings.json` shape (what you write)
A JSON list. Each item:
```
{
  "check": "answer-readiness",
  "title": "Pricing facts are buried in prose, not extractable",
  "severity": "medium",
  "half": "discoverability",
  "evidence": "On /pricing the plan tiers appear only inside a paragraph ('...starts at $29/mo for up to 5 seats...'); no table, list, or Offer/PriceSpecification markup — 1/12 pages carry pricing and none expose it as structured data.",
  "mechanism": "An assistant asked 'how much does X cost?' cannot lift a clean price/unit pair from running prose, so it omits or hedges the answer.",
  "location": "https://example.com/pricing",
  "suggested_action": {
    "summary": "Restate the three tiers on /pricing as a table (plan, price, seat cap) and add Offer/PriceSpecification JSON-LD mirroring it.",
    "priority": "medium",
    "effort": "low",
    "confidence": "medium"
  }
}
```
Field meanings match `references/finding-contract.md`. `severity` and
`suggested_action.priority` are `critical|high|medium|low`;
`half` is `discoverability|engagement|both`; `effort` is `low|medium|high`;
`confidence` is `high|medium|low`. `check` becomes the report `category`;
`location` (url + optional selector/header) is the dedup discriminator.

## False-positive guards (conservative by default)
- **Evidence-only.** Reason strictly from `context.json`. Never assert a fact
  about the site that isn't in the pack. If the evidence is thin, lower severity
  and confidence or drop the finding.
- **Clean pages stay clean.** Do not manufacture problems. A short, honest
  low-severity observation beats an invented high-severity one.
- **Never contradict a bad fetch.** Skip any page whose `fetch_class != "ok"`;
  its content fields are unreliable.
- **Don't double-report the scripts.** If `signals.json` already covers a
  mechanical fact (missing JSON-LD, missing viewport, missing alt text), don't
  restate it — add the judgment layer on top (is the fact actually answerable?),
  which the deterministic check cannot decide. Compose dedupes by
  `check`+`location`, but avoid the overlap in the first place.
- **Aggregate, don't spam.** One finding per issue-type with a `N/M pages`
  prevalence in `evidence`, not one finding per page.
- **Site-specific fixes only.** `suggested_action.summary` must name the actual
  page, entity, or field from the evidence — not a generic template line.
- **Render caveat.** If `render_available` is false, don't infer that
  client-rendered content is missing; note the limitation instead of asserting.
