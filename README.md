# brand-ai-audit

An Agent Skill Marketplace that audits any website for two things at once: whether AI assistants can **find and cite** the brand, and whether human visitors who arrive actually **stay**. Point it at a URL and it produces one prioritized report of problems (with evidence and severity) plus mechanism-sound fixes. It is recommend-only and read-only — it never touches the live site.

#### Why both halves
An AI assistant only cites a page it can reach, read, and quote a clean fact from. A visitor only converts on a page that loads fast and orients them quickly. Those are two different failure surfaces, so the marketplace covers both and labels every finding as `discoverability`, `engagement`, or `both`.

#### How it's composed
One entrypoint skill orchestrates five focused sub-skills over a single shared, read-only crawl. The split follows the actual mechanism chain — a crawler must be let *in*, then be able to *read* the page, then *pick out* the fact, then *trust* it — plus the engagement half.

| skill | concern |
|-------|---------|
| `website-ai-audit` *(entrypoint)* | Runs the shared crawl, invokes the five sub-skills, merges everything into one schema-valid report. No checks of its own. |
| `crawler-access` | Can an AI citation crawler get in? robots.txt per-bot, WAF/UA gating, indexability, redirects, sitemap/orphans. |
| `machine-readability` | Once in, can a non-rendering crawler read it? The JavaScript render gap and fetch latency. |
| `fact-extractability` | Can a machine pick out the specific fact? JSON-LD, semantic HTML, head tags, facts locked in images. |
| `entity-trust` | Does the assistant trust and attribute the fact to the right brand? Organization anchor, sameAs, freshness, E-E-A-T, corroboration. |
| `onsite-engagement` | Why don't arriving visitors stay? Speed risk factors, accessibility, interstitials, mixed content, readability. |

Each sub-skill is a valid agentskills.io skill (its own `SKILL.md`, `scripts/`, `references/`) and is independently runnable. They share one read-only spine in `common/` (fetch/render, robots, the finding contract, report assembly) so the whole audit is one polite pass, not five.

**Hybrid by design.** Deterministic scripts own the mechanical, measurable signals (robots, JS render gap, JSON-LD, headers, contrast, …) — reproducible and no LLM. The invoking AI agent owns the judgment calls (is content answer-ready? is the brand entity ambiguous? is the value prop clear?) and writes site-specific fixes, reasoning over an evidence pack the scripts produce. The scripts alone still emit a complete report, so the marketplace also runs headless (see below).

#### Prerequisites
- **Python 3.11+** (developed on 3.11.13).
- The pip packages in `requirements.txt` (all pure-Python, ~a few MB): `httpx`, `beautifulsoup4`, `lxml`, `w3lib`, `protego`, `jsonschema`.
- **Internet access to the website you're auditing** (the tool fetches the site over HTTPS). Nothing else outbound is needed.
- Optional: a headless browser for the JS render-gap live diff, and OCR — see below. Both are optional; the tool degrades gracefully without them.

No API keys, no accounts, no config files.

#### Does it need an LLM / a gateway?
This is an **Agent Skill marketplace**, so it is designed to be run *by* a general AI agent — but the detection engine is pure Python. That gives two ways to run it, and **neither needs a separate/bespoke LLM gateway**:

1. **Headless / deterministic (no LLM, no keys).** Run the entrypoint script directly and you get a complete report from the deterministic signal layer:
   ```
   python3 skills/website-ai-audit/scripts/audit.py https://example.com --out ./out
   ```
   No model call, no API key, no gateway — just Python + internet. Ideal for CI, teammates without an agent, and reproducible runs.

2. **Full hybrid (best results).** Invoke the entrypoint *skill* inside whatever AI agent you already use (Claude Code, or any agent that supports the agentskills.io skill format). The scripts gather the mechanical signals (`--emit-context`), the agent reasons over the evidence pack for the judgment checks (answer-readiness, entity clarity, engagement) and writes site-specific fixes, then `compose.py` merges both into the final report. The "LLM" here is simply **the agent you're running the skill in** — it uses that agent's own model. There is nothing to configure and no DeSco-specific gateway to stand up.

   Easiest way: open the repo in your agent and say *"Use the website-ai-audit skill to audit https://example.com and show me the report."* To run the same steps by hand:
   ```
   python3 skills/website-ai-audit/scripts/audit.py https://example.com --out ./out --emit-context
   #   → the agent reads out/context.json and writes out/agent_findings.json
   python3 skills/website-ai-audit/scripts/compose.py --site https://example.com \
       --signals ./out/signals.json --agent ./out/agent_findings.json --scope ./out/scope.json --out ./out
   ```
   Output is the same as headless: `out/report.json` + `out/report.md`.

