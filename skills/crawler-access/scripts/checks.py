"""crawler-access checks: can an AI CITATION crawler get in at all (discoverability step 1).

Read-only, deterministic. Emits findings ONLY via common.contract.make_finding.
Each check is wrapped so one failure never aborts run().
"""
import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
from common.contract import make_finding
from common import htmlutil

from urllib.parse import urljoin, urlparse

try:
    from protego import Protego
except Exception:  # pragma: no cover - protego is a declared dep
    Protego = None

# --- User-agent token maps (last verified 2026-08-30; see references/ai-user-agents.md) ---
# Citation/search bots: a Disallow here removes the brand from that AI assistant's answers.
# These are the live answer/search fetchers — NOT bulk training/corpus crawlers.
CITATION_BOTS = sorted([
    "OAI-SearchBot", "ChatGPT-User", "PerplexityBot", "Perplexity-User",
    "Claude-User", "Claude-SearchBot", "Googlebot", "Bingbot",
    "Applebot", "Amazonbot", "DuckDuckBot",
])
# Training/bulk-corpus bots: blocking these is a LEGITIMATE opt-out, never flagged as a
# problem. ClaudeBot and Meta-ExternalAgent are training/bulk crawlers, so a site that
# blocks them while allowing the citation bots above is opting out of training, not
# removing itself from AI answers.
TRAINING_BOTS = sorted([
    "GPTBot", "Google-Extended", "CCBot", "anthropic-ai",
    "ClaudeBot", "meta-externalagent",
    "Applebot-Extended", "Bytespider",
])

# Utility routes that legitimately carry noindex / are not "content" pages.
_UTILITY_HINTS = (
    "login", "signin", "sign-in", "logout", "signout", "register",
    "cart", "checkout", "basket", "wishlist", "account", "/search",
    "password", "reset", "/admin",
)

_MIN_CONTENT_WORDS = 50          # homepage "real content" bar
_SOFT_404_MAX_WORDS = 50         # a 200 with fewer main-text words is suspiciously thin


# ----------------------------------------------------------------------------- helpers
def best_html(p):
    """Rendered HTML when a render succeeded, else the raw HTML."""
    if getattr(p, "render_status", None) == "ok" and p.rendered_html:
        return p.rendered_html
    return p.raw_html or ""


def _home_url(home):
    return (home.final_url or home.url) if home else ""


def _home_is_public(home):
    """Homepage must be a real, readable 200 before we flag anything content-related."""
    if home is None or not home.ok:
        return False
    words = htmlutil.word_count(home.raw_main_text or home.raw_text or "")
    return words >= _MIN_CONTENT_WORDS


def _get_parser(ctx):
    """Prefer the pre-parsed robots parser; otherwise parse ctx.robots.raw ourselves."""
    parser = getattr(ctx.robots, "parser", None)
    if parser is not None:
        return parser
    raw = getattr(ctx.robots, "raw", "") or ""
    if raw and Protego is not None:
        try:
            return Protego.parse(raw)
        except Exception:
            return None
    return None


def _named_agents(raw):
    """Set of lowercased user-agent tokens that have their own named group (excludes '*')."""
    agents = set()
    for line in (raw or "").splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        if key.strip().lower() == "user-agent":
            tok = val.strip().lower()
            if tok and tok != "*":
                agents.add(tok)
    return agents


def _content_pages(ctx):
    """ok pages that look like content routes (skip login/cart/checkout/search utilities)."""
    out = []
    for p in ctx.pages:
        if not p.ok:
            continue
        low = (p.final_url or p.url or "").lower()
        if any(h in low for h in _UTILITY_HINTS):
            continue
        out.append(p)
    return out


def _has_noindex_meta(html):
    """(has_noindex, directive_string) from meta name=robots|googlebot content."""
    try:
        s = htmlutil.soup(html)
    except Exception:
        return False, ""
    for tag in s.find_all("meta"):
        name = (tag.get("name") or "").strip().lower()
        if name in ("robots", "googlebot"):
            content = (tag.get("content") or "").lower()
            if "noindex" in content:
                return True, "meta name=%s content=%r" % (name, content.strip())
    return False, ""


def _xrobots_noindex(headers):
    val = (headers or {}).get("x-robots-tag", "") or ""
    if "noindex" in val.lower():
        return True, "X-Robots-Tag: %s" % val.strip()
    return False, ""


