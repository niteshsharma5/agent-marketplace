#### Entity ambiguity and E-E-A-T quality: an agent reasoning checklist

This is the agent-facing half of entity-trust. It runs after the deterministic
scripts, reasoning over `out/context.json` only — no re-fetch, no web search. The
scripts already flag mechanical problems (missing anchor, dead sameAs, missing
byline). Your job is the two judgments a script cannot make: is the brand
genuinely ambiguous, and do the visible trust signals actually convey expertise?

#### Ground rules
- Reason ONLY from evidence in `context.json`. Never assert a fact about the brand
  the pack does not contain. If you cannot see it, you cannot flag it.
- Stay conservative. A clean, well-described site should produce zero agent
  findings here. A low-severity honest observation is fine; manufacturing a
  problem on a clear page is not.
- Every finding needs a concrete, site-specific fix — quote the actual brand name,
  the actual thin page, the actual competing meaning. No templates.
- Skip pages whose `fetch_class` is not a success and pages with an empty
  `main_text_excerpt`; you cannot judge what you cannot read.

Evidence to read per page: `title`, `meta_description`, `h1`, `headings`,
`main_text_excerpt`, and the `jsonld` org `name`. Across pages, note whether an
About-type or Contact-type page exists (URL path or a heading naming it).

#### Check 1 — entity ambiguity / mistaken identity
The question: if an engine reads this brand string cold, could it confuse the
brand with a different well-known entity, and does the site do the disambiguation
work itself?

Look for a collision risk first. A name carries collision risk when it is a common
dictionary word, a common personal name, a place, or a term already owned by a
famous company or product (think a generic noun used as a brand). Then check
whether the site resolves that risk on its own: a clear statement of WHO or WHAT
the brand is — an About or value statement, and distinctive descriptors (the
industry, the offering, the location or audience) that pin the meaning down.

Flag (severity low–medium, half `discoverability`, `confidence` medium at most)
only when BOTH hold:
- The name plausibly collides with another well-known entity or meaning, AND
- The pack shows no clear self-disambiguation: the homepage / About text does not
  say plainly what the brand is, `meta_description` and `h1` are generic or empty,
  and there are no distinctive descriptors that fix the meaning.

Write the fix around what is actually missing — e.g. "Add one sentence to the
homepage hero and the Organization `description` stating that <Brand> is a
<specific category> for <specific audience> in <place>, since the name also reads
as <the competing meaning>."

False-positive guards — do NOT flag when any of these is true:
- The brand is already well anchored (the deterministic layer found a resolvable
  Wikidata/Wikipedia sameAs, or `name-consistency-ambiguity` did not fire). A
  well-anchored generic name is fine; the engine already has a node to bind to.
- The name is distinctive (a coined or compound word unlikely to collide) AND an
  About page or a clear value statement is present. A distinctive name with an
  About page is fine — do not flag it.
- The site clearly states its category and audience in the homepage text,
  `meta_description`, or `h1`, even if the name is common. Self-disambiguation
  present means no finding.
- You are only guessing at a collision. If you cannot name the specific competing
  entity or meaning from general knowledge, do not flag.

#### Check 2 — E-E-A-T quality (beyond mere presence)
The scripts confirm whether a byline, author node, or NAP EXISTS. This check asks
whether the visible experience, expertise, authoritativeness, and accountability
signals actually mean something to a reader or an engine.

Look at the evidence pack for: whether an About page conveys real substance (who
runs the brand, credentials, history) versus boilerplate; whether article-type
pages name a real, identifiable author rather than a role; whether a Contact
surface gives a reachable, accountable identity (a real address, a named team)
versus a bare form. Judge substance, not just the tag being present.

Flag (severity low–medium, half `discoverability`, `confidence` medium at most)
only when the visible signals are genuinely thin for what the site is:
- An About page exists but says nothing verifiable about who is behind the brand or
  why they are credible — pure marketing copy with no expertise or accountability.
- Article / expertise content carries no identifiable, accountable author (a role
  or brand name where a person's expertise should stand behind the claims).
- A brand that makes expertise or advice claims offers no way to verify who is
  accountable (no meaningful About, no real contact identity).

Write the fix around the specific gap — e.g. "The About page describes the mission
but never says who runs <Brand> or their background; add founder/team names and
relevant credentials so an engine can attribute expertise."

False-positive guards — do NOT flag when any of these is true:
- The signal is genuinely present and substantive. A real About page with named
  people and background, or articles with credited authors, is fine.
- The page type does not owe a byline. Corporate, product, and marketing pages
  need no author — never demand E-E-A-T signals a page type does not require.
- The site is a small or local business whose About + contact is proportionate to
  its size. Do not hold a plumber's site to a publisher's authorship bar.
- The deterministic `author-eeat-contact-citations` finding already covers the same
  gap mechanically. Add an agent finding only when your judgment sees a QUALITY
  problem the script's presence check missed; do not restate the script.

#### Writing findings
Append each conclusion to `out/agent_findings.json` (a JSON list) in the shared
shape: `check`, `title`, `severity`, `half`, `evidence` (a concrete string quoting
what you saw), `mechanism` (why it hurts AI attribution), `location`, and
`suggested_action` {`summary`, `priority`, `effort`, `confidence`}. Suggested
`check` slugs: `entity-ambiguity-disambiguation` and `eeat-quality-thin`. Keep
`confidence` at medium or low — these are judgments, not measurements. If the site
is clean on both questions, write nothing; an empty agent layer is a valid result.
