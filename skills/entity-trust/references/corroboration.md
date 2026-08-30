#### Corroboration, freshness, E-E-A-T, and the bot-blocked-host allowlist

Detail behind `freshness-signals`, `author-eeat-contact-citations`, and
`offsite-corroboration-surface`, plus the shared host allowlist used when bucketing
sameAs. All checks are deterministic and read-only.

#### Bot-blocked-host allowlist (used by sameAs bucketing)
These hosts routinely challenge or 999/403 an automated HEAD from a datacenter IP.
A non-2xx from any of them is NOT evidence the profile is dead — bucket as
"could not verify," never "broken":

linkedin.com, crunchbase.com, instagram.com, facebook.com / fb.com, x.com /
twitter.com, tiktok.com, pinterest.com, threads.net, glassdoor.com.

Only 404 / 410 from a NON-allowlisted host counts as a broken sameAs target.

#### freshness-signals (both halves)
Recency-sensitive engines discount stale pages, and a human reads an old copyright
year as abandonment. A read-only fetch CANNOT prove gaming — report only OBSERVABLE
mismatch or clear age. Read the rendered DOM (dates are often JS-injected) and use
`datetime.date.today().year` as the current year.

Signals compared:
- schema `dateModified` (parse the year).
- visible "updated / last modified" date in the rendered text.
- footer copyright year — parse the UPPER bound of a range (2019-2024 -> 2024) and
  take the newest across pages.
- response `Last-Modified` header year.

Flag:
- Stale copyright -> medium. Newest footer copyright year is >= 2 years behind the
  current year.
- Conflicting date signals -> medium. On a content page, the distinct set of years
  from {dateModified, visible-updated, Last-Modified} spans >= 1 year.
- Schema-only staleness -> low. `dateModified` is >= 2 years behind current, when no
  outright mismatch was found.

False-positive guards:
- Gate mismatch/staleness to content page types (article/WebPage schema, or main
  content > 300 words). Skip thin nav/utility pages.
- Normalize date formats and ignore timezone noise; compare YEARS, not timestamps.
- Copyright staleness is footer-wide, so it aggregates across all sampled pages.

#### author-eeat-contact-citations (discoverability)
Machine-readable E-E-A-T, gated to ARTICLE-type pages (article / newsarticle /
blogposting / techarticle / ...). Corporate and product pages need no byline and
are not flagged.

Flag:
- Author missing or generic -> medium. Schema `author` is absent or a placeholder
  (admin / administrator / editor / author).
- Schema author disagrees with the visible byline -> medium. A visible "By <Name>"
  differs from the JSON-LD author after name normalization.
- Long-form with zero citations -> low. Main content >= 600 words AND zero outbound
  external links. Count PRESENCE of outbound links, not their quality.
- LocalBusiness NAP incomplete -> medium. Only for local/physical business types:
  `name`, `address`, or `telephone` missing across the local-business nodes.

False-positive guards:
- Bylines only on article content; never require them on corporate/product pages.
- Normalize name forms before comparing author vs byline.
- NAP applies only to LocalBusiness (and subtypes), never to a plain Organization.

#### offsite-corroboration-surface (discoverability, low confidence)
Roughly 85% of AI brand mentions come from third-party pages, so a brand with zero
off-site surface is structurally hard to cite. This check reports the ABSENCE of any
off-site identity surface as the firm signal — presence only means a surface exists,
not that it is strong.

Flag -> medium, confidence low: NO sameAs anywhere, AND no footer/social profile
links (LinkedIn, X/Twitter, Facebook, Instagram, YouTube, GitHub, TikTok, ...), AND
no Wikipedia/Wikidata link on any sampled page.

False-positive guards:
- Report ABSENCE only; do not claim quality from mere presence.
- NEVER run a live web search — that is non-deterministic and out of scope.
- Small / local brands legitimately lack Wikipedia, so keep confidence LOW.