# ----------------------------------------------------------------------------- checks
def _check_citation_bot_block(ctx, findings):
    parser = _get_parser(ctx)
    if parser is None or not getattr(ctx.robots, "exists", False):
        return
    if not _home_is_public(ctx.home):
        return
    url = _home_url(ctx.home)
    blocked = []
    verdicts = []
    for bot in CITATION_BOTS:
        try:
            allowed = parser.can_fetch(url, bot)
        except Exception:
            continue
        verdicts.append("%s=%s" % (bot, "Allow" if allowed else "DISALLOW"))
        if not allowed:
            blocked.append(bot)
    if not blocked:
        return
    evidence = ("%d/%d citation bots Disallowed for homepage %s: %s. Resolved verdicts: %s"
                % (len(blocked), len(CITATION_BOTS), url, ", ".join(blocked),
                   "; ".join(verdicts)))
    findings.append(make_finding(
        check="robots-citation-bot-block",
        title="robots.txt blocks AI citation crawlers from the homepage",
        severity="critical",
        half="discoverability",
        evidence=evidence,
        fix=("Remove or narrow the Disallow rules for these citation/search bots in "
             "robots.txt (%s). Keep training-only opt-outs if desired, but allow the "
             "crawlers that power AI answers to reach the homepage." % ", ".join(blocked)),
        mechanism=("AI assistants retrieve live pages via citation crawlers; a Disallow "
                   "for one of these bots removes the brand from that assistant's answers."),
        priority="critical", confidence="high", effort="low",
        location="robots.txt#citation-bots",
        evidence_detail={"blocked_bots": blocked, "resolved_verdicts": verdicts,
                         "homepage": url},
    ))


def _check_wildcard_catchall(ctx, findings):
    parser = _get_parser(ctx)
    raw = getattr(ctx.robots, "raw", "") or ""
    if parser is None or not getattr(ctx.robots, "exists", False) or not raw:
        return
    if not _home_is_public(ctx.home):
        return
    url = _home_url(ctx.home)
    # A UA token that cannot match any named group -> exercises the '*' catchall group.
    probe_token = "BrandAuditCatchallProbe"
    try:
        catchall_allows = parser.can_fetch(url, probe_token)
    except Exception:
        return
    if catchall_allows:
        return  # the '*' group does not block the homepage
    named = _named_agents(raw)
    inheriting = [b for b in CITATION_BOTS if b.lower() not in named]
    if not inheriting:
        return  # every citation bot has its own group; catchall doesn't reach them
    evidence = ("User-agent:* blocks homepage %s (probe verdict=DISALLOW) and %d/%d "
                "citation bots have no named group, so they inherit the catch-all block: %s"
                % (url, len(inheriting), len(CITATION_BOTS), ", ".join(inheriting)))
    findings.append(make_finding(
        check="robots-wildcard-catchall",
        title="Wildcard robots.txt Disallow catches AI citation crawlers with no named group",
        severity="critical",
        half="discoverability",
        evidence=evidence,
        fix=("The homepage is publicly served but User-agent:* Disallow:/ blocks every "
             "unnamed bot. Add explicit Allow groups for the citation crawlers (%s) or "
             "loosen the wildcard Disallow." % ", ".join(inheriting)),
        mechanism=("Under RFC 9309 a bot with no named group inherits the User-agent:* "
                   "group; a catch-all Disallow:/ therefore blocks these citation crawlers "
                   "even though no rule names them."),
        priority="critical", confidence="high", effort="low",
        location="robots.txt#wildcard-catchall",
        evidence_detail={"inheriting_bots": inheriting, "named_groups": sorted(named),
                         "homepage": url},
    ))


