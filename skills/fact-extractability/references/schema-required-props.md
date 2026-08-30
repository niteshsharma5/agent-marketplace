#### Schema required props & page-role inference

Reference for `jsonld-presence-validity` and `schema-visible-consistency`. All parsing uses `htmlutil.jsonld_blocks(best_html(p))`, which flattens `@graph` and tolerates one bad block. `best_html(p)` = rendered HTML when `render_status == 'ok'`, else raw HTML.

#### Inferring page role
Only require schema on pages whose role warrants it. Role is inferred deterministically from `best_html` + visible text:

- **product** — visible text contains a buy/cart affordance (`add to cart`, `add to bag`, `buy now`, `in stock`, `sku`) OR an `itemprop="price"` node exists.
- **article** — an `<article>` element or article phrasing (`min read`, `published on`, `posted on`, byline `by `) AND a byline/date shape (`<time>` present, or a publish-date phrase). A bare `<article>` tag alone is not enough.
- **generic / home / contact** — everything else. Never demand schema here.

Only **product** and **article** pages are treated as "type-warranting". A page missing the matching schema is flagged; generic/contact/simple pages are never flagged for absence.

#### Required properties (validated ONLY for @types actually present)
Validate props only for types that appear in the JSON-LD. A present type with all required props passes even if it would not win rich results.

| @type | Required props |
|---|---|
| Organization | `name`, `url` |
| Product | `name`, `offers.price`, `offers.priceCurrency` |
| Article / NewsArticle | `headline`, `author`, `datePublished` |
| FAQPage | `mainEntity` |
| BreadcrumbList | `itemListElement` |

Notes:
- `offers` may be a dict or a list; the first offer is used. `price` / `priceCurrency` may sit inside a `priceSpecification` wrapper — both locations are checked.
- Property lookup is case-insensitive; empty string / empty list / empty dict count as missing.

#### schema-visible-consistency
When a `Product` block carries `price` or `name`, compare against the visible rendered text of the **default/selected variant only** (the first/top-level Product node per page):

- **Price** — normalize by stripping currency symbols, thousands separators, and whitespace; compare the numeric value against numbers found in visible text. Flag only when the schema price appears nowhere in the visible text.
- **Name** — normalize case/whitespace; flag when a name of length >= 4 is absent from visible text.

#### False-positive guards
- Never demand schema on simple/contact/home pages.
- A valid `FAQPage` passes even if it loses rich results.
- Only validate props for types that are present; do not require a type just because the page role suggests it (absence is handled separately, per role).
- Per-variant pricing legitimately differs — compare the default variant only; do not iterate every offer.
- Always normalize currency symbols, separators, whitespace, and case before comparing.
- `htmlutil` already tolerates one malformed JSON-LD block; do not fail the whole page on a single bad block.
