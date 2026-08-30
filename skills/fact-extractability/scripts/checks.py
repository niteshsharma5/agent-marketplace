"""fact-extractability — can a machine pick out the specific correct FACT.

Discoverability step 3. Prefers rendered HTML (structured data is often injected
by JavaScript) and falls back to raw HTML. Every check is read-only, deterministic,
aggregates across the sampled pages with 'N/M pages' prevalence, and is wrapped so
one failure never aborts the whole run.
"""
import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
from common.contract import make_finding
from common import htmlutil

import re

_CURRENCY = re.compile(r"[$£€¥₹]")
_MONEY_RUN = re.compile(r"[0-9][0-9.,]*")

# Signals used to infer page role. Kept deterministic and conservative.
_PRODUCT_HINTS = ("add to cart", "add to bag", "add to basket", "buy now",
                  "buy it now", "in stock", "out of stock", "sku")
_ARTICLE_HINTS = ("min read", "minute read", "posted on", "published on", "by ")
_QUESTION_WORDS = ("how", "what", "why", "when", "where", "who", "which",
                   "can", "do", "does", "is", "are", "should", "will")
_DECORATIVE_HINTS = ("logo", "icon", "sprite", "spacer", "pixel", "tracking",
                     "background", "bg-", "avatar", "badge")

# JSON-LD page-type schemas that are themselves the appropriate, sufficient
# structured data for their page role. A page carrying any of these (author bio,
# about, contact, profile, collection/listing) already exposes its role to
# machines and must NOT be asked for Product or Article schema — even when it is
# wrapped in an <article> element with a timestamp.
_SELF_SUFFICIENT_TYPES = frozenset({
    "profilepage", "person", "aboutpage", "contactpage", "collectionpage",
})


def best_html(p):
    """Prefer rendered HTML when the render succeeded, else the raw HTML.
    Structured data and prices are frequently JS-injected, so rendered wins."""
    if getattr(p, "render_status", None) == "ok" and p.rendered_html:
        return p.rendered_html
    return p.raw_html or ""


def _ok_pages(ctx):
    return [p for p in ctx.pages if p.ok and (p.raw_html or best_html(p))]


def _prevalence(n, m):
    return f"{n}/{m} pages"


def _infer_role(html, text, present_types=None):
    """Deterministically classify a page as product, article, profile, or generic.

    When the page's JSON-LD already declares an appropriate page-type schema
    (ProfilePage/Person/AboutPage/ContactPage/CollectionPage), it is a
    profile/about/collection page, not an Article- or Product-needing page —
    even if it is wrapped in an <article> element carrying a <time> byline."""
    if present_types and (present_types & _SELF_SUFFICIENT_TYPES):
        return "profile"
    t = htmlutil.norm_text(text)
    s = htmlutil.soup(html)
    if any(h in t for h in _PRODUCT_HINTS):
        return "product"
    # A price near a cart/buy affordance is a strong product signal.
    if s.find(attrs={"itemprop": "price"}) is not None:
        return "product"
    if s.find("article") is not None or any(h in t for h in _ARTICLE_HINTS):
        # Only call it an article when there's a byline/date shape, not just any <article>.
        if s.find("time") is not None or "min read" in t or "published on" in t or "posted on" in t:
            return "article"
    return "generic"


def _get_prop(obj, *names):
    """Case-insensitive first-present property lookup on a JSON-LD dict."""
    if not isinstance(obj, dict):
        return None
    lower = {str(k).lower(): v for k, v in obj.items()}
    for n in names:
        v = lower.get(n.lower())
        if v not in (None, "", [], {}):
            return v
    return None


def _offers_prop(obj, prop):
    """Dig price / priceCurrency out of an offers node (dict or list)."""
    offers = _get_prop(obj, "offers")
    if offers is None:
        return None
    cand = offers[0] if isinstance(offers, list) and offers else offers
    if not isinstance(cand, dict):
        return None
    # priceSpecification wrapper is common.
    val = _get_prop(cand, prop)
    if val is None:
        spec = _get_prop(cand, "priceSpecification")
        if isinstance(spec, list) and spec:
            spec = spec[0]
        if isinstance(spec, dict):
            val = _get_prop(spec, prop)
    return val


