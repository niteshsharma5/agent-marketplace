import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
from common.contract import make_finding
from common import htmlutil

import re

# Static SPA mount markers: an element that a client-side framework hydrates into.
# data-server-rendered / SSR markers are deliberately excluded (those mean the raw
# HTML is already populated, so no gap).
_MOUNT_MARKERS = (
    'id="root"', "id='root'",
    'id="app"', "id='app'",
    'id="__next"', "id='__next'",
    'id="__nuxt"', "id='__nuxt'",
    'ng-app', 'ng-version',
    'data-reactroot',
)

# Buckets for the raw/rendered main-text ratio (fraction of rendered content that a
# non-rendering crawler can already read from raw HTML). Lower ratio = bigger gap.
_RATIO_CRITICAL = 0.10
_RATIO_HIGH = 0.30
_RATIO_MEDIUM = 0.55

# Rendered main text must clear this length to be a trustworthy denominator; below
# it, byte noise (hydration attrs, whitespace) dominates and the ratio is unstable.
_MIN_RENDERED = 600

# Static-heuristic thresholds (only used when the render check was skipped).
_TINY_RAW_MAIN = 200          # normalized chars of raw main text
_MIN_SCRIPT_SRC = 3           # several external bundles
_BIG_INLINE_JS = 20000        # chars of inline script (one big bundle)

# TTFB / latency proxy thresholds (ms). web.dev "poor TTFB" is ~1800ms; AI text
# crawlers commonly enforce 1-5s timeouts with no retry, so >3000ms is high risk.
_LATENCY_HIGH_MS = 3000
_LATENCY_MEDIUM_MS = 1800


def best_html(p):
    """Prefer the rendered DOM when render succeeded, else the raw HTML."""
    if getattr(p, "render_status", None) == "ok" and getattr(p, "rendered_html", None):
        return p.rendered_html
    return p.raw_html or ""


def _first_h1(html):
    try:
        s = htmlutil.soup(html)
        h1 = s.find("h1")
        return htmlutil.norm_text(h1.get_text(" ")) if h1 else ""
    except Exception:
        return ""


def _short_url(p):
    return getattr(p, "final_url", None) or getattr(p, "url", "")


def _has_empty_mount(raw_html):
    """A framework mount marker is present in raw HTML (paired elsewhere with tiny
    raw main text to conclude the body is an empty shell)."""
    low = (raw_html or "").lower()
    return any(m in low for m in _MOUNT_MARKERS)


def _js_presence(raw_html):
    """(count of <script src>, total inline-script char length) — deterministic."""
    try:
        s = htmlutil.soup(raw_html)
    except Exception:
        return 0, 0
    src_count = 0
    inline_len = 0
    for tag in s.find_all("script"):
        if tag.get("src"):
            src_count += 1
        else:
            inline_len += len(tag.string or tag.get_text() or "")
    return src_count, inline_len