def _check_waf_ua_block(ctx, findings):
    home = ctx.home
    if home is None:
        return
    # Only probe when our bot UA actually failed to read the homepage as a block.
    if home.fetch_class != "blocked":
        return
    try:
        from common import fetch
    except Exception:
        return
    url = home.final_url or home.url
    browser = ctx.fetch_as(url, fetch.BROWSER_UA)
    bot = ctx.fetch_as(url, fetch.AUDIT_UA)
    if browser.get("fetch_class") == "capped" or bot.get("fetch_class") == "capped":
        return
    if browser.get("fetch_class") == "ok" and bot.get("fetch_class") == "blocked":
        evidence = ("Same-IP probe of %s: browser UA -> HTTP %s (%s) but bot UA -> HTTP %s "
                    "(%s). 1/1 pages show a UA-conditional block."
                    % (url, browser.get("status"), browser.get("fetch_class"),
                       bot.get("status"), bot.get("fetch_class")))
        findings.append(make_finding(
            check="waf-ua-block-probe",
            title="Possible WAF/CDN User-Agent block on the homepage",
            severity="high",
            half="discoverability",
            evidence=evidence,
            fix=("Verify against server/CDN logs and, ideally, from a vendor IP range. If a "
                 "WAF/CDN rule is blocking crawler User-Agents, allowlist the citation bots "
                 "(and their published IP ranges) at the edge."),
            mechanism=("robots.txt is advisory; a CDN/WAF can block requests by User-Agent "
                       "even when robots allows them, so the crawler never reads the page. "
                       "Our audit runs from a non-vendor IP, so this is a signal to verify, "
                       "not a definitive verdict."),
            priority="high", confidence="low", effort="medium",
            location="waf-ua-block-probe#homepage",
            evidence_detail={"browser": browser, "bot": bot, "homepage": url,
                             "note": "possible; verify with logs / vendor IP ranges"},
        ))


def _check_indexability_directives(ctx, findings):
    pages = _content_pages(ctx)
    if not pages:
        return
    total = len(pages)
    noindex_pages = []       # (url, source-string)
    conflict_pages = []      # (url, source-string) noindex + robots-disallowed
    for p in pages:
        url = p.final_url or p.url
        has_meta, meta_src = _has_noindex_meta(best_html(p))
        has_hdr, hdr_src = _xrobots_noindex(p.headers)
        if not (has_meta or has_hdr):
            continue
        src = " and ".join([s for s in (hdr_src if has_hdr else "",
                                        meta_src if has_meta else "") if s])
        noindex_pages.append((url, src))
        disallowed = False
        try:
            disallowed = not ctx.allowed(p.url)
        except Exception:
            disallowed = False
        if disallowed:
            conflict_pages.append((url, src))
    if noindex_pages:
        listing = "; ".join("%s (%s)" % (u, s) for u, s in noindex_pages)
        findings.append(make_finding(
            check="indexability-directives",
            title="noindex directive on content pages",
            severity="high",
            half="discoverability",
            evidence=("%d/%d content pages carry a noindex directive: %s"
                      % (len(noindex_pages), total, listing)),
            fix=("Remove the noindex directive (meta tag or X-Robots-Tag header) from "
                 "pages you want cited. noindex tells search/citation engines to drop the "
                 "page from their index entirely."),
            mechanism=("A noindex directive instructs indexing engines to exclude the page, "
                       "so it cannot surface as a citation source even if crawling is allowed."),
            priority="high", confidence="high", effort="low",
            location="indexability-directives#noindex",
            evidence_detail={"pages": [{"url": u, "source": s} for u, s in noindex_pages],
                             "considered_pages": total},
        ))
    if conflict_pages:
        listing = "; ".join("%s (%s)" % (u, s) for u, s in conflict_pages)
        findings.append(make_finding(
            check="indexability-directives",
            title="Self-cancelling conflict: robots-Disallowed page also serves noindex",
            severity="high",
            half="discoverability",
            evidence=("%d/%d content pages are both robots-Disallowed and serve noindex: %s"
                      % (len(conflict_pages), total, listing)),
            fix=("Pick one intent. If the page should be dropped, allow crawling so engines "
                 "can SEE the noindex; if it should be cited, remove both the Disallow and "
                 "the noindex."),
            mechanism=("A robots Disallow stops the crawler from ever reading the page, so it "
                       "never sees the noindex tag; the two directives cancel each other and "
                       "the outcome is undefined across engines."),
            priority="high", confidence="medium", effort="low",
            location="indexability-directives#noindex-disallow-conflict",
            evidence_detail={"pages": [{"url": u, "source": s} for u, s in conflict_pages],
                             "considered_pages": total},
        ))