# ---------------------------------------------------------------------------
# 1) jsonld-presence-validity
# ---------------------------------------------------------------------------
def _check_jsonld(ctx, pages):
    findings = []
    m = len(pages)
    role_pages = 0            # type-warranting pages (product/article)
    missing_schema = []       # role pages with no relevant JSON-LD at all
    invalid = {}              # type -> list of (url, missing props)

    required = {
        "organization": ["name", "url"],
        "product": ["name", "offers.price", "offers.priceCurrency"],
        "article": ["headline", "author", "datePublished"],
        "newsarticle": ["headline", "author", "datePublished"],
        "faqpage": ["mainEntity"],
        "breadcrumblist": ["itemListElement"],
    }

    for p in pages:
        html = best_html(p)
        blocks = htmlutil.jsonld_blocks(html)
        present_types = set()
        for b in blocks:
            present_types |= htmlutil.schema_types(b)

        role = _infer_role(html, p.rendered_text or p.raw_text or "", present_types)
        warrants = role in ("product", "article")
        if warrants:
            role_pages += 1
            relevant = (present_types & {"product"}) if role == "product" else \
                       (present_types & {"article", "newsarticle", "blogposting"})
            if not relevant:
                missing_schema.append(p.url)

        # Validate required props ONLY for types actually present.
        for b in blocks:
            for t in sorted(htmlutil.schema_types(b)):
                if t not in required:
                    continue
                miss = []
                for prop in required[t]:
                    if "." in prop:
                        _, sub = prop.split(".", 1)
                        if _offers_prop(b, sub) is None:
                            miss.append(prop)
                    else:
                        if _get_prop(b, prop) is None:
                            miss.append(prop)
                if miss:
                    invalid.setdefault(t, []).append((p.url, miss))

    if missing_schema:
        n = len(missing_schema)
        findings.append(make_finding(
            check="jsonld-presence-validity",
            title="Type-warranting pages have no JSON-LD structured data",
            severity="high", half="discoverability",
            evidence=(f"{_prevalence(n, m)} that read as product/article pages carry no "
                      f"matching schema.org JSON-LD (e.g. {missing_schema[0]}). "
                      f"Sampled {role_pages} type-warranting page(s)."),
            fix="Add schema.org JSON-LD (Product or Article) matching each page's role so "
                "engines can extract the fact, not guess it.",
            mechanism="Structured data lets machines read the exact fact (price, headline, "
                      "author) instead of inferring it from prose; missing schema forfeits rich results.",
            confidence="high", effort="medium", location="jsonld-missing",
            evidence_detail={"pages_missing": sorted(missing_schema), "role_pages": role_pages}))

    for t in sorted(invalid):
        rows = invalid[t]
        n = len({u for u, _ in rows})
        all_miss = sorted({p for _, ms in rows for p in ms})
        ex_url, ex_miss = rows[0]
        findings.append(make_finding(
            check="jsonld-presence-validity",
            title=f"{t} JSON-LD is missing required properties",
            severity="high", half="discoverability",
            evidence=(f"{_prevalence(n, m)} have a {t} block missing {', '.join(all_miss)} "
                      f"(e.g. {ex_url} lacks {', '.join(ex_miss)})."),
            fix=f"Populate the required {t} properties ({', '.join(required[t])}) so the block validates.",
            mechanism="Incomplete structured data is discarded or ignored by extractors, so the "
                      "fact you meant to expose never reaches the answer.",
            confidence="high", effort="low", location=f"jsonld-invalid::{t}",
            evidence_detail={"type": t, "missing_props": all_miss,
                             "pages": sorted({u for u, _ in rows})}))
    return findings


# ---------------------------------------------------------------------------
# 2) schema-visible-consistency
# ---------------------------------------------------------------------------
def _norm_money(v):
    if v is None:
        return None
    s = str(v)
    m = _MONEY_RUN.search(s.replace(",", ""))
    if not m:
        return None
    try:
        return round(float(m.group(0)), 2)
    except Exception:
        return None


