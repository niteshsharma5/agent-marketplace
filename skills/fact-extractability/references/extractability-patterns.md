#### Extractability patterns, non-text traps & alt-text rule

Reference for `title-meta-heading-orientation`, `facts-in-images-alt`, `canonical-lang-hreflang`, and `answer-ready-extractability`.

#### Title / meta / heading orientation
- **Generic/missing title** (medium, both) — flag when the normalized `<title>` is empty or in {home, home page, index, untitled, document, new page, welcome}. A brand-only homepage title is legitimate: on the home page, only truly empty/`home`/`untitled` titles are flagged.
- **Missing meta description** (low, discoverability, soft) — advisory only; length is never a hard failure.
- **Zero H1** (medium, both) — the real issue. Multiple H1 is valid HTML5, so it is at most low/info and is **not** flagged here.
- **Heading jumps** (low, both) — flag the first non-sequential jump (e.g. h2 -> h4). Sequential outlines let machines locate a fact within a section.

#### Facts in images — decorative vs content alt rule
- Count a content `<img>` as a problem only when the **alt attribute is entirely absent**. `alt=""` is CORRECT for decorative images and always passes.
- Ignore likely decorative/non-content images before counting: `src`/`class`/`id` hints of logo, icon, sprite, spacer, pixel, tracking, background, `bg-`, avatar, badge; and images with declared width/height <= 2px (tracking pixels / spacers).
- Report a count plus `N/M pages` prevalence, never one finding per image.

#### Image-only page trap
Flag a page (medium, both) when it has very little HTML text (< 50 words of main text) alongside a large or hero image — a large declared dimension (>= 600px) or a `hero`/`banner` class. The message lives in pixels, so text extractors miss the fact.

#### OCR (optional, OFF by default)
OCR is not run by default. If ever enabled, it must be inside a `try/except` importing `pytesseract` + `PIL` (the tesseract binary may be absent) and only when image bytes are already in hand. Do **not** fetch image bytes solely to OCR — it blows the time budget.

#### Canonical / lang / hreflang
- **Missing canonical** (medium, discoverability) — no `rel=canonical` link, or empty href, on a key page.
- **Relative canonical** (low, discoverability) — canonical href that is not an absolute `https?://` URL.
- **Missing `<html lang>`** (low, discoverability) — no lang attribute on `<html>`.
- **hreflang reciprocity** — only relevant on multilingual sites; single-language sites need `lang` but NOT hreflang, so it is not flagged here.
- FP guard: cross-domain and pagination canonicals can be intentional — verify shared content before treating them as errors; this check only flags absence and relative form, not intentional cross-domain targets.

#### Answer-ready extractability (informational, low)
An informational nudge, never a hard failure. Flag a page only when ALL of these hold:
- Main text has >= 200 words (too-short pages are skipped, not punished).
- No question-style headings (heading ending in `?`, or starting with how/what/why/when/where/who/which/can/do/does/is/are/should/will with >= 3 words).
- No lists or tables (`ul`, `ol`, `table`, `dl`).
- No `FAQPage` JSON-LD.
- Every substantial paragraph (>= 40 words) is long (> 150 words), so nothing is front-loaded.

Mechanism: RAG lifts self-contained short passages under question-style headings; ~44% of citations come from the first ~30% of content, so front-loaded answers get quoted. FP guard: quotability is subjective — keep this low/informational and do not punish legitimately narrative pages.
