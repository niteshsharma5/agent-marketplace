---
name: machine-readability
description: >-
  Checks whether a non-rendering AI crawler can actually read a page once it is
  allowed in. Detects the JavaScript render gap where client-rendered content is
  invisible to non-rendering AI crawlers, and flags fetch latency that risks
  crawler timeouts. Use it for concerns about JS rendering, SPA / client-side
  rendering, render gap, hydration, empty HTML shells, TTFB, and crawler timeout.
license: MIT
allowed-tools: "Bash, Read"
---

#### When to use
Use this skill when auditing whether an AI text crawler (GPTBot, ClaudeBot,
PerplexityBot) that executes zero JavaScript can read a page's main content, and
whether the page returns fast enough to avoid a crawler timeout. Triggers: JS
rendering, SPA, client-side rendering, render gap, hydration, empty HTML, TTFB,
crawler timeout.

This is discoverability step 2 (once in, can the crawler READ it). It does not
cover robots/access gating (that is crawler-access) or on-page facts and
structured data (that is fact-extractability).

#### How this runs in the hybrid audit
The `website-ai-audit` entrypoint runs the deterministic signal layer once over a
shared crawl, then the agent reasons over the evidence pack. This skill's
detection is entirely deterministic; the agent's role here is a light
interpretation on top of it. The auditor produces a complete report with no
agent involvement in headless mode — the reasoning below is additive, not
required.

#### Deterministic signals (scripts)
Produced by the entrypoint's signal layer, which already includes this skill's
`scripts/checks.py`:

`python3 skills/website-ai-audit/scripts/audit.py <URL> --out ./out --emit-context`
(add `--no-render` when no browser is available).

It writes `out/signals.json` (script findings), `out/context.json` (the per-page
evidence pack), and `out/scope.json`. This skill contributes two checks:
- `js-render-gap` — raw-HTML vs rendered-DOM main-text comparison, with a static
  SPA fallback when the render step was skipped.
- `fetch-latency-ttfb` — lab-proxy response-latency worst case.

Thresholds, bucket boundaries, the shared normalization pipeline, and the
SSR/hydration false-positive guards live in
`references/render-gap-normalization.md`. Do not re-derive them inline.

#### Agent reasoning (this skill's judgment checks)
Additive and evidence-only. After the signal layer runs, READ `out/context.json`
and reason over it — no re-fetch. When a `js-render-gap` signal was raised, name
WHICH concrete facts from a page's rendered `main_text_excerpt` (and its `title`,
`h1`, `headings`) are absent from the raw HTML the crawler sees. Detection stays
the script's job; the agent only makes the gap concrete and site-specific.

Reason ONLY from `context.json`; never invent facts about the site; keep
judgments conservative (a clean, server-rendered page gets no finding). Write any
concluded findings to `out/agent_findings.json` in the agent-findings shape, with
site-specific evidence and a fix that names the actual missing content — not a
template.

#### Compose the report
`python3 skills/website-ai-audit/scripts/compose.py --site <URL> --signals ./out/signals.json --agent ./out/agent_findings.json --scope ./out/scope.json --out ./out`

This merges script and agent findings, dedupes, sorts, counts, validates against
the JSON Schema, and writes `out/report.json` + `out/report.md`.

#### Standalone spot check
`python3 scripts/checks.py https://example.com` runs just this skill's
deterministic checks against one URL and prints the findings as JSON.
