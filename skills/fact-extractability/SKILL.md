---
name: fact-extractability
description: Audits whether a machine can pick out the specific correct fact from a page — JSON-LD structured data presence and validity, schema-vs-visible consistency, title/meta/heading orientation, facts locked in images, canonical/lang correctness, and answer-ready content. Use when auditing structured data, schema.org, JSON-LD, rich results, meta description, H1, alt text, canonical tags, or general fact extractability for AI and search engines.
license: MIT
allowed-tools: "Bash, Read"
---

# Fact extractability

Covers discoverability step 3 of the website AI-readiness audit: once a machine can reach and parse a page, can it pull out the exact correct fact (price, headline, author, product name) instead of guessing? This skill has two layers. The deterministic scripts catch the mechanical signals. The agent layer reasons over the evidence pack for the judgment calls that a regex cannot make.

## When to use
Use during a website AI-readiness audit when you need to know whether structured data, page orientation, and content shape let an AI assistant or search engine extract facts cleanly. It covers structured data (schema.org / JSON-LD), schema-vs-visible agreement, page orientation signals (title, meta description, H1, heading order), facts trapped in images, canonical/lang tags, and answer-ready content structure.

## Deterministic signals (scripts)
These run inside the shared crawl. You do not run them per skill — the entrypoint runs every sub-skill's checks once over one read-only crawl:

```
python3 skills/website-ai-audit/scripts/audit.py <URL> --out ./out --emit-context
```

Add `--no-render` when no browser is available. This writes `out/signals.json` (the script findings), `out/context.json` (the per-page evidence pack), and `out/scope.json`. The script layer alone is a complete report floor and needs no agent or LLM.

The checks this skill contributes to `signals.json`, each aggregated into one finding with `N/M pages` prevalence:
- `jsonld-presence-validity` — schema on type-warranting pages, plus required props for the types actually present.
- `schema-visible-consistency` — JSON-LD price/name vs visible default-variant text.
- `title-meta-heading-orientation` — generic/missing title, missing meta description, zero H1, heading jumps.
- `facts-in-images-alt` — content images missing an alt attribute; image-only pages.
- `canonical-lang-hreflang` — missing/relative canonical, missing `<html lang>`.

See `references/schema-required-props.md` for per-type required props and page-role inference, and `references/extractability-patterns.md` for the orientation, non-text-trap, and alt-text rules with their thresholds and false-positive guards.

## Agent reasoning (this skill's judgment checks)
Read `out/context.json` and reason over it directly — do not re-fetch anything. Two judgments live here because they need reading comprehension, not pattern matching:

1. **Answer-readiness** — for each readable page, is the main content quotable by a RAG system? Self-contained factual sentences, question-style headings, lists or tables, and the answer front-loaded rather than buried.
2. **Schema-type fit** — when JSON-LD is missing or the present type is wrong for the page, judge the correct schema.org type from the page's actual role (for example `WebSite` + `Organization` + `FAQPage` for a landing page, `Recipe` for a recipe, `Article` for editorial) instead of a generic guess.

Follow `references/answer-readiness-reasoning.md` for how to judge both and for the conservative guards that keep clean, answer-ready pages unflagged. Write only genuinely weak pages, each with a site-specific fix, to `out/agent_findings.json` in the shape:

```
{check, title, severity, half, evidence, mechanism, location, suggested_action:{summary, priority, effort, confidence}}
```

Reason only from the evidence in `context.json`. Never invent facts about the site, and prefer a low-severity honest observation over a manufactured problem.

## Compose
Merge the script and agent findings into the final report:

```
python3 skills/website-ai-audit/scripts/compose.py --site <URL> --signals ./out/signals.json --agent ./out/agent_findings.json --scope ./out/scope.json --out ./out
```

This dedupes, sorts, counts, validates against the JSON Schema, and writes `out/report.json` + `out/report.md`.

## Output
Findings in the shared contract shape, split across `signals.json` (scripts) and `agent_findings.json` (this skill's judgment layer), merged by compose into one schema-valid report. The audit is read-only and recommend-only; it never modifies the audited site.
