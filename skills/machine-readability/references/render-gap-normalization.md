#### Render-gap normalization, thresholds, and false-positive guards

This is the detailed spec behind the `js-render-gap` and `fetch-latency-ttfb`
checks in `scripts/checks.py`. It exists so the thresholds live in one place and
so the reasoning behind each false-positive guard is reviewable.

#### Why this check matters
Most AI text crawlers (GPTBot, ClaudeBot, PerplexityBot) do not execute
JavaScript. If a page's main content is injected client-side after load, those
crawlers see an empty or near-empty shell — the brand's facts never enter the
model's view. The same client rendering also delays first paint for humans. This
is the highest-leverage machine-readability check.

#### The shared normalization pipeline
Both sides of every comparison go through the same `common.htmlutil` functions so
the raw-vs-rendered ratio is apples-to-apples:
- `htmlutil.main_text(html)` — extracts `<main>`/`<article>`, else body minus
  obvious chrome (nav/header/footer/aside/form), with script/style/noscript
  stripped. This is already applied by the fetch spine to produce
  `raw_main_text` and `rendered_main_text`.
- `htmlutil.norm_text(s)` — lowercases and collapses whitespace.

The check measures `len(norm_text(main_text))` on each side. Using main-content
scope (not whole-page bytes) means nav/footer boilerplate present on both sides
cannot mask or inflate the gap.

#### Mode A — measured raw-vs-rendered gap
Applies to each `ok` page where `render_status == 'ok'` and `rendered_main_text`
is present.
- `rendered = len(norm_text(rendered_main_text))`
- `raw = len(norm_text(raw_main_text))`
- Require `rendered > 600` (non-trivial) before computing a ratio.
- `ratio = raw / rendered`

Bucketed severity by the worst (smallest) ratio across affected pages:
- `ratio < 0.10` -> critical
- `ratio < 0.30` -> high
- `ratio < 0.55` -> medium
- `ratio >= 0.55` -> no finding

The finding cites a concrete missing signal (an H1 present in the rendered DOM
but absent from raw HTML, otherwise main-content text missing from raw HTML), and
aggregates to one finding with prevalence `N/M sampled pages`.

#### Mode B — static SPA heuristic (render check skipped/error)
Applies to each `ok` page where `render_status != 'ok'` (Playwright unavailable or
failed). Lower confidence; framed as "likely client-side rendered (render check
skipped — install Playwright chromium to confirm)". All three signals must hold:
1. Raw main text is very small: `len(norm_text(raw_main_text)) < 200`.
2. An empty framework mount is present in raw HTML: one of `id="root"`,
   `id="app"`, `id="__next"`, `id="__nuxt"`, `ng-app`, `ng-version`,
   `data-reactroot`. SSR markers (e.g. `data-server-rendered`) are deliberately
   excluded because they mean the raw HTML is already populated.
3. Heavy JS presence: `>= 3` `<script src>` tags OR `>= 20000` chars of inline
   script.

Severity: `high` if `>= 2` pages are suspect, else `medium`. Confidence `medium`.
Aggregated to one finding with prevalence `N/M pages`.

#### False-positive guards (both modes)
- Never emit from a page whose `fetch_class != 'ok'` — blocked/transient/404 means
  we could not read it, not that content is missing.
- Push BOTH sides through `norm_text` on main-content-scoped text.
- Require rendered main text `> 600` chars before trusting the ratio, so a tiny
  page cannot produce a misleading denominator.
- Emit bucketed severity, never a raw ratio float, so a server-rendered page whose
  raw HTML is already substantial (SSR/hydration, ratio `>= 0.55`) never trips.
- Base the finding on missing content (H1 / main text), not a raw byte diff.
- If a measured (Mode A) finding is produced, the static heuristic (Mode B) is not
  also emitted for the same run — measured evidence supersedes the heuristic.

#### fetch-latency-ttfb thresholds
Uses `p.elapsed_ms` on `ok` pages (a single lab sample, one geo).
- worst-case `> 3000ms` -> high
- worst-case `> 1800ms` -> medium (web.dev "poor TTFB" proxy)
- otherwise no finding

Reported as a lab proxy with a geo caveat, using the worst case across sampled
pages plus the count of slow pages (`N/M pages`). Framed as "at risk of crawler
timeout" (AI crawlers enforce ~1-5s timeouts with no retry), not "definitely
dropped". Confidence `low` because it is a single sample.
