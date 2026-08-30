#### Entity disambiguation: anchors, sameAs, and the generic-name guard

This is the detail behind `org-entity-anchor-idgraph`, `sameas-resolvability`, and
`name-consistency-ambiguity`. Everything is deterministic and read-only. Schema is
read from rendered HTML when the render succeeded (`best_html`), because JSON-LD is
frequently JS-injected.

#### Why the anchor matters
An engine resolves the brand string to a knowledge-graph node BEFORE it evaluates
page content. With no stable anchor there is nothing to consolidate mentions onto,
and no brand-panel eligibility. So the Organization node is the first thing to get
right.

#### org-entity-anchor-idgraph
What counts as an Organization node: any JSON-LD node whose `@type` is in the org
set (Organization, Corporation, LocalBusiness and common subtypes / *Organization /
*Business). Detection uses the flattened `@graph` from `htmlutil.jsonld_blocks`.

Flag, one aggregated finding per issue-type:
- No anchor at all: zero Organization nodes on any sampled page -> high. This is
  the strongest signal; when it fires, the missing-fields finding is suppressed.
- Missing core fields: the primary Organization node lacks `name`, `url`, or `logo`.
  Report the per-field missing frequency. `foundingDate` is optional and never
  required.
- Fragmented graph: two or more Organization nodes on the SAME page with different
  `@id` values, or with different normalized `name` values. This is duplicate /
  conflicting anchoring, not mere presence.

False-positive guards:
- Parse the rendered DOM, not just raw HTML.
- A single-node page needs no `@id` cross-references — never flag a lone node for
  lacking `@id`.
- Detect DUPLICATES (conflicting nodes), not the absence of `@id` on a single node.

#### sameas-resolvability
`sameAs` is the merge instruction that tells engines "this brand is also that
Wikidata / Wikipedia / LinkedIn entity." A dead sameAs is worse than none because
it actively breaks the merge.

Collect all `Organization.sameAs` URLs (string or list), dedupe, sort. For each
http(s) URL that is NOT on the bot-blocked host allowlist (see
`corroboration.md`), issue one capped `ctx.fetch_extra(url, 'head')` and bucket:
- resolves: 2xx, or 3xx that lands on a 2xx final URL.
- broken: 404 / 410 only (`fetch_class == 'not_found'`).
- could-not-verify: blocked / transient / capped / robots — never counted as dead.

Flag:
- Broken (404/410) targets -> high. List up to five.
- sameAs present but NO Wikidata/Wikipedia URL among them -> high. (Total absence of
  sameAs is intentionally NOT reported here — that is the
  `offsite-corroboration-surface` finding, to avoid double-counting.)

False-positive guards:
- Bucket LinkedIn (often 999), Crunchbase, Instagram, Facebook, X/Twitter, TikTok,
  Pinterest, Threads, Glassdoor as "blocked, could not verify" — NEVER dead.
- Legitimate redirects are fine: http->https or a rename that still lands on 2xx
  counts as resolves. Compare the FINAL status, not the first hop.
- Extra fetches are globally capped (~30); iterate sorted and stop early.

#### name-consistency-ambiguity
Compare the brand string across `Organization.name`, `og:site_name`, the `<title>`
(first segment before a `|`/`-`/`:` separator), and the registrable domain label.
Normalize each: lowercase, strip punctuation, strip legal suffixes (Inc, Inc., LLC,
Ltd, Limited, Corp, Co, GmbH, PLC, LLP, Group, Holdings, ...).

Flag:
- Trivial mismatch -> low. Two or more DISTINCT normalized declared values
  (schema.name / og:site_name / title) that share no common token. Differences that
  are only a legal suffix normalize away and are not flagged.
- Generic-name mistaken-identity risk -> medium. The brand is a single alphabetic
  token that is a common dictionary word (see `GENERIC_WORDS` in the script) AND it
  co-occurs with NO sameAs and NO Wikidata/Wikipedia link.

False-positive guards:
- NEVER flag a dictionary-word name on its own. The generic-name finding requires
  co-occurring weak anchoring (no sameAs AND no wiki link). A well-anchored generic
  name (e.g. a brand with a Wikidata entry) is fine.
- The token match is intentionally a curated common-word set: false negatives are
  acceptable, false positives are not.
