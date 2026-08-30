#### Answer-readiness & schema-type fit — agent reasoning checklist

You are reasoning over `out/context.json` after the deterministic scripts have run. The scripts already caught missing schema, broken required props, schema-vs-visible mismatches, orientation problems, and missing alt. Your job is the two judgments a regex cannot make: is the content quotable, and when schema is absent or wrong, what is the right type. Reason only from the evidence in `context.json`. Never re-fetch, never invent facts about the site, and never flag a page you cannot ground in a concrete quote or field from the evidence pack.

Each page in `context.json` gives you: `url`, `fetch_class`, `title`, `meta_description`, `lang`, `canonical`, `h1[]`, `headings[]`, `jsonld:[{types[],name?,headline?}]`, `images_total`, `images_missing_alt`, `has_viewport`, and `main_text_excerpt`. Only reason about pages with `fetch_class == 'ok'`; skip the rest silently.

#### Check 1 — Answer-readiness

The question: if a RAG system retrieved this page, could it lift a short, self-contained, correct passage and cite it? A page is answer-ready when a reader who sees only one paragraph or one heading-plus-answer still gets a true, complete fact.

Read `main_text_excerpt` and `headings[]` and judge these together, not as a checklist to fail one by one:
- **Self-contained sentences** — does a factual claim stand on its own, or does it depend on unstated earlier context ("as mentioned above", "it does this too", pronouns with no nearby referent)?
- **Question-style headings** — headings phrased as the question a user would ask ("How do I return an item?", "What's included?") let a retriever match query to answer. Their absence is a weakness only when the page is clearly Q&A or informational.
- **Lists / tables / structure** — steps, specs, comparisons, and hours read far better as lists or tables than as one dense paragraph. Note when structured facts are trapped in prose.
- **Answer front-loaded** — the answer should come in the first sentence or two under a heading, not after three paragraphs of preamble. Roughly the first third of content earns most citations, so a buried answer is a real loss.

Write an answer-readiness finding only when the page is genuinely weak on the axes that matter for its role, and you can quote the specific weak passage from `main_text_excerpt`. Use `check: "answer-readiness"`, `half: "discoverability"`. Severity is usually `low` or `medium` — reserve `medium` for a page whose whole purpose is to answer a question (support, FAQ, docs, product detail) yet buries or fragments the answer. The fix in `suggested_action.summary` must name the actual page and the actual content: e.g. "Add a question-style H2 'What is your return window?' directly above the existing 30-day sentence on /returns, and lead with the answer." Not a template.

Conservative guards (do not flag when any of these hold):
- The page already has question-style headings AND front-loaded answers AND some list/table structure. It is answer-ready; leave it alone.
- `main_text_excerpt` is short (well under ~200 words). Thin pages are handled by other checks; do not punish brevity here.
- The page is legitimately narrative by design — an about story, a manifesto, an essay, a landing hero. Narrative prose is a valid choice, not a defect. At most a `low` observation, and only if a genuinely quotable fact is buried inside it.
- You would be guessing. If you cannot point to a concrete passage in the evidence, do not write the finding. Quotability is subjective; stay conservative and let a clean page pass clean.

#### Check 2 — Schema-type fit

The scripts flag *absence* of schema on type-warranting pages and *invalid required props* on present types. They do not tell the site *which* type it should have used, and they do not catch a page carrying a plausible-but-wrong type. That judgment is yours.

Only act when the deterministic layer already signalled a gap for this page (missing schema where the role warrants it, or a present type that does not fit), or when the evidence makes an obvious type clearly correct and clearly absent. Then infer the right `@type` from the page's real role, reading `title`, `h1[]`, `headings[]`, `main_text_excerpt`, and existing `jsonld[].types`:

- **Landing / home page** — `WebSite` + `Organization` (brand identity), and `FAQPage` if the page answers common questions. Not `Article`.
- **Recipe page** (ingredients + steps) — `Recipe`. Not generic `Article`.
- **Editorial / blog / news** — `Article` or `NewsArticle` with `headline`, `author`, `datePublished`.
- **Product detail** — `Product` with `offers.price` + `offers.priceCurrency`.
- **Q&A / support / help** — `FAQPage` with `mainEntity`.
- **Local business / contact** — `Organization` or a `LocalBusiness` subtype with `name`, `address`, contact info.
- **Recorded how-to steps** — `HowTo` when the page is procedural but not a recipe.

Write a schema-type-fit finding with `check: "schema-type-fit"`, `half: "discoverability"`. State the page's role from the evidence, the type it should carry, and the key props that type needs, all specific to this page. Example `evidence`: "/blog/spring-guide has an author byline and a March 2026 date in main_text_excerpt but no Article JSON-LD (jsonld is empty)." Example fix: "Add Article JSON-LD to /blog/spring-guide with headline from the H1, author 'Jane Doe', and datePublished 2026-03-14."

Conservative guards (do not flag when any of these hold):
- Correct-and-valid schema is already present for the page's role. The scripts validated the props; do not second-guess a passing type.
- The page role is genuinely ambiguous from the evidence. Pick a type only when the evidence makes the role clear; otherwise stay silent rather than guess.
- The "missing" type would not fit the page's actual purpose. Do not demand `Product` schema on a category listing or `Article` on a bare contact page.
- A valid `FAQPage` (or any correct type) that simply would not win rich results is fine. Rich-result eligibility is not the bar; correct extractable facts are.

#### Severity and confidence defaults

Keep this layer honest. Answer-readiness and schema-type-fit findings are advisory improvements, not outages — default `severity` to `low`, step up to `medium` only when the page's core job is answering or being cited and it clearly fails. Set `suggested_action.confidence` to `high` only when the evidence is unambiguous (an explicit byline with no Article schema, a buried answer you can quote); use `medium` or `low` when you are inferring role or quotability. A clean, answer-ready, correctly-typed page should produce no finding at all.