def _check_consistency(ctx, pages):
    findings = []
    m = len(pages)
    price_mismatch = []
    name_mismatch = []

    for p in pages:
        html = best_html(p)
        vis = htmlutil.norm_text(htmlutil.visible_text(html))
        blocks = htmlutil.jsonld_blocks(html)
        for b in blocks:
            types = htmlutil.schema_types(b)
            if "product" not in types:
                continue
            # Default/selected variant only: the top-level Product node.
            price = _offers_prop(b, "price")
            np = _norm_money(price)
            if np is not None:
                vis_money = {round(float(x), 2) for x in
                             (_norm_money(tok) for tok in _MONEY_RUN.findall(vis.replace(",", "")))
                             if x is not None}
                if vis_money and np not in vis_money:
                    price_mismatch.append((p.url, np))

            name = _get_prop(b, "name")
            if isinstance(name, str) and name.strip():
                nn = htmlutil.norm_text(name)
                if len(nn) >= 4 and nn not in vis:
                    name_mismatch.append((p.url, name.strip()))
            break  # only the first/default Product node per page

    if price_mismatch:
        n = len(price_mismatch)
        ex = price_mismatch[0]
        findings.append(make_finding(
            check="schema-visible-consistency",
            title="JSON-LD price disagrees with the visible price",
            severity="high", half="discoverability",
            evidence=(f"{_prevalence(n, m)} expose a Product price in JSON-LD that does not appear "
                      f"in the visible page text (e.g. {ex[0]} declares {ex[1]} in schema)."),
            fix="Keep the structured-data price in sync with the rendered default-variant price so "
                "machines and shoppers see the same number.",
            mechanism="When schema and visible text disagree, extractors may surface a stale or wrong "
                      "price, eroding trust and risking a misquoted fact.",
            confidence="medium", effort="medium", location="consistency-price",
            evidence_detail={"pages": sorted({u for u, _ in price_mismatch})}))

    if name_mismatch:
        n = len(name_mismatch)
        ex = name_mismatch[0]
        findings.append(make_finding(
            check="schema-visible-consistency",
            title="JSON-LD product name is absent from visible text",
            severity="medium", half="discoverability",
            evidence=(f"{_prevalence(n, m)} declare a Product name in JSON-LD that is not present in "
                      f"the visible page (e.g. {ex[0]}: \"{ex[1]}\")."),
            fix="Match the schema name to the on-page product title (normalizing case/whitespace).",
            mechanism="A name mismatch signals the structured data was templated separately from the "
                      "content, so extractors can attach the wrong label to the fact.",
            confidence="medium", effort="low", location="consistency-name",
            evidence_detail={"pages": sorted({u for u, _ in name_mismatch})}))
    return findings


# ---------------------------------------------------------------------------
# 3) title-meta-heading-orientation
# ---------------------------------------------------------------------------
_GENERIC_TITLES = {"", "home", "untitled", "home page", "index",
                   "document", "new page", "welcome"}