def _check_status_redirect_canonical(ctx, findings):
    pages = [p for p in ctx.pages if p is not None]
    if not pages:
        return
    total = len(pages)

    long_chains = []     # (url, hops)
    non_200 = []         # (url, status/class)
    soft_404 = []        # (url, words)

    for p in pages:
        url = p.final_url or p.url
        chain = p.redirect_chain or []
        hops = max(0, len(chain) - 1)
        if hops > 2:
            long_chains.append((p.url, hops))
        if p.status is not None and not (200 <= int(p.status) < 300):
            non_200.append((url, "HTTP %s (%s)" % (p.status, p.fetch_class)))
        if not p.ok:
            continue
        # NOTE: a rel=canonical pointing at a different host is NOT flagged. Pointing the
        # canonical at the production domain is standard, legitimate practice on staging
        # hosts, CDNs, and syndicated copies; "fixing" it would break the site. Only
        # genuinely-broken signals (long chains, non-200, soft-404) are reported here.
        # soft-404: 200 but thin body AND not-found phrasing
        text = (p.raw_main_text or p.raw_text or "")
        words = htmlutil.word_count(text)
        low = text.lower()
        if words < _SOFT_404_MAX_WORDS and ("not found" in low or "404" in low or
                                            "page doesn" in low):
            soft_404.append((url, words))

    if long_chains:
        listing = "; ".join("%s (%d hops)" % (u, h) for u, h in long_chains)
        findings.append(make_finding(
            check="http-status-redirect-canonical-integrity",
            title="Redirect chains longer than 2 hops",
            severity="medium", half="both",
            evidence=("%d/%d sampled URLs redirect through more than 2 hops: %s"
                      % (len(long_chains), total, listing)),
            fix="Collapse multi-hop redirects to a single 301 to the final URL.",
            mechanism=("Each extra redirect adds latency and a chance for a crawler to drop "
                       "the request before it reaches the real content."),
            priority="medium", confidence="high", effort="low",
            location="http-integrity#redirect-chains",
            evidence_detail={"chains": [{"url": u, "hops": h} for u, h in long_chains]},
        ))
    if non_200:
        listing = "; ".join("%s -> %s" % (u, s) for u, s in non_200)
        findings.append(make_finding(
            check="http-status-redirect-canonical-integrity",
            title="Non-200 final status on sampled URLs",
            severity="medium", half="both",
            evidence=("%d/%d sampled URLs return a non-200 final status: %s"
                      % (len(non_200), total, listing)),
            fix="Investigate and restore 200 responses, or remove the dead links pointing here.",
            mechanism=("A crawler that hits a non-200 final response gets no content to index "
                       "or cite from that URL."),
            priority="medium", confidence="medium", effort="medium",
            location="http-integrity#non-200",
            evidence_detail={"urls": [{"url": u, "status": s} for u, s in non_200]},
        ))
    if soft_404:
        listing = "; ".join("%s (%d words)" % (u, w) for u, w in soft_404)
        findings.append(make_finding(
            check="http-status-redirect-canonical-integrity",
            title="Possible soft-404 (200 status with not-found content)",
            severity="medium", half="both",
            evidence=("%d/%d sampled pages return HTTP 200 but have very little text and "
                      "not-found phrasing: %s" % (len(soft_404), total, listing)),
            fix=("Return a real 404/410 for missing pages so crawlers don't index empty "
                 "not-found shells as real content."),
            mechanism=("A 200 on a not-found page (soft-404) wastes crawl budget and can put "
                       "empty pages into the index instead of real content."),
            priority="medium", confidence="low", effort="medium",
            location="http-integrity#soft-404",
            evidence_detail={"pages": [{"url": u, "words": w} for u, w in soft_404]},
        ))


