---
name: entity-trust
description: >-
  Audits whether an AI assistant trusts and attributes a fact to the RIGHT brand.
  Deterministic scripts check the Organization entity anchor and @id graph in
  JSON-LD, sameAs resolvability (including Wikidata/Wikipedia), name consistency,
  freshness signals, and machine-readable E-E-A-T (author, citations, NAP). An
  agent layer then reasons over the evidence pack to judge entity ambiguity /
  mistaken identity and E-E-A-T quality. Use it when a task mentions entity, brand
  identity, Organization schema, sameAs, Wikidata, corroboration, mistaken
  identity, freshness, author, or E-E-A-T.
license: MIT
allowed-tools: "Bash, Read"
---

#### When to use
Use this skill to answer one question about a website: when an AI engine reads a
fact on this site, can it confidently attribute that fact to the correct brand
entity? Reach for it on requests about brand identity and disambiguation,
Organization schema and the @id graph, sameAs / Wikidata / Wikipedia links,
mistaken-identity risk from a generic name, content freshness, author / E-E-A-T
signals, or off-site corroboration.

#### How it runs (hybrid)
This skill has two layers over one shared read-only crawl. The deterministic
layer always runs and stands on its own; the agent layer is additive judgment on
top of it. You do not need an LLM for the deterministic floor.

The entrypoint runs the signal layer once for the whole marketplace:
`python3 skills/website-ai-audit/scripts/audit.py <URL> --out ./out --emit-context`
(add `--no-render` when no browser is available). That writes `out/signals.json`
(script findings from every sub-skill, including this one's), `out/context.json`
(the per-page evidence pack), and `out/scope.json`.

#### Deterministic signals (scripts)
These are already implemented and validated. They run mechanically and read-only,
reading rendered HTML when the render succeeded (JSON-LD is often JS-injected).
They land in `out/signals.json`:
- `org-entity-anchor-idgraph` — presence, core fields, and @id fragmentation of the Organization node.
- `sameas-resolvability` — broken sameAs targets and the Wikidata/Wikipedia anchor.
- `name-consistency-ambiguity` — brand-string consistency and the generic-name mistaken-identity flag.
- `freshness-signals` — copyright / dateModified / visible-updated / Last-Modified agreement.
- `author-eeat-contact-citations` — article author, byline agreement, citations, LocalBusiness NAP.
- `offsite-corroboration-surface` — absence of any off-site identity surface.

For the exact thresholds, bucketing rules, and false-positive guards behind these,
read `references/entity-disambiguation.md` (anchor, sameAs/Wikidata, generic-name
guard) and `references/corroboration.md` (freshness, machine-readable E-E-A-T, the
bot-blocked-host allowlist). The scripts already encode all of it; do not restate
it.

#### Agent reasoning (this skill's judgment checks)
Read `out/context.json` and reason over it — no re-fetch. These two questions need
judgment the scripts cannot make, and they belong to this skill:
1. Entity ambiguity / mistaken identity — could this brand name plausibly collide
   with other well-known entities, and does the site clearly disambiguate WHO or
   WHAT it is (a real About / value statement, distinctive descriptors)?
2. E-E-A-T quality — do the visible author / about / contact signals actually
   convey expertise and accountability, beyond merely existing?

Follow `references/entity-ambiguity-reasoning.md`. It is the agent-facing checklist
with the conservative guards: reason only from evidence in `context.json`, never
invent facts about the site, and do not flag a brand that is already well anchored
or clearly described. Write a finding only where the site is genuinely ambiguous or
thin, each with a concrete, site-specific fix. Append what you conclude to
`out/agent_findings.json` in the shared finding shape.

#### Compose
The entrypoint merges both layers:
`python3 skills/website-ai-audit/scripts/compose.py --site <URL> --signals ./out/signals.json --agent ./out/agent_findings.json --scope ./out/scope.json --out ./out`
It dedupes, sorts, numbers, counts, validates against the schema, and writes
`out/report.json` + `out/report.md`.

#### Output
Findings in the shared contract shape — each with a stable `check`, `half`,
`severity`, an `evidence` string carrying the numbers (and, for script findings, an
`N/M pages` prevalence), a `mechanism`, and a `suggested_action` (summary,
priority, effort, confidence). Findings are one per issue-type, aggregated across
pages, and never emitted from a page whose fetch failed. Everything is
recommend-only and read-only; the audit never modifies the site.
