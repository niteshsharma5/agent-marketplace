# Orchestration

## Composition model (hybrid)
`audit.py` runs ONE shared read-only pass over the sampled pages and runs every
sub-skill's DETERMINISTIC checks against that single cached crawl — sub-skills
never re-fetch, which keeps the audit polite and under the 5-minute budget.

Two runtimes share that one crawl:
- **Headless / deterministic floor** — `audit.py <URL> --out ./out` runs the
  scripts and writes the full `report.json` + `report.md` with no LLM.
- **Hybrid** — `audit.py <URL> --out ./out --emit-context` runs the same scripts
  but writes `signals.json` (script findings) + `context.json` (a per-page
  evidence pack) + `scope.json`. The invoking agent reasons over `context.json`
  for the judgment-heavy checks, writes `agent_findings.json`, and `compose.py`
  merges both layers into the report. See `hybrid-procedure.md`.

The deterministic scripts own the mechanical/measurable signals; the agent owns
judgment, site-specific fixes, and the final narrative.

## Which sub-skill covers what (the discoverability chain + engagement)
| stage | sub-skill | question it answers |
|-------|-----------|---------------------|
| 1 | `crawler-access` | Can an AI citation crawler get in? (robots per-bot, WAF/UA, indexability, status, sitemap) |
| 2 | `machine-readability` | Once in, can a non-rendering crawler read it? (JS render gap, latency) |
| 3 | `fact-extractability` | Can it pick out the specific fact? (JSON-LD, semantic HTML, head tags, non-text traps) |
| 4 | `entity-trust` | Does it trust/attribute the fact to the right brand? (Organization anchor, sameAs, freshness, E-E-A-T, corroboration) |
| — | `onsite-engagement` | Why don't arriving visitors stay? (speed, a11y, friction, security, readability) |

Fixed invocation order (deterministic): crawler-access → machine-readability →
fact-extractability → entity-trust → onsite-engagement.

## Budget & safety rules
- Deterministic scope: homepage + a sorted, capped sample of internal/sitemap URLs (default cap 12).
- One shared fetch (and optional render) per page; sub-skills read the cache.
- Bounded extra fetches (~30 total, GET/HEAD only) for network-dependent checks
  (sameAs resolvability, broken links). Same-origin extra fetches honor robots.
- Read-only always: no auth, no POST, no writes to the target. Robots.txt honored for our crawl.
- One sub-skill raising never aborts the run — the entrypoint records the error in `scope.skill_errors` and continues.

## Manifest note
`marketplace.json` is this contest's lightweight convention (name, version,
skills[], exactly one `entrypoint: true`). It is intentionally not Claude Code's
native `.claude-plugin/marketplace.json`, which auto-discovers skills and has no
entrypoint field — we need to express which skill orchestrates the rest.
