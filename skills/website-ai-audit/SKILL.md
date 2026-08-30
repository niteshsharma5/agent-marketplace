---
name: website-ai-audit
description: >-
  Entry point that audits a website for AI discoverability (why AI assistants
  like ChatGPT, Perplexity, Gemini/AI Overviews and Claude fail to find or cite
  the brand) and on-site engagement (why visitors who arrive don't stay). It
  runs one shared read-only crawl that produces deterministic signals plus a
  per-page evidence pack, has the agent reason over that pack for the
  judgment-heavy checks, and emits a single prioritized findings-plus-fixes
  report. Use when asked to audit a site for AI search visibility, GEO/AEO
  readiness, LLM citability, or why a brand is invisible, misrepresented, or
  bouncing traffic in AI apps.
license: MIT
allowed-tools: Bash, Read
---

# Website AI-Readiness Audit (entrypoint)

The one skill you invoke. It runs a hybrid audit: deterministic scripts own the
mechanical, measurable signals over a single shared crawl, and you (the agent)
own judgment, site-specific fixes, and the final narrative.

## When to use
Someone gives a website URL and wants to know why AI assistants don't cite it
and/or why arriving visitors bounce, plus what to fix first. This skill produces
the final report; the other five sub-skills are its building blocks.

## Inputs
A single website URL or domain (e.g. `https://example.com`). Optional: page
sample cap (`--max-pages`, default 12), whether a browser is available.

## Who owns what
- **Deterministic scripts** own the mechanical/measurable signals — robots and
  per-bot access, status codes, JS render gap, latency, presence/shape of
  JSON-LD and head tags, alt-text counts, viewport, and every other check that
  is a clean pass/fail measurement. These run with no LLM.
- **The agent (this skill)** owns judgment: reading the evidence pack to decide
  whether facts are actually answer-ready, whether the site's entity is
  ambiguous, whether engagement leaks are real, and writing the site-specific
  fixes and the final narrative.

## Procedure (hybrid)
1. Run the signal layer ONCE. It executes every sub-skill's deterministic checks
   over one shared read-only crawl and emits the evidence pack:
   `python3 skills/website-ai-audit/scripts/audit.py <URL> --out ./out --emit-context`
   Add `--no-render` if no browser is available (static-only fetch). This writes
   `out/signals.json` (script findings), `out/context.json` (per-page evidence
   pack), and `out/scope.json` (crawl scope + per-skill errors).
2. Read `out/context.json` and REASON over it — no re-fetching. For the
   judgment-heavy checks, follow the reasoning checklists in the sub-skills:
   - `skills/fact-extractability/references/answer-readiness-reasoning.md`
   - `skills/entity-trust/references/entity-ambiguity-reasoning.md`
   - `skills/onsite-engagement/references/engagement-judgment-reasoning.md`
   Write the findings you conclude to `out/agent_findings.json` (a JSON list in
   the shared finding shape). See `references/hybrid-procedure.md` for the exact
   loop, the `agent_findings.json` shape, a worked example, and the
   false-positive guards.
3. Compose the report. This merges script + agent findings, dedupes, sorts,
   numbers `F-001…`, recomputes counts, and validates against the schema:
   `python3 skills/website-ai-audit/scripts/compose.py --site <URL> --signals ./out/signals.json --agent ./out/agent_findings.json --scope ./out/scope.json --out ./out`
4. Present `out/report.md` to the user.

## Headless deterministic fallback
The audit does NOT need an LLM to run. To get a complete deterministic report
with no agent layer (used by CI and as the quality floor), run the orchestrator
alone: `python3 skills/website-ai-audit/scripts/audit.py <URL> --out ./out`.
The agent-reasoning layer in step 2 is purely additive on top of that floor.

## References
- `references/hybrid-procedure.md` — the emit-context → reason → compose loop,
  the `agent_findings.json` shape, and a worked example.
- `references/orchestration.md` — which sub-skill covers what, budget + safety.
- `references/finding-contract.md` — the finding shape both layers emit.
- `references/report-schema.md` — the validated report schema.

## Output
One audit report (`out/report.json`, schema-validated) with `site`,
`audited_at`, a counts-by-severity `summary` (+ discoverability/engagement
split), and a `findings` array where each finding carries `id`, `title`,
`severity`, `category`, `half`, `evidence`, `mechanism`, and a prioritized
`suggested_action`. A human-readable `out/report.md` is emitted alongside. The
audit is recommend-only and read-only — it never modifies the audited site.
