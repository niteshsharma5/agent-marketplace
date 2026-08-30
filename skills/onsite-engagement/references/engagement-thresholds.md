#### Engagement thresholds and provenance

Bands and numbers the checks in `scripts/checks.py` compare against. These are
risk-factor heuristics computed from a single HTML bundle (no subresource
fetching), so they flag likely problems rather than measured field metrics.

#### Core Web Vitals (web.dev good / needs-work / poor)
| Metric | Good | Needs work | Poor |
|---|---|---|---|
| LCP (Largest Contentful Paint) | <= 2.5s | 2.5s-4.0s | > 4.0s |
| CLS (Cumulative Layout Shift) | <= 0.1 | 0.1-0.25 | > 0.25 |
| INP (Interaction to Next Paint) | <= 200ms | 200ms-500ms | > 500ms |

We cannot measure these directly from static HTML. Instead we flag the markup
patterns that most reliably degrade them (render-blocking resources -> LCP;
undimensioned media and late fonts -> CLS).

#### HTTP Archive medians (used as "vs median" language)
- Compressed HTML document transfer: ~30 KB (mobile). Our uncompressed-markup
  risk trigger is 150 KB of raw HTML bytes.
- Render-blocking resources: a typical page ships only a few. Trigger: >= 4
  synchronous `<script>` in `<head>` (async/defer/`type=module` excluded), or
  >= 4 `<link rel=stylesheet>` in `<head>`.
- Compression: text HTML should carry `Content-Encoding: gzip|br|deflate|zstd`.
  Missing on a text/html response is a transfer-size risk factor.

#### Images
- Large intrinsic dimension without responsive variants: `<img>` declaring
  width or height >= 1000px and no `srcset` / no `<picture>` ancestor.
- Below-fold lazy-load: content images after the first (hero/LCP) image should
  carry `loading="lazy"`. The first image is never flagged.

#### Layout stability (CLS)
- `<img>` / `<video>` / `<iframe>` must reserve space: either width AND height
  attributes, or an inline `aspect-ratio` / explicit `width`/`height` in CSS.
- `@font-face` rules should set `font-display` (e.g. `swap`) to avoid invisible
  or swapping text that shifts layout.

#### Mobile viewport / zoom (WCAG 1.4.4 Resize Text)
- A `<meta name="viewport">` must exist; `width=device-width, initial-scale=1`
  is the baseline.
- Pinch-zoom must not be disabled: `user-scalable=no` or `maximum-scale < 2`
  fails WCAG 1.4.4. `maximum-scale >= 2` (e.g. 5) is acceptable.

#### Contrast / legibility (WCAG 1.4.3 / 1.4.4)
- Normal body text: contrast ratio >= 4.5:1.
- Large text (>= 24px, or >= 18.66px bold): >= 3:1.
- Dominant body font-size: >= 16px recommended; below a 12px absolute floor is
  flagged.
- Contrast is computed with the standard WCAG relative-luminance formula, only
  when both foreground and an OPAQUE solid background resolve confidently.

#### Interstitials / autoplay
- On-load overlays that cover main content (fixed/absolute + high z-index +
  full-size/backdrop) hurt engagement and are penalized by Google, EXCEPT
  legally permitted consent/cookie/age/login prompts.
- Autoplaying `<video>` must be `muted`; unmuted autoplay is the escalated case.

#### Mixed content / HTTPS
- The origin should be HTTPS. On HTTPS pages, subresource URLs (`src`/`href` on
  script/link/iframe/img/video/source/audio) must not use `http://`. Active
  mixed content (script/link/iframe) is blocked by browsers and ranks above
  passive (img/video), which is downgraded.

#### Readability (English Flesch Reading Ease)
- < 45 = college+ reading level (flagged, with a domain caveat).
- Needs >= 100 words and >= 3 sentences or the helper returns None (skip).
- Wall-of-text: any paragraph > 150 words in main content with no lists or
  subheadings.

#### Orientation (landmarks / skip link / value prop)
- A `<main>` or `role="main"` landmark should exist.
- A skip-to-content link (`<a href="#...">` whose text contains "skip").
- Above-fold value proposition: an `<h1>` plus a nearby descriptive paragraph
  (>= 10 words). Value-prop text baked into a hero image is a known blind spot.