def _check_orientation(ctx, pages):
    findings = []
    m = len(pages)
    bad_title = []
    no_meta_desc = []
    zero_h1 = []
    jump = []

    for p in pages:
        s = htmlutil.soup(best_html(p))
        title_tag = s.find("title")
        title = htmlutil.norm_text(title_tag.get_text()) if title_tag else ""
        if title in _GENERIC_TITLES:
            # Brand-only homepage title is legitimate; only flag truly generic/empty.
            if not (p.is_home and title not in ("", "home", "untitled")):
                bad_title.append((p.url, title or "(empty)"))

        md = s.find("meta", attrs={"name": re.compile("^description$", re.I)})
        if md is None or not (md.get("content") or "").strip():
            no_meta_desc.append(p.url)

        h1s = s.find_all("h1")
        if len(h1s) == 0:
            zero_h1.append(p.url)

        levels = []
        for h in s.find_all(re.compile("^h[1-6]$")):
            try:
                levels.append(int(h.name[1]))
            except Exception:
                continue
        prev = None
        for lv in levels:
            if prev is not None and lv > prev + 1:
                jump.append((p.url, prev, lv))
                break
            prev = lv

    if bad_title:
        n = len(bad_title)
        ex = bad_title[0]
        findings.append(make_finding(
            check="title-meta-heading-orientation",
            title="Missing or generic <title>",
            severity="medium", half="both",
            evidence=f"{_prevalence(n, m)} have a missing/generic title (e.g. {ex[0]}: \"{ex[1]}\").",
            fix="Give each page a specific, descriptive <title> naming the page's subject.",
            mechanism="The title is the strongest orientation signal an extractor has for what fact "
                      "the page answers; a generic title leaves it guessing.",
            confidence="high", effort="low", location="title-generic",
            evidence_detail={"pages": sorted({u for u, _ in bad_title})}))

    if zero_h1:
        n = len(zero_h1)
        findings.append(make_finding(
            check="title-meta-heading-orientation",
            title="Page has no <h1>",
            severity="medium", half="both",
            evidence=f"{_prevalence(n, m)} render zero <h1> elements (e.g. {sorted(zero_h1)[0]}).",
            fix="Add exactly one <h1> stating the page's primary subject.",
            mechanism="The h1 anchors the page's main topic for machine outlining; without it the "
                      "content hierarchy is ambiguous.",
            confidence="high", effort="low", location="h1-zero",
            evidence_detail={"pages": sorted(zero_h1)}))

    if jump:
        n = len(jump)
        ex = jump[0]
        findings.append(make_finding(
            check="title-meta-heading-orientation",
            title="Non-sequential heading levels",
            severity="low", half="both",
            evidence=f"{_prevalence(n, m)} skip heading levels (e.g. {ex[0]} jumps h{ex[1]}->h{ex[2]}).",
            fix="Keep headings sequential (no skipping levels) so the outline parses cleanly.",
            mechanism="Level jumps break the document outline machines build to locate a fact within a section.",
            confidence="medium", effort="low", location="heading-jump",
            evidence_detail={"pages": sorted({u for u, _, _ in jump})}))

    if no_meta_desc:
        n = len(no_meta_desc)
        findings.append(make_finding(
            check="title-meta-heading-orientation",
            title="Missing meta description",
            severity="low", half="discoverability",
            evidence=f"{_prevalence(n, m)} have no meta description (e.g. {sorted(no_meta_desc)[0]}).",
            fix="Add a concise meta description summarizing the page (soft advisory).",
            mechanism="A meta description gives extractors a ready-made summary snippet; its absence is "
                      "a minor, recoverable gap.",
            confidence="medium", effort="low", location="meta-desc-missing",
            evidence_detail={"pages": sorted(no_meta_desc)}))
    return findings


# ---------------------------------------------------------------------------
# 4) facts-in-images-alt
# ---------------------------------------------------------------------------
def _is_decorative_candidate(img):
    src = (img.get("src") or img.get("data-src") or "").lower()
    cls = " ".join(img.get("class") or []).lower()
    hint = src + " " + cls + " " + (img.get("id") or "").lower()
    if any(h in hint for h in _DECORATIVE_HINTS):
        return True
    # tiny declared dimensions -> likely spacer/pixel
    for dim in ("width", "height"):
        v = img.get(dim)
        try:
            if v is not None and int(re.sub(r"[^0-9]", "", str(v)) or "0") <= 2:
                return True
        except Exception:
            pass
    return False


