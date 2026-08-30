---
name: crawler-access
description: Checks whether AI citation crawlers can reach a website at all — robots.txt per-bot blocking (GPTBot, PerplexityBot, Googlebot and friends), WAF/UA gating, indexability directives (noindex), redirect/status integrity, and sitemap/orphan discovery. Use when auditing crawlability, blocking, robots.txt, redirects, or why an AI assistant can't cite a site.
license: MIT
allowed-tools: "Bash, Read"
---

#### When to use
This is discoverability step 1 of the website AI-readiness audit: can an AI citation crawler get in at all? It covers robots.txt per-bot rules, WAF/UA blocking, noindex directives, redirect and HTTP-status integrity, and sitemap/orphan discovery. Trigger vocabulary: robots.txt, crawlability, blocking, GPTBot, PerplexityBot, noindex, sitemap, redirect, WAF.

#### What this skill contributes: deterministic signals only
Crawler-access is almost entirely mechanical. Every check here has a defensible, reproducible answer (a bot either resolves to Disallow or it does not), so all of it lives in the deterministic script layer. This skill adds **no new agent findings** — the agent's only job is to read the emitted signals and, where useful, interpret them in the narrative (see below).

#### Deterministic signals (scripts)
The entrypoint runs the shared signal layer once over one read-only crawl:

`python3 skills/website-ai-audit/scripts/audit.py <URL> --out ./out --emit-context`

(add `--no-render` when no browser is available). That run executes this skill's checks in `skills/website-ai-audit/scripts/checks.py` and writes them to `out/signals.json`. The seven checks:

- `robots-citation-bot-block` — a citation bot resolves to Disallow on the homepage.
- `robots-wildcard-catchall` — a citation bot with no named group inherits a `*` Disallow.
- `waf-ua-block-probe` — homepage OK under a browser UA but blocked under a bot UA (same client/IP).
- `indexability-directives` — `noindex` via meta robots or `X-Robots-Tag`, plus the Disallow+noindex self-cancel conflict.
- `http-status-redirect-canonical-integrity` — long redirect chains, non-200 finals, soft-404s, verifiably broken canonicals.
- `discovery-infra-sitemap-orphan-llmstxt` — no `Sitemap:` directive and no reachable `/sitemap.xml`.
- `blocked-render-assets` — same-origin CSS/JS that resolves to Disallow for a rendering engine.

Per-check thresholds, RFC 9309 group resolution, longest-match logic, and the false-positive guards are in `references/robots-semantics.md`. The citation-vs-training bot token map (blocking a training-only bot is a legitimate opt-out and is never flagged) is in `references/ai-user-agents.md`.

#### Agent reasoning (this skill's judgment)
The agent reads `out/context.json` and `out/signals.json` but does **not** re-run any access check and writes **no** `crawler-access` entries to `out/agent_findings.json`. Its only additive role is interpretive: when narrating the report, it may note whether a detected bot block looks intentional (e.g. a training-only opt-out, a staging host, a deliberately private path) versus an accidental barrier to citation. This interpretation must come only from the evidence in `out/context.json` — never invent intent the signals do not support.

#### Output
This skill's findings are the deterministic entries already in `out/signals.json`. The compose step merges them into the final report:

`python3 skills/website-ai-audit/scripts/compose.py --site <URL> --signals ./out/signals.json --agent ./out/agent_findings.json --scope ./out/scope.json --out ./out`

which dedupes, sorts, counts, validates against the schema, and writes `out/report.json` + `out/report.md`. Running `audit.py <URL> --out ./out` alone (no `--emit-context`, no agent layer) still produces a complete deterministic report — this skill needs no LLM to run.