def _check_discovery_infra(ctx, findings):
    home = ctx.home
    if not _home_is_public(home):
        return
    robots_sitemaps = list(getattr(ctx.robots, "sitemaps", []) or [])
    sitemap_ok = False
    sitemap_url = ctx.site + "/sitemap.xml"
    if robots_sitemaps:
        sitemap_ok = True
    else:
        res = ctx.fetch_extra(sitemap_url, "get")
        sitemap_ok = res.get("fetch_class") == "ok"
    if not sitemap_ok:
        findings.append(make_finding(
            check="discovery-infra-sitemap-orphan-llmstxt",
            title="No sitemap discoverable (no robots Sitemap directive and /sitemap.xml missing)",
            severity="low", half="discoverability",
            evidence=("robots.txt lists 0 Sitemap directives and %s did not return 200. "
                      "1/1 site checked." % sitemap_url),
            fix=("Publish a sitemap.xml and reference it with a Sitemap: directive in "
                 "robots.txt so crawlers can enumerate URLs beyond homepage links."),
            mechanism=("A sitemap helps crawlers find pages that aren't reachable through "
                       "on-page links; small sites can rely on internal links, so this is "
                       "low severity."),
            priority="low", confidence="medium", effort="low",
            location="discovery-infra#no-sitemap",
            evidence_detail={"robots_sitemaps": robots_sitemaps, "sitemap_url": sitemap_url},
        ))

    # NOTE: the absence of /llms.txt is deliberately NOT emitted as a finding. llms.txt is an
    # emerging, non-standard convention that no crawler requires, so flagging its absence (even
    # informationally) is pure noise. If the site owner wants to adopt it, that lives as a
    # proactive suggestion in references/, not as an audit finding.


def _check_blocked_render_assets(ctx, findings):
    parser = _get_parser(ctx)
    raw = getattr(ctx.robots, "raw", "") or ""
    home = ctx.home
    if parser is None or not raw or not _home_is_public(home):
        return
    base = home.final_url or home.url
    try:
        s = htmlutil.soup(best_html(home))
    except Exception:
        return
    asset_urls = []
    for link in s.find_all("link", attrs={"rel": True}):
        rels = link.get("rel")
        rels = rels if isinstance(rels, list) else [rels]
        if any(str(r).lower() == "stylesheet" for r in rels) and link.get("href"):
            asset_urls.append(urljoin(base, link["href"].strip()))
    for tag in s.find_all("script", src=True):
        asset_urls.append(urljoin(base, tag["src"].strip()))
    # Keep only same-origin render-critical assets, deduped and sorted for determinism.
    site_host = urlparse(ctx.site).netloc.lower()
    same = sorted({u for u in asset_urls
                   if urlparse(u).netloc.lower() == site_host
                   and urlparse(u).path.lower().split("?")[0].endswith((".css", ".js"))})
    if not same:
        return
    blocked = []
    for u in same:
        try:
            if not parser.can_fetch(u, "Googlebot"):
                blocked.append(u)
        except Exception:
            continue
    if not blocked:
        return
    sample = blocked[:5]
    evidence = ("%d/%d render-critical CSS/JS assets referenced by the homepage are "
                "Disallowed in robots.txt (tested as Googlebot): %s"
                % (len(blocked), len(same), ", ".join(sample)
                   + (" ..." if len(blocked) > len(sample) else "")))
    findings.append(make_finding(
        check="blocked-render-assets",
        title="robots.txt blocks CSS/JS the homepage needs to render",
        severity="medium", half="discoverability",
        evidence=evidence,
        fix=("Allow the CSS/JS paths in robots.txt so rendering engines can build the page. "
             "Blocked assets: %s" % ", ".join(sample)),
        mechanism=("AI surfaces that render pages (e.g. Google AI Overviews, Applebot) need "
                   "CSS/JS to see the real layout and content; blocking those assets breaks "
                   "the render. Text-only crawlers are unaffected."),
        priority="medium", confidence="medium", effort="low",
        location="blocked-render-assets#css-js",
        evidence_detail={"blocked_assets": blocked, "considered": len(same)},
    ))


# ----------------------------------------------------------------------------- entry
def run(ctx):
    findings = []
    if ctx is None or not getattr(ctx, "pages", None):
        return findings
    if not any(p.ok for p in ctx.pages):
        return findings
    for check in (
        _check_citation_bot_block,
        _check_wildcard_catchall,
        _check_waf_ua_block,
        _check_indexability_directives,
        _check_status_redirect_canonical,
        _check_discovery_infra,
        _check_blocked_render_assets,
    ):
        try:
            check(ctx, findings)
        except Exception:
            continue
    return findings


if __name__ == '__main__':
    import json
    from common import fetch
    ctx = fetch.build_context(sys.argv[1])
    print(json.dumps(run(ctx), indent=2, default=str))
    ctx.close()
