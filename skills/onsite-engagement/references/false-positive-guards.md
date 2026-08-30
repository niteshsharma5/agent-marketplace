#### False-positive guards

The engagement checks are intentionally conservative: a wrong "your popup blocks
content" or "your contrast fails" claim erodes trust in the whole report. Every
check follows the guards below and, when it cannot decide confidently, lowers
severity/confidence or skips entirely.

#### General
- Only pages with `fetch_class == 'ok'` produce content findings. Blocked,
  transient, or not-found pages mean we could not read the page, not that the
  content is missing.
- `best_html(p)` prefers rendered HTML when `render_status == 'ok'`, else raw
  HTML. Rendered fields may be None; always guard.
- Aggregate: one finding per issue-type with `N/M pages` prevalence, never one
  finding per page.

#### Page weight / render-blocking
- Media-heavy sites are legitimately large; we report risk factors versus HTTP
  Archive medians, not a hard byte cap.
- `async`, `defer`, and `type=module` scripts do NOT block parsing and are
  excluded from the sync-script count.
- Missing compression is only flagged on text/html responses.

#### Images
- Skip images that already have `srcset` or a `<picture>` ancestor.
- Skip vector/inline SVG and `data:` URIs (no responsive/lazy benefit).
- NEVER recommend `loading=lazy` on the hero / LCP / first image; lazy-loading
  the above-fold image delays LCP. Only below-fold images (index >= 1) are
  considered.

#### Layout stability (CLS)
- Check BOTH the HTML dimension attributes AND inline CSS (`aspect-ratio`,
  `width`, `height`) before flagging undimensioned media. Either reserves space.
- Only `@font-face` rules that omit `font-display` are flagged.

#### Mobile viewport / zoom
- `maximum-scale >= 2` (e.g. 5) is fine and never flagged.
- "Missing viewport tag" and "zoom disabled" are reported as separate findings
  with separate severities/locations.

#### Contrast / legibility / tap targets
- Compute contrast ONLY when the background resolves to a single OPAQUE color.
  Skip when the background is an image, gradient, `rgba()`/`hsla()` with alpha
  < 1, `currentColor`, `transparent`, `inherit`, or otherwise unresolved.
- `hsl()`/`hsla()` are deliberately not resolved (kept out to keep FP low).
- Large-text threshold (3:1) applies only when font-size >= 24px, or >= 18.66px
  with bold weight; otherwise the 4.5:1 normal threshold is used.
- EXCLUDE inline text links from tap-target sizing rules (WCAG 2.5.8 exempts
  inline links). This skill does not flag tap-target size at all, because it
  cannot resolve rendered box geometry confidently from markup.
- If colors cannot be resolved confidently, SKIP. A missed low-contrast pair is
  far cheaper than a false accusation.

#### Interstitials / autoplay
- DOWN-RANK / skip overlays whose text or class matches consent, cookie, GDPR,
  CCPA, privacy, age-gate, sign-in/login, or newsletter/subscribe patterns.
  These are the categories Google explicitly permits.
- Small, dismissible banners are fine; only full-size/backdrop, high-z-index,
  fixed/absolute overlays that cover content are flagged.
- Muted autoplay is low/info and not escalated; only UNMUTED autoplay is flagged.

#### Mixed content / HTTPS
- Inspect ONLY resource-loading attributes (`src`/`href` on
  script/link/iframe/img/video/source/audio). Plain `<a href>` navigation links
  are NOT mixed content and are ignored.
- Ignore protocol-relative (`//host/...`) and `data:` URIs.
- Active mixed content (script/link/iframe) ranks above passive (img/video).

#### Broken internal links
- Internal (same-origin) links only.
- 404/410 = broken. 401/403/405/429, timeouts, `capped`, and
  `robots_disallowed` are INCONCLUSIVE and skipped (not reported).
- Already-sampled URLs are skipped to conserve the shared extra-fetch budget.
- This check is network-dependent; the evidence says so.

#### Readability
- Needs >= 100 words (the Flesch helper returns None otherwise -> skip).
- English-oriented heuristic. Report is kept soft (low severity) and always
  carries the caveat that legal/technical/medical copy is legitimately dense.

#### Orientation (landmarks / skip link / value prop)
- Accept `role="main"`, not just the `<main>` element.
- Advisory (low severity) on very short or single-purpose pages.
- Hero-text baked into an image is a known limitation and is noted in evidence.
