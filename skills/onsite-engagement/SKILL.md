---
name: onsite-engagement
description: >-
  Audits why arriving visitors do not stay (the engagement half of a website
  audit). Deterministic scripts flag mechanical risk factors: page-weight and
  render-blocking speed, image optimization, layout stability (CLS), mobile
  viewport and zoom, contrast and legibility, intrusive interstitials and
  autoplay, mixed content and HTTPS, broken internal links, and a readability
  metric. An agent layer then judges page orientation from the evidence pack:
  whether a visitor can tell what the page is and what to do next, and whether
  the content delivers what its headings promise. Use it when a request mentions
  engagement, bounce, page speed, Core Web Vitals, mobile, accessibility,
  contrast, popups, readability, broken links, or page orientation.
license: MIT
allowed-tools: "Bash, Read"
---

#### When to use
Use this sub-skill when a caller wants to understand why traffic that reaches a
site bounces instead of engaging: slow first paint, unoptimized images, layout
shift, a broken mobile experience, unreadable contrast or tiny text, intrusive
popups or autoplaying video, insecure mixed content, dead internal links, dense
copy, or a page that fails to orient the visitor. It is one of five sub-skills
composed by the `website-ai-audit` entrypoint over one shared crawl.

#### How this skill runs (hybrid)
The mechanical signals are deterministic and need no LLM. The orientation and
intent judgments are done by the agent reasoning over the shared evidence pack.
The agent layer is additive: with no agent step, the deterministic checks still
produce a complete engagement report on their own.

#### Deterministic signals (scripts)
The entrypoint runs the signal layer once across all sub-skills over one shared
read-only crawl:

`python3 skills/website-ai-audit/scripts/audit.py <URL> --out ./out --emit-context`

Add `--no-render` when no browser is available. This skill's script checks run
inside that pass and write their findings to `out/signals.json`. They cover the
mechanical, markup-measurable risk factors only: page weight / render-blocking
transfer, image optimization / lazy-load, layout stability (CLS), mobile
viewport / zoom, contrast / legibility, intrusive interstitials / autoplay,
mixed content / HTTPS, broken internal links, and the readability metric. Each
check runs over readable pages (`fetch_class == 'ok'`), aggregates to one
finding per issue-type with `N/M pages` prevalence, and applies the guards in
`references/false-positive-guards.md`. Thresholds and their WCAG / web.dev /
HTTP Archive provenance live in `references/engagement-thresholds.md`.

#### Agent reasoning (this skill's judgment checks)
After the signal layer, read `out/context.json` (the per-page evidence pack) and
reason over it. Do not re-fetch. This skill owns two judgment checks that markup
thresholds cannot settle:

1. Value-proposition clarity and orientation — from `title`, `h1`, `headings`,
   and `main_text_excerpt`, can a visitor tell within seconds what this is and
   what to do next?
2. Content answers intent — does the page deliver what its title and headings
   promise, or bury it?

Follow the checklist and conservative guards in
`references/engagement-judgment-reasoning.md`. Reason only from the evidence in
`context.json`; never invent facts about the site; keep judgments conservative.
A clear hero with a real value proposition is fine, so do not flag it. Write
findings only where orientation or intent is genuinely weak, each with a
site-specific fix, and append them to `out/agent_findings.json` in the agent
findings shape (`half` = `engagement`).

#### Compose
Merge the script and agent findings into the final report:

`python3 skills/website-ai-audit/scripts/compose.py --site <URL> --signals ./out/signals.json --agent ./out/agent_findings.json --scope ./out/scope.json --out ./out`

Compose dedupes, sorts, numbers, counts by severity, validates against the JSON
Schema, and writes `out/report.json` + `out/report.md`.

#### Headless fallback
`python3 skills/website-ai-audit/scripts/audit.py <URL> --out ./out` alone
produces a complete deterministic engagement report with no agent step. The
orientation and intent judgments are simply omitted in that mode.

#### Inputs
A single URL (the site to audit). The shared fetch/render pass supplies the page
sample and the evidence pack; this skill reads those and never writes to the
target. GET/HEAD only.

#### Output
Deterministic findings in `out/signals.json` and, when the agent layer runs,
orientation/intent findings in `out/agent_findings.json`, both in the shared
contract shape. The entrypoint's compose step merges, dedupes, sorts, numbers,
and validates them into `out/report.json` and `out/report.md`.