**Which model?** Nothing is hardwired to a provider. We developed and tested with Claude (Sonnet for generating the blind test dataset, Opus for grading it — see `evaluation/`), but any capable agent works. Reproducing the eval metrics is pure Python and needs no LLM; only *regenerating or re-grading the blind dataset* would use an agent again (optional, dev-only).

#### Quickstart (audit a website)
```
git clone <your-repo-url> && cd brand-ai-audit
pip install -r requirements.txt
python3 skills/website-ai-audit/scripts/audit.py https://example.com --out ./out
```
Outputs `out/report.json` (schema-validated) and `out/report.md` (human-readable). Flags: `--max-pages N` (default 12), `--no-render` (static-only, fastest), `--format json|md|both`, `--audited-at ISO` (fix the timestamp for reproducible output).

#### Will it finish in under 5 minutes?
Yes, by design. It samples a capped set of pages (default 12), does one shared read-only pass, and puts a timeout on every check.
- **Static mode** (`--no-render`, or when no browser is installed): typically **seconds to a few tens of seconds** for a normal site — it's dominated by how fast the site responds.
- **With browser rendering**: add roughly 1–3s per sampled page, so still comfortably **1–2 minutes** for a typical site. Lower `--max-pages` for very large/slow sites.

#### Optional: browser rendering for the JS render-gap check
```
pip install playwright && playwright install chromium --only-shell
```
With a browser, `machine-readability` does a real raw-vs-rendered diff. Without it, that skill falls back to a static SPA heuristic and the report notes the render check was skipped — nothing crashes. (Optional OCR of image-locked facts needs `pytesseract` + `Pillow` + the `tesseract` binary; it's off by default.)

#### Reproduce the evaluation (no LLM needed)
```
python3 evaluation/validate_marketplace.py   # structure + hygiene
python3 evaluation/scorecard.py              # white-box regression (recall / FP-rate)
python3 evaluation/run_harness.py            # determinism + robots-politeness + budget
python3 evaluation/blackbox/run_eval.py      # re-audit the saved blind sites
```
The blind dataset, sealed ground truth, saved auditor findings, and the independent grading are all committed under `evaluation/` — see `evaluation/README.md`. The methodology and results are in `TESTING.md`; the full write-up (incl. the improvement journey) is in `REPORT.md`, and slides in `PRESENTATION.pptx`.

#### A note on heavily bot-protected sites (e.g. amazon.com)
Some large sites (Amazon, Instagram, LinkedIn) aggressively block bots via WAF challenges and a big `robots.txt` disallow list. This tool **honors `robots.txt` and never fabricates "content missing" findings from a blocked fetch** — so on those sites many pages come back classified as `blocked`/`inconclusive` and the report is thinner than the tool is capable of. It still runs and produces a valid report. To see the tool at its best, point it at a normal marketing site, a blog, a Shopify store, or a mid-size brand, and keep `--max-pages` modest on very large sites.

#### Output shape
A report with `site`, `audited_at`, a counts-by-severity `summary` (plus a discoverability/engagement split), and a `findings` array. Every finding carries `id`, `title`, `severity`, `category`, `half`, `evidence`, the `mechanism` it addresses, and a prioritized `suggested_action` with `effort` and `confidence`. Schema: `common/schema.json`.

#### Design choices worth knowing
- **Conservative by default.** Every check has explicit false-positive guards (documented in each skill's `references/`). Blocked or unreachable pages never produce "content missing" findings. When a signal is soft, it lands as `low` with lower `confidence` rather than as a false alarm.
- **Deterministic.** Fixed page sampling, sorted iteration, bucketed thresholds, and an injectable timestamp. Two runs on static input are byte-identical except `audited_at`. The few network-dependent checks (sameAs resolvability, broken links) are labeled as such in `limitations`.
- **Honest about limits.** The report ships a `limitations` block (single-variant fetch, lab-vs-field metrics, personalization) so nothing is over-claimed.

#### Manifest note
`marketplace.json` (name, version, skills, exactly one `entrypoint: true`) is this contest's own lightweight convention — deliberately not Claude Code's native auto-discovery manifest, because we need to name which skill orchestrates the rest. It is self-contained; no external service resolves it.