def _check_images_alt(ctx, pages):
    findings = []
    m = len(pages)
    missing_alt_pages = []
    total_missing = 0
    image_only_pages = []

    for p in pages:
        html = best_html(p)
        s = htmlutil.soup(html)
        imgs = s.find_all("img")
        content_missing = 0
        for img in imgs:
            if _is_decorative_candidate(img):
                continue
            # alt="" is CORRECT for decorative -> only flag missing ATTRIBUTE.
            if not img.has_attr("alt"):
                content_missing += 1
        if content_missing:
            missing_alt_pages.append((p.url, content_missing))
            total_missing += content_missing

        # "one big image with little HTML text": few words + a large/hero image.
        text = htmlutil.norm_text(p.rendered_main_text or p.raw_main_text or
                                  htmlutil.main_text(html))
        wc = htmlutil.word_count(text)
        if wc < 50 and imgs:
            big = False
            for img in imgs:
                for dim in ("width", "height"):
                    v = img.get(dim)
                    try:
                        if v is not None and int(re.sub(r"[^0-9]", "", str(v)) or "0") >= 600:
                            big = True
                    except Exception:
                        pass
                cls = " ".join(img.get("class") or []).lower()
                if "hero" in cls or "banner" in cls:
                    big = True
            if big:
                image_only_pages.append((p.url, wc))

    if missing_alt_pages:
        n = len(missing_alt_pages)
        ex = missing_alt_pages[0]
        findings.append(make_finding(
            check="facts-in-images-alt",
            title="Content images missing an alt attribute",
            severity="medium", half="both",
            evidence=(f"{total_missing} content <img> across {_prevalence(n, m)} have no alt attribute "
                      f"(e.g. {ex[0]}: {ex[1]} image(s))."),
            fix="Add descriptive alt text to content images (leave alt=\"\" only for decorative ones).",
            mechanism="Text locked in an image with no alt is invisible to text extractors, so any fact "
                      "it carries is lost.",
            confidence="medium", effort="low", location="alt-missing",
            evidence_detail={"total_missing": total_missing,
                             "pages": sorted({u for u, _ in missing_alt_pages})}))

    if image_only_pages:
        n = len(image_only_pages)
        ex = image_only_pages[0]
        findings.append(make_finding(
            check="facts-in-images-alt",
            title="Page carries its message in an image, not HTML text",
            severity="medium", half="both",
            evidence=(f"{_prevalence(n, m)} have very little HTML text alongside a large/hero image "
                      f"(e.g. {ex[0]}: {ex[1]} words of main text)."),
            fix="Move the key message into real HTML text; keep imagery as a complement, not the carrier.",
            mechanism="When the fact lives only inside a rendered image, machines cannot read it without OCR "
                      "and usually skip the page.",
            confidence="medium", effort="medium", location="image-only",
            evidence_detail={"pages": sorted({u for u, _ in image_only_pages})}))
    return findings


# ---------------------------------------------------------------------------
# 5) canonical-lang-hreflang
# ---------------------------------------------------------------------------
def _is_absolute(u):
    return bool(re.match(r"^https?://", (u or "").strip(), re.I))


def _check_canonical_lang(ctx, pages):
    findings = []
    m = len(pages)
    missing_canonical = []
    relative_canonical = []
    missing_lang = []

    for p in pages:
        s = htmlutil.soup(best_html(p))
        link = s.find("link", attrs={"rel": re.compile("canonical", re.I)})
        href = (link.get("href") if link else "") or ""
        if link is None or not href.strip():
            missing_canonical.append(p.url)
        elif not _is_absolute(href):
            relative_canonical.append((p.url, href.strip()))

        html_tag = s.find("html")
        lang = (html_tag.get("lang") if html_tag else "") or ""
        if not lang.strip():
            missing_lang.append(p.url)

    if missing_canonical:
        n = len(missing_canonical)
        findings.append(make_finding(
            check="canonical-lang-hreflang",
            title="Missing rel=canonical",
            severity="medium", half="discoverability",
            evidence=f"{_prevalence(n, m)} have no rel=canonical link (e.g. {sorted(missing_canonical)[0]}).",
            fix="Add a self-referential absolute rel=canonical to each key page.",
            mechanism="Without a canonical, engines may index a duplicate URL and attribute the fact to the "
                      "wrong page, splitting authority.",
            confidence="medium", effort="low", location="canonical-missing",
            evidence_detail={"pages": sorted(missing_canonical)}))

    if relative_canonical:
        n = len(relative_canonical)
        ex = relative_canonical[0]
        findings.append(make_finding(
            check="canonical-lang-hreflang",
            title="Relative rel=canonical URL",
            severity="low", half="discoverability",
            evidence=f"{_prevalence(n, m)} use a relative canonical (e.g. {ex[0]}: \"{ex[1]}\").",
            fix="Use an absolute https:// URL in rel=canonical.",
            mechanism="Relative canonicals are error-prone and can resolve to the wrong host, misdirecting "
                      "which URL owns the fact.",
            confidence="medium", effort="low", location="canonical-relative",
            evidence_detail={"pages": sorted({u for u, _ in relative_canonical})}))

    if missing_lang:
        n = len(missing_lang)
        findings.append(make_finding(
            check="canonical-lang-hreflang",
            title="<html> missing lang attribute",
            severity="low", half="discoverability",
            evidence=f"{_prevalence(n, m)} have an <html> element with no lang attribute (e.g. {sorted(missing_lang)[0]}).",
            fix="Set a lang attribute on <html> (e.g. lang=\"en\").",
            mechanism="The lang attribute tells machines which language the fact is written in; its absence "
                      "hurts correct interpretation and localization.",
            confidence="high", effort="low", location="lang-missing",
            evidence_detail={"pages": sorted(missing_lang)}))
    return findings


