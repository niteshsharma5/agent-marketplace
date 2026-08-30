# Brand AI-Readiness Audit — Project Report

An Agent Skill Marketplace that audits any website for two things at once: whether AI assistants can **find and cite** the brand (AI discoverability) and whether human visitors who arrive actually **stay** (on-site engagement). Point it at a URL and it returns one prioritized report of problems — each with evidence, severity, and a mechanism-sound fix. It is recommend-only and read-only: it never modifies the audited site.

This report covers what we built, how it works, and — most importantly — the journey of how we built our own ground-truth test dataset and used it to iteratively raise the auditor's precision from 0.58 to 0.86 on sites it had never seen.

#### The problem
Round 3 of the challenge asks for a reusable Agent Skill Marketplace (agentskills.io format) that, pointed at any website, audits it and emits a findings-plus-fixes report. It is graded on the *skill's logic* — not any single report — and specifically on: detection accuracy with **few false positives**, mechanism-sound **prioritized fixes**, clear **output**, clean **skill/marketplace hygiene**, and **generalization to unseen sites**. No example sites are provided; generalization is tested by construction.

The underlying mechanics (from Round 2): an AI assistant only cites a page it can (1) reach, (2) read, and (3) pick a clean fact from — and it trusts facts that are corroborated and attributed to the right entity. A visitor only stays on a page that loads fast and orients them quickly. Those are two distinct failure surfaces, so the marketplace covers both.

#### What we built
A self-contained marketplace: one **entrypoint** skill orchestrating **five focused sub-skills** over a single shared, read-only crawl. The split follows the real mechanism chain rather than arbitrary topics.

| skill | concern it owns |
|-------|-----------------|
| `website-ai-audit` *(entrypoint)* | Runs the shared crawl, invokes the five sub-skills, merges everything into one schema-valid report. No detection of its own. |
| `crawler-access` | Can an AI citation crawler get in? robots.txt per-bot, WAF/UA gating, indexability, redirects/status, sitemap/orphans. |
| `machine-readability` | Once in, can a non-rendering crawler read it? The JavaScript render gap and fetch latency. |
| `fact-extractability` | Can a machine pick out the specific fact? JSON-LD, semantic HTML, head tags, facts locked in images. |
| `entity-trust` | Does the assistant trust and attribute the fact to the right brand? Organization anchor, sameAs, freshness, E-E-A-T, corroboration. |
| `onsite-engagement` | Why don't arriving visitors stay? Speed risk factors, accessibility, interstitials, mixed content, readability. |

Together the sub-skills implement **31 checks** across the two halves. A shared `common/` package holds the read-only fetch/render spine, robots handling, the finding contract, and report assembly — so the whole audit is one polite pass, not five. Each sub-skill is a valid agentskills.io skill (its own `SKILL.md`, `scripts/`, `references/`) and is independently runnable; `marketplace.json` names exactly one entrypoint.

#### How it's executed (hybrid)
Agent Skills are run *by* a general AI agent, so the marketplace is deliberately **hybrid**, splitting the work by what each side is genuinely better at:
- **Deterministic scripts own the mechanical, measurable signals** — robots per-bot, HTTP status, the raw-vs-rendered JS render gap, JSON-LD presence/validity, headers, contrast, mixed content. These are a clean pass/fail, so a script does them reproducibly with no LLM.
- **The invoking agent owns the judgment** — is the content actually *answer-ready* and quotable? is the brand *entity* ambiguous vs. lookalikes? is the value proposition clear? — and writes *site-specific* fixes and the final narrative, reasoning over an evidence pack the scripts emit (`--emit-context` → the agent writes `agent_findings.json` → `compose.py` merges both into one schema-valid report).

Because the script layer already emits a complete report, the marketplace also runs **headless** (`audit.py <URL>`), with no LLM and no gateway — the agent layer is purely additive. This is also why the evaluation below could measure the deterministic layer's precision objectively: it's the reproducible floor, and the agent layer adds coverage on top of it.