def check_js_render_gap(ctx, ok_pages):
    """Compare readable main-content text in raw HTML vs the rendered DOM.

    Mode A (render available): bucketed ratio of raw/rendered main text.
    Mode B (render skipped/error): static SPA heuristic (empty mount + tiny raw
    main text + heavy JS), lower confidence.
    """
    findings = []

    # ---- Mode A: measured raw-vs-rendered gap -------------------------------
    measured = []   # (ratio, page, missing_signal)
    for p in ok_pages:
        if getattr(p, "render_status", None) != "ok":
            continue
        rmain = getattr(p, "rendered_main_text", None)
        if not rmain:
            continue
        rendered = len(htmlutil.norm_text(rmain))
        if rendered <= _MIN_RENDERED:
            continue  # FP guard: rendered content too small to trust the ratio
        raw = len(htmlutil.norm_text(getattr(p, "raw_main_text", "") or ""))
        ratio = raw / rendered if rendered else 1.0
        if ratio >= _RATIO_MEDIUM:
            continue  # raw already substantial (SSR / hydration) -> no gap
        # Cite a concrete missing signal.
        raw_h1 = _first_h1(p.raw_html)
        rendered_h1 = _first_h1(p.rendered_html)
        if rendered_h1 and not raw_h1:
            missing = "H1 present in rendered DOM but absent from raw HTML"
        else:
            missing = "main-content text present in rendered DOM but absent from raw HTML"
        measured.append((ratio, p, missing))

    eligible_measured = sum(
        1 for p in ok_pages
        if getattr(p, "render_status", None) == "ok"
        and getattr(p, "rendered_main_text", None)
        and len(htmlutil.norm_text(p.rendered_main_text)) > _MIN_RENDERED
    )

    if measured:
        measured.sort(key=lambda t: t[0])   # worst (smallest) ratio first
        worst_ratio, worst_page, worst_missing = measured[0]
        if worst_ratio < _RATIO_CRITICAL:
            severity = "critical"
        elif worst_ratio < _RATIO_HIGH:
            severity = "high"
        else:
            severity = "medium"
        n, m = len(measured), max(eligible_measured, len(measured))
        pct = int(round(worst_ratio * 100))
        evidence = (
            f"{n}/{m} sampled pages expose <{_RATIO_MEDIUM:.0%} of their rendered "
            f"main text in raw HTML; worst page {_short_url(worst_page)} shows only "
            f"~{pct}% ({worst_missing})."
        )
        findings.append(make_finding(
            check="js-render-gap",
            title="Main content is client-rendered and invisible to non-rendering AI crawlers",
            severity=severity,
            half="both",
            evidence=evidence,
            fix=("Server-render or pre-render the primary content (SSR/SSG/hydration or "
                 "prerendering) so the H1 and main copy are present in the initial HTML "
                 "response, not injected by JavaScript after load."),
            mechanism=("AI text crawlers (GPTBot/ClaudeBot/PerplexityBot) execute zero "
                       "JavaScript; content painted only after JS runs is invisible to them "
                       "and also delays first paint for humans. Highest-leverage fix."),
            priority=severity,
            confidence="high",
            effort="high",
            location="js-render-gap::rendered-vs-raw",
            evidence_detail={
                "worst_ratio": round(worst_ratio, 3),
                "pages_with_gap": n,
                "pages_evaluated": m,
                "worst_page": _short_url(worst_page),
            },
        ))
        return findings  # measured evidence supersedes the heuristic

    # ---- Mode B: static SPA heuristic (render check skipped/error) ----------
    suspects = []
    eligible_static = 0
    for p in ok_pages:
        if getattr(p, "render_status", None) == "ok":
            continue  # render succeeded -> Mode A already covered it
        eligible_static += 1
        raw_main = len(htmlutil.norm_text(getattr(p, "raw_main_text", "") or ""))
        if raw_main >= _TINY_RAW_MAIN:
            continue
        if not _has_empty_mount(p.raw_html):
            continue
        src_count, inline_len = _js_presence(p.raw_html)
        if src_count < _MIN_SCRIPT_SRC and inline_len < _BIG_INLINE_JS:
            continue
        suspects.append((p, raw_main, src_count, inline_len))

    if suspects:
        n, m = len(suspects), max(eligible_static, len(suspects))
        severity = "high" if n >= 2 else "medium"
        worst = min(suspects, key=lambda t: t[1])
        wp, wmain, wsrc, winline = worst
        evidence = (
            f"{n}/{m} pages look likely client-side rendered (render check skipped — "
            f"install Playwright chromium to confirm): near-empty raw main text and an "
            f"empty framework mount with heavy JS. Worst page {_short_url(wp)} has "
            f"~{wmain} chars of raw main text, {wsrc} <script src> tags and "
            f"~{winline} chars of inline script."
        )
        findings.append(make_finding(
            check="js-render-gap",
            title="Pages appear client-side rendered (empty HTML shell) — likely invisible to AI crawlers",
            severity=severity,
            half="both",
            evidence=evidence,
            fix=("Confirm by rendering (install Playwright chromium), then server-render "
                 "or pre-render primary content so the initial HTML response is not an "
                 "empty mount awaiting JavaScript."),
            mechanism=("AI text crawlers execute zero JavaScript; an empty <div id=root> "
                       "shell that JS fills leaves crawlers with a blank page and slows "
                       "human first paint. This is a heuristic, not a measured gap."),
            priority=severity,
            confidence="medium",
            effort="high",
            location="js-render-gap::static-spa-heuristic",
            evidence_detail={
                "pages_suspect": n,
                "pages_evaluated": m,
                "worst_page": _short_url(wp),
                "worst_raw_main_chars": wmain,
            },
        ))
    return findings


def check_fetch_latency(ctx, ok_pages):
    """Single lab-sample TTFB/latency proxy from p.elapsed_ms on ok pages."""
    findings = []
    timed = [(p, p.elapsed_ms) for p in ok_pages if isinstance(getattr(p, "elapsed_ms", None), int)]
    if not timed:
        return findings

    slow = [(p, ms) for p, ms in timed if ms > _LATENCY_MEDIUM_MS]
    if not slow:
        return findings

    worst_page, worst_ms = max(slow, key=lambda t: t[1])
    severity = "high" if worst_ms > _LATENCY_HIGH_MS else "medium"
    n, m = len(slow), len(timed)
    evidence = (
        f"{n}/{m} pages exceeded the {_LATENCY_MEDIUM_MS}ms latency proxy (single lab "
        f"sample); worst was {worst_ms}ms on {_short_url(worst_page)}. Lab proxy only — "
        f"one measurement from one location, at risk of crawler timeout, not proof of a "
        f"dropped request."
    )
    findings.append(make_finding(
        check="fetch-latency-ttfb",
        title="Slow response latency risks AI-crawler timeouts",
        severity=severity,
        half="both",
        evidence=evidence,
        fix=("Reduce server response time / TTFB (caching, CDN, faster origin) so pages "
             "return well under ~1-2s; AI crawlers enforce short timeouts (~1-5s) with no "
             "retry, so a slow first byte can drop the page from their index entirely."),
        mechanism=("AI crawlers enforce tight fetch timeouts (~1-5s) with no retry; a slow "
                   "first byte can cause the page to be skipped and never indexed."),
        priority=severity,
        confidence="low",
        effort="medium",
        location="fetch-latency-ttfb::worst-case",
        evidence_detail={
            "worst_ms": worst_ms,
            "pages_slow": n,
            "pages_timed": m,
            "worst_page": _short_url(worst_page),
            "caveat": "single lab sample, one geo; not a field measurement",
        },
    ))
    return findings


def run(ctx):
    ok_pages = [p for p in getattr(ctx, "pages", []) if getattr(p, "ok", False)]
    if not ok_pages:
        return []
    findings = []
    for fn in (check_js_render_gap, check_fetch_latency):
        try:
            findings.extend(fn(ctx, ok_pages))
        except Exception:
            continue
    return findings


if __name__ == '__main__':
    import json
    from common import fetch
    ctx = fetch.build_context(sys.argv[1])
    print(json.dumps(run(ctx), indent=2, default=str))
    ctx.close()