# ---------------------------------------------------------------------------
# 6) answer-ready-extractability (informational, low)
# ---------------------------------------------------------------------------
def _has_question_heading(s):
    for h in s.find_all(re.compile("^h[1-6]$")):
        t = htmlutil.norm_text(h.get_text())
        if not t:
            continue
        if t.endswith("?"):
            return True
        first = t.split(" ", 1)[0]
        if first in _QUESTION_WORDS and len(t.split()) >= 3:
            return True
    return False


def _check_answer_ready(ctx, pages):
    findings = []
    m = len(pages)
    not_answer_ready = []

    for p in pages:
        html = best_html(p)
        s = htmlutil.soup(html)
        text = p.rendered_main_text or p.raw_main_text or htmlutil.main_text(html)
        if htmlutil.word_count(text) < 200:
            continue  # too short to judge; don't punish

        has_q = _has_question_heading(s)
        has_lists = bool(s.find(["ul", "ol", "table", "dl"]))
        blocks = htmlutil.jsonld_blocks(html)
        has_faq = any("faqpage" in htmlutil.schema_types(b) for b in blocks)

        # Are ALL substantial paragraphs long (>150 words)? If so, nothing is front-loaded.
        paras = [htmlutil.norm_text(pp.get_text()) for pp in s.find_all("p")]
        substantial = [t for t in paras if htmlutil.word_count(t) >= 40]
        all_long = bool(substantial) and all(htmlutil.word_count(t) > 150 for t in substantial)

        if not has_q and not has_lists and not has_faq and all_long:
            not_answer_ready.append(p.url)

    if not_answer_ready:
        n = len(not_answer_ready)
        findings.append(make_finding(
            check="answer-ready-extractability",
            title="Content is not answer-ready for extraction",
            severity="low", half="discoverability",
            evidence=(f"{_prevalence(n, m)} have no question-style headings, lists/tables, or FAQ, and "
                      f"consist only of long (>150-word) blocks (e.g. {sorted(not_answer_ready)[0]})."),
            fix="Add question-style headings, short front-loaded answers, and lists/tables where facts are "
                "enumerable (informational nudge, not a failure).",
            mechanism="RAG lifts self-contained short passages under question-style headings; ~44% of "
                      "citations come from the first ~30% of content, so front-loaded answers get quoted.",
            confidence="low", effort="medium", location="answer-ready",
            evidence_detail={"pages": sorted(not_answer_ready)}))
    return findings


# ---------------------------------------------------------------------------
def run(ctx):
    pages = _ok_pages(ctx)
    if not pages:
        return []
    findings = []
    for fn in (_check_jsonld, _check_consistency, _check_orientation,
               _check_images_alt, _check_canonical_lang, _check_answer_ready):
        try:
            findings.extend(fn(ctx, pages) or [])
        except Exception:
            continue
    return findings


if __name__ == '__main__':
    import json
    from common import fetch
    ctx = fetch.build_context(sys.argv[1])
    print(json.dumps(run(ctx), indent=2, default=str))
    ctx.close()