#### How a finding looks
Every finding meets the required schema floor and extends it usefully:
- `id`, `title`, `severity` (critical/high/medium/low), `evidence` (a concrete string with numbers and prevalence, e.g. "0/12 product pages carry schema.org markup"),
- plus `category`, `half` (discoverability/engagement/both), the `mechanism` it addresses, and a `suggested_action` with a fix `summary`, a fix-first `priority`, `effort`, and `confidence`.

The report also carries a `summary` (counts by severity + a discoverability/engagement split), a `scope` block, and an honest `limitations` block (single-variant fetch, lab-vs-field metrics, network-dependent checks). Counts are computed from the findings — never hand-maintained — and everything is validated against a bundled JSON Schema before emit.

#### How it runs — the guarantees
- **Read-only and recommend-only.** GET/HEAD only, no auth, no writes to the target. robots.txt is honored for our own crawl.
- **Deterministic.** Fixed page sampling (homepage + a sorted, capped set of internal/sitemap URLs), sorted iteration, bucketed thresholds, and an injectable timestamp. Two runs on static input are byte-identical.
- **Fast and bounded.** One shared fetch (and optional render) per page; a fixture audit runs in ~0.03s and the design budget is well under the 5-minute limit.
- **Portable and small.** Pure-Python core; the package is 1.8 MB with no model weights. The JavaScript render-gap check uses a headless browser when available and **degrades to a static SPA heuristic** when it isn't — nothing crashes.
- **Conservative by default.** Every check carries explicit false-positive guards; blocked or unreadable pages never produce "content missing" findings.

#### Testing: the bias problem we designed around
The hardest part of a task graded on "few false positives" and "generalization" is testing it honestly. If the same author writes the detector, the test data, *and* the grader, the tests just confirm the code does what its author intended — they prove nothing. Our first, biased fixtures demonstrated exactly this trap: they reported a flawless **0% false-positive rate**, which was meaningless because their authors had seen the checks.

So we rebuilt testing around a strict **information barrier**, with no single model both creating ground truth and judging against it:

| role | who | knows the detector? | model |
|------|-----|--------------------|-------|
| system under test | the auditor (deterministic Python) | it *is* the detector | code, not a model |
| test-set author | blind red-team generators | no (walled off from our code) | Sonnet |
| grader | blind adjudicators | no (judge on merits) | Opus |
| tie-breakers | prosecutor / defender / referee | no | Sonnet / Sonnet / Opus |

Because the auditor is code, there is no prompt to quietly tune toward the tests. Fixes only ever came from *generalizable* logic errors the blind graders surfaced — never from special-casing a site.

#### The journey: a ground-truth test set, and iterating to higher precision
This is the heart of the project.

**Step 1 — build a labeled dataset, kept blind.** We had an independent red team author its own realistic websites — SaaS SPAs, a local restaurant, e-commerce, a news site, a corporate brand page, a personal blog, a government page, and deliberately-clean controls — and, for each, seal a **ground truth in its own words**: every genuine problem (with severity and mechanism), plus the aspects that are *fine* and the legitimate *traps* (dense expert prose, decorative empty `alt`, a deliberate training-bot opt-out) that must **not** be flagged. Crucially, the authors never saw how the auditor detects anything. This gave us a dataset of realistic sites each paired with trustworthy labels — our yardstick.

**Step 2 — measure honestly.** We ran the deterministic auditor over the blind sites, then had independent judges inspect each site themselves and score every finding true-positive or false-positive against reality, with a prosecutor/defender/referee debate settling contested calls. The verdict: **precision 0.576** — 49 true positives against **36 false positives**. The biased fixtures had hidden all of it.

