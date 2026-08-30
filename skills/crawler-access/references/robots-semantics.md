# robots.txt Semantics + Per-Check Guards

How the checks reason about robots.txt (RFC 9309), plus the thresholds and false-positive guards for each check. Protego implements the resolution below; this file explains what it does so the findings are defensible.

## Per-UA group resolution (RFC 9309)
1. A crawler picks exactly ONE group: the group whose `User-agent` product token best matches its own token. Matching is case-insensitive and prefix-based on the product token (e.g. a `User-agent: Google` group matches `Googlebot`).
2. If no named group matches, the crawler uses the `User-agent: *` group.
3. A crawler NEVER merges rules from `*` into its named group. If `Googlebot` has its own group, the `*` rules do not apply to it.
4. Within the selected group, the **most specific (longest) matching path rule wins**, and `Allow` beats `Disallow` when the match lengths tie.

### Worked example A — named group escapes the wildcard
```
User-agent: *
Disallow: /

User-agent: Googlebot
Allow: /
```
`Googlebot` selects its own group → Allowed. `PerplexityBot` (no named group) falls to `*` → Disallowed. The `robots-wildcard-catchall` check flags every citation bot with no named group here.

### Worked example B — longest match wins
```
User-agent: *
Disallow: /
Allow: /blog/
```
`/blog/post` → the `Allow: /blog/` rule is longer than `Disallow: /` → Allowed. `/about` → only `Disallow: /` matches → Disallowed. This is why the checks resolve verdicts via `can_fetch(url, token)` per URL, never by string-grepping for `Disallow: /`.

### Worked example C — citation Disallow
```
User-agent: PerplexityBot
Disallow: /
```
`PerplexityBot` → Disallowed. `robots-citation-bot-block` flags this (citation bot). An identical block on `GPTBot` (training-only) is NOT flagged.

## Per-check thresholds + guards

### robots-citation-bot-block (critical)
- For each citation token, `can_fetch(homepage, token)`; flag the tokens that resolve to Disallow.
- Aggregate into ONE finding listing every blocked citation bot + the full resolved verdict list.
- Guards: robots.txt must exist; homepage must be 200 with >= 50 main-text words; only citation tokens count; training-only Disallows are never a defect.

### robots-wildcard-catchall (critical)
- Probe the `*` group with a token that can match no named group (`BrandAuditCatchallProbe`). If it resolves to Disallow on the homepage AND >= 1 citation bot has no named group, flag those inheriting bots.
- Guards: homepage clearly public (200 + real content); report the mechanism (inheritance), not intent; don't flag deliberately private/staging sites.

### waf-ua-block-probe (high, confidence low)
- Only when the homepage `fetch_class == 'blocked'` under our bot UA. Compare `fetch_as(browser UA)` vs `fetch_as(bot UA)` from the SAME client/IP.
- Flag only when browser UA → ok but bot UA → blocked.
- Guards: our non-vendor IP may itself be blocked as a spoofer, so frame as "possible, verify with logs / vendor IP ranges", never definitive. Skip if either probe is capped.

### indexability-directives (high)
- Scope: homepage + primary content pages; skip login/cart/checkout/search/account/admin utility routes by path.
- Flag `noindex` in `meta name=robots|googlebot` (parsed from best_html) OR in the `X-Robots-Tag` header. State which one.
- Also flag the self-cancel conflict: page is robots-Disallowed AND serves noindex (the crawler can't read the tag it's told to obey).

### http-status-redirect-canonical-integrity (medium)
- Redirect chains: a single http→https or trailing-slash redirect (chain length 2 / 1 hop) is normal. Flag only > 2 hops.
- Non-200 finals on sampled pages.
- Soft-404: HTTP 200 but < 50 main-text words AND "not found" / "404" / "page doesn't" phrasing.
- Do NOT flag a `rel=canonical` merely because its host differs from the fetched origin. Pointing the canonical at the production domain is standard, legitimate practice on staging hosts, CDNs, and syndicated copies, and "fixing" it would break the site. Only a canonical that is malformed or whose target is verifiably broken (404) would count — never host-difference alone.

### discovery-infra-sitemap-orphan-llmstxt (low)
- Flag only when there is no `Sitemap:` directive in robots AND `/sitemap.xml` does not return 200. Small sites legitimately rely on internal links → keep low.
- Do NOT emit any finding for the absence of `/llms.txt`. It is an emerging, non-standard convention that no crawler requires, so flagging its absence (even informationally) is noise. Adopting llms.txt is only a proactive nice-to-have suggestion, never an audit finding.

### blocked-render-assets (medium)
- Collect same-origin `.css` / `.js` referenced by the homepage; test each with `can_fetch(asset, 'Googlebot')`. Flag only assets that actually resolve to Disallow.
- Scope impact to rendering engines (Google AI Overviews / Applebot); text-only crawlers are unaffected.
