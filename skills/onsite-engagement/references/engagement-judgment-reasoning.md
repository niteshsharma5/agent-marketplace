#### Engagement judgment reasoning (agent-facing)

The deterministic scripts already cover the mechanical risk factors (speed,
images, CLS, viewport, contrast, interstitials, mixed content, broken links,
readability). Do not repeat any of those here. This checklist covers the two
judgments a markup threshold cannot settle: whether the page orients a first
time visitor, and whether it delivers what it promises.

Reason only from `out/context.json`. Never re-fetch and never assert a fact that
is not visible in the evidence pack. Every finding you write must name the
specific page and quote the specific evidence that made you conclude it. Write
site-specific fixes, not templates. When the evidence is thin or ambiguous,
lower severity and confidence or write nothing. A clean page should produce zero
findings from this skill.

#### Fields you reason over (per page in `context.json`)
- `url`, `title`, `meta_description`
- `h1` (list), `headings` (ordered outline), `main_text_excerpt`
- `jsonld` types/names (for what the page claims to be)
- `lang`, `canonical` (context only)

Only reason over pages you can actually read. If a page has no `title`, no
`h1`, and an empty `main_text_excerpt`, that is a render or fetch limitation,
not a content problem; skip it rather than flagging emptiness.

#### Check 1 — value-proposition clarity and orientation
Ask: reading only the `title`, `h1`, first few `headings`, and the opening of
`main_text_excerpt`, could a first time visitor say in one sentence what this
page or brand is, who it is for, and what the obvious next step is?

Signals of a genuine problem (need more than one before flagging):
- The `h1` is generic boilerplate (`Welcome`, `Home`, the bare brand name) and
  nothing in the excerpt or early headings states what is offered.
- `title` / `h1` / excerpt point in three different directions, so the primary
  offer is unclear.
- No discernible next action or orientation anywhere in the readable text on
  what is clearly a landing or entry page.
- The excerpt opens with filler (company history, mission platitudes) and the
  concrete offer never surfaces in the sampled text.

Do NOT flag when:
- A clear hero exists: the `h1` plus the first line or two of the excerpt
  already convey the offer and audience. This is the good case; leave it alone.
- The page is a legitimate deep or single-purpose page (an article, a policy, a
  login, a form). Judge orientation against what that page type is for, not a
  homepage standard.
- The value proposition is plausibly carried in a hero image or video. The
  evidence pack is text-only, so absence of text is not proof of absence of
  orientation. At most note it as a low-severity, low-confidence observation.
- Wording is merely not to your taste. Unclear is a problem; imperfect is not.

Severity guide: a homepage or primary landing page a visitor genuinely cannot
parse is `high`; a secondary page with weak but present orientation is `low`.

#### Check 2 — content answers intent
Ask: does the readable content deliver on the promise its `title` and `headings`
make, or is the answer buried, missing, or off-topic?

Signals of a genuine problem:
- A `title`/`h1` that poses a clear question or promises specifics (pricing,
  how-to, comparison, specs), while the `main_text_excerpt` and headings never
  begin to address it.
- Headings advertise sections whose promised substance is absent from the
  sampled text.
- The lead is padded with preamble so the thing the visitor came for is pushed
  far down or out of the sample entirely.

Do NOT flag when:
- The excerpt is a truncated sample. It is an opening slice, not the whole page.
  Only flag when the promised answer should appear up front and clearly does
  not, not merely because the sample ended before it.
- The page is a hub/index whose job is to route, not to answer in body copy.
- The mismatch is minor or arguable. Reserve this check for a real gap between
  what the page promises and what it visibly delivers.

Severity guide: a page that promises a specific answer and delivers none is
`medium`; a lead buried under preamble on an otherwise on-topic page is `low`.

#### Writing the finding
Append to `out/agent_findings.json` (a JSON list). Each entry:
- `check`: `value-prop-orientation` or `content-answers-intent`
- `title`: short, specific to the page
- `severity`: `critical` | `high` | `medium` | `low` (use the guides above;
  most honest findings here are `low` or `medium`)
- `half`: `engagement`
- `evidence`: quote the concrete `context.json` values (the actual `h1`,
  heading, or excerpt text) that led to the conclusion, with the page URL
- `mechanism`: why this makes visitors bounce or fail to orient
- `location`: the page URL (and the element, e.g. the `h1`)
- `suggested_action`: `{ summary, priority, effort, confidence }` — a
  site-specific rewrite or restructure, not a generic tip. Lower `confidence`
  when the judgment rests on a text-only sample.

If neither check finds a genuine weakness on the sampled pages, write nothing.
An empty agent contribution on a clean site is the correct outcome.