**Step 3 — find the root causes.** The false positives were not random; they clustered into a handful of *systematic, generalizable* logic bugs the judges pinpointed and the debate confirmed:
- flagging "served over plain HTTP" whenever the fetch origin was `http://`, even when the site's own canonical/sitemap declared HTTPS;
- over-claiming "render-blocking / heavy" on tiny pages whose only real factor was missing gzip;
- penalizing an off-domain canonical (legitimate staging/CDN practice) — and even suggesting a fix that would break the site;
- treating `ClaudeBot` and `Meta-ExternalAgent` (training crawlers) as citation bots;
- rejecting a valid `ProfilePage`/`Person` author page for lacking Article schema;
- entity checks blind to an `Organization` nested under `NewsArticle.publisher`, to bylines like "By Priya Chandran, Senior Correspondent" (a superset of the schema author), and to `Person.sameAs`;
- auditing `robots.txt` as if it were an HTML page;
- emitting noise for a missing `llms.txt` (a convention no crawler requires).

**Step 4 — fix generalizably.** Two fix cycles corrected the *logic* — each fixer was told the general bug and its mechanism and was explicitly forbidden from special-casing any URL or the test sites. Result on the round-1 set: **28 false positives removed, zero real regressions**, white-box regression still perfect.

**Step 5 — prove it generalizes.** The real test of whether we'd fixed logic or just memorized: we generated a **fresh, held-out batch of six new site archetypes** (recipe blog, dental clinic, university department, fashion store, B2B enterprise, crypto startup) — created *after* and blind to every fix — and ran the whole blind pipeline again.

| run | sites | precision | true positives | false positives |
|-----|-------|-----------|----------------|-----------------|
| Round 1 (pre-fix) | 8 blind | **0.576** | 49 | 36 |
| Held-out (post-fix) | 6 fresh blind | **0.857** | 30 | 5 |

Precision rose from 0.58 to **0.86 on sites the system had never seen**, with zero regressions. Clean control sites that previously drew 5–12 findings now draw 2–3. The five residual false positives are spread one-per-category and are borderline judgment calls (an inflated severity on an otherwise-valid entity, a deliberately-planted fictional-brand trap, a dated site with no HTTPS self-reference) — not systematic bugs.

#### Results against the rubric
- **Detection accuracy / few false positives / both halves** — measured, not asserted: 0.86 precision on unseen sites, with per-half coverage in every report. Proven by the blind eval, not by fixtures we wrote.
- **Suggested-action quality** — every finding carries the mechanism it addresses, a fix-first priority distinct from severity, effort, and confidence; speculative levers are marked low-confidence.
- **Output design** — one schema-validated JSON report plus a readable Markdown view a non-expert can act on.
- **Skill/marketplace hygiene** — six agentskills.io-valid skills, exactly one entrypoint, deterministic, safe; a validator enforces it.
- **Generalization** — demonstrated by construction: the headline number comes from held-out sites created after the fixes.

#### Limitations and next steps
- **Recall is the open axis.** On the held-out set the auditor missed 28 lower-severity issues (meta-description quality, some dark-background contrast, dead CTAs, per-page social cards). Precision was the priority for this rubric; recall is the natural next loop, using the same blind methodology.
- **Live network is out of scope in the sandbox.** The field-realism suite runs via offline snapshots (`capture.py`) captured outside the sandbox, which also makes it deterministic and reproducible.
- **A few checks are network-dependent** (sameAs resolvability, broken links) and are labeled as such rather than folded into the determinism guarantee.

#### How to run
```
pip install -r requirements.txt
python3 skills/website-ai-audit/scripts/audit.py https://example.com --out ./out
```
Testing: `python3 evaluation/validate_marketplace.py` (hygiene), `python3 evaluation/scorecard.py` (white-box regression), `python3 evaluation/run_harness.py` (determinism/politeness/budget), `python3 evaluation/blackbox/run_eval.py` (blind audit; adjudicate separately). See `TESTING.md` for the full methodology and `README.md` for the marketplace layout.
