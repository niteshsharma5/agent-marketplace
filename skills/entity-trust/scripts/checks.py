"""entity-trust checks: does the assistant trust and attribute a fact to the RIGHT brand.

Read-only, deterministic. Prefers rendered HTML for schema (JSON-LD is often
JS-injected). Every finding is built via make_finding and aggregated across the
sampled pages with an 'N/M pages' prevalence string.
"""
import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
from common.contract import make_finding
from common import htmlutil

import re
import datetime
from urllib.parse import urlparse

# --- constants (deterministic; sort any iteration) -------------------------

ORG_TYPES = {
    "organization", "corporation", "localbusiness", "onlinestore",
    "onlinebusiness", "ngo", "governmentorganization", "educationalorganization",
    "collegeoruniversity", "nonprofit", "nonprofitorganization",
    "sportsorganization", "medicalorganization", "airline", "consortium",
    "cooperative", "library", "newsmediaorganization", "researchorganization",
    "workersunion", "professionalservice", "store", "restaurant",
    "foodestablishment", "financialservice", "legalservice",
}

ARTICLE_TYPES = {
    "article", "newsarticle", "blogposting", "techarticle", "report",
    "scholarlyarticle", "socialmediaposting", "liveblogposting",
}

LOCAL_TYPES = {
    "localbusiness", "store", "restaurant", "foodestablishment",
    "professionalservice", "financialservice", "legalservice",
    "medicalorganization", "dentist", "lodgingbusiness",
}

# Schema types that signal a commercial/business site (used to distinguish a
# brand/business from an individual's personal site).
COMMERCIAL_TYPES = {
    "product", "offer", "aggregateoffer", "offercatalog", "service", "productgroup",
}

# JSON-LD properties that commonly carry a nested Organization/Person entity, so
# the entity anchor may live one or two levels deep inside an Article/WebPage node.
CARRIER_PROPS = frozenset({
    "publisher", "author", "provider",
    "mainentity", "sourceorganization", "parentorganization",
})

# Hosts that bot-block / challenge HEAD requests: a non-2xx here is NOT proof the
# profile is dead. Bucket these as 'could not verify', never 'broken'.
BLOCKED_SAMEAS_HOSTS = (
    "linkedin.com", "crunchbase.com", "instagram.com", "facebook.com",
    "fb.com", "x.com", "twitter.com", "tiktok.com", "pinterest.com",
    "threads.net", "glassdoor.com",
)

SOCIAL_HOSTS = (
    "linkedin.com", "twitter.com", "x.com", "facebook.com", "fb.com",
    "instagram.com", "youtube.com", "youtu.be", "tiktok.com", "github.com",
    "pinterest.com", "threads.net", "medium.com", "mastodon.social",
    "crunchbase.com", "glassdoor.com",
)

LEGAL_SUFFIX = re.compile(
    r"\b(incorporated|inc|llc|l\.l\.c|ltd|limited|corp|corporation|co|company|"
    r"gmbh|plc|llp|lp|s\.?a|a\.?g|n\.?v|b\.?v|pty|holdings|group)\b\.?",
    re.I,
)

# Common single-word English terms that create mistaken-identity risk when used
# as a brand name with no external anchoring. (Deterministic; false negatives OK.)
GENERIC_WORDS = frozenset("""
apple orange amazon oracle sage monday notion stripe square block mint chime
robin path medium slack discord signal telegram opera edge chrome safari
summit peak river ocean forest meadow harbor anchor beacon compass lantern
atlas titan apollo mercury venus saturn nova comet nebula orbit fusion pulse
spark flare ember cinder frost glacier tide current wave surge ripple stream
brook grove maple cedar birch willow aspen elm oak pine fern moss ivy bloom
petal bud root branch canopy field pasture prairie valley ridge summit crest
apex vertex zenith horizon dawn dusk twilight aurora solstice equinox
lever pivot fulcrum axis vector matrix cipher token vault ledger nexus prism
beacon relay signal channel bridge portal gateway conduit vessel harbor
canvas palette easel studio forge anvil hammer chisel loom thread weave
harvest orchard vineyard cellar barrel keg brew roast grind bean leaf bloom
falcon eagle raven hawk sparrow finch wren robin heron crane swift kite
otter beaver fox wolf bear lynx puma jaguar panther cheetah bison stag
""".split())

# --- html/text access -------------------------------------------------------


def best_html(p):
    """Rendered HTML when render succeeded (JS-injected schema), else raw."""
    if getattr(p, "render_status", None) == "ok" and getattr(p, "rendered_html", None):
        return p.rendered_html
    return p.raw_html or ""


def best_text(p):
    if getattr(p, "render_status", None) == "ok" and getattr(p, "rendered_text", None):
        return p.rendered_text
    return p.raw_text or ""


# --- small pure helpers -----------------------------------------------------


def _as_text(v):
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, dict):
        return _as_text(v.get("@value") or v.get("name") or v.get("@id") or "")
    if isinstance(v, list):
        for x in v:
            t = _as_text(x)
            if t:
                return t
    return ""


def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _is_org(node):
    if not isinstance(node, dict):
        return False
    types = htmlutil.schema_types(node)
    if types & ORG_TYPES:
        return True
    return any(("organization" in t) or t.endswith("business") for t in types)


def _org_nodes(blocks):
    return [b for b in blocks if _is_org(b)]


def _article_nodes(blocks):
    out = []
    for b in blocks:
        if isinstance(b, dict) and (htmlutil.schema_types(b) & ARTICLE_TYPES):
            out.append(b)
    return out


def _is_person(node):
    return isinstance(node, dict) and ("person" in htmlutil.schema_types(node))


def _nested_matching(node, pred, depth=2):
    """Objects satisfying `pred` nested up to `depth` levels deep inside common
    carrier properties (publisher, author, provider, mainEntity, ...). This is how
    an Organization/Person anchor is found when it lives inside an Article/WebPage
    node rather than at the top level of the JSON-LD."""
    out = []
    if not isinstance(node, dict) or depth <= 0:
        return out
    for key, val in node.items():
        if key.lower() not in CARRIER_PROPS:
            continue
        for child in _as_list(val):
            if isinstance(child, dict):
                if pred(child):
                    out.append(child)
                out.extend(_nested_matching(child, pred, depth - 1))
    return out


def _page_org_nodes(blocks):
    """Organization nodes on a page: top-level first, then any nested one or two
    levels deep inside carrier properties (e.g. NewsArticle.publisher)."""
    orgs = _org_nodes(blocks)
    seen = {id(o) for o in orgs}
    for b in blocks:
        for o in _nested_matching(b, _is_org):
            if id(o) not in seen:
                seen.add(id(o))
                orgs.append(o)
    return orgs


def _has_person_anywhere(blocks):
    for b in blocks:
        if _is_person(b):
            return True
        if _nested_matching(b, _is_person):
            return True
    return False


def _deep_sameas(obj, out):
    """Collect every sameAs URL anywhere in a JSON-LD tree (any @type, any depth)."""
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key.lower() == "sameas":
                for u in _as_list(val):
                    s = _as_text(u)
                    if s.lower().startswith(("http://", "https://")):
                        out.add(s)
            else:
                _deep_sameas(val, out)
    elif isinstance(obj, list):
        for item in obj:
            _deep_sameas(item, out)


def _sameas_urls(nodes):
    urls = set()
    for n in nodes:
        for v in _as_list(n.get("sameAs")):
            u = _as_text(v)
            if u.lower().startswith(("http://", "https://")):
                urls.add(u)
    return urls


def _host(url):
    try:
        return (urlparse(url).netloc or "").lower().split(":")[0]
    except Exception:
        return ""


def _reg_domain(netloc):
    labels = [x for x in (netloc or "").lower().split(".") if x]
    if labels and labels[0] == "www":
        labels = labels[1:]
    if len(labels) >= 2:
        return labels[-2]
    return labels[0] if labels else ""


def _norm_brand(s):
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = LEGAL_SUFFIX.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def _meta(soup_obj, key):
    tag = soup_obj.find("meta", attrs={"property": key}) or \
        soup_obj.find("meta", attrs={"name": key})
    if tag and tag.get("content"):
        return tag["content"].strip()
    return ""


def _title_brand(soup_obj):
    """Best-effort brand segment of a <title>. Titles are typically
    'Article Headline | Brand' or 'Page Name - Brand', so the brand sits in the
    trailing segment after the separator — never the leading headline portion."""
    t = soup_obj.find("title")
    if not t:
        return ""
    txt = htmlutil.norm_text(t.get_text())
    seg = [s.strip() for s in re.split(r"\s[|\-–—:·]\s", txt) if s.strip()]
    return (seg[-1] if seg else txt).strip()


_YEAR = re.compile(r"(?:19|20)\d{2}")
_COPYRIGHT = re.compile(
    r"(?:©|&copy;|copyright)\s*(?:\(c\))?\s*"
    r"((?:19|20)\d{2})(?:\s*[-–—]\s*((?:19|20)\d{2}))?",
    re.I,
)
_UPDATED = re.compile(
    r"(?:last\s+updated|last\s+modified|updated\s+on|updated|modified)\b[^\d]{0,40}?"
    r"((?:19|20)\d{2})",
    re.I,
)


def _copyright_year(text):
    best = None
    for m in _COPYRIGHT.finditer(text or ""):
        yr = int(m.group(2) or m.group(1))  # upper bound of a range
        if best is None or yr > best:
            best = yr
    return best


def _updated_year(text):
    m = _UPDATED.search(text or "")
    return int(m.group(1)) if m else None


def _schema_year(nodes, key):
    for n in nodes:
        v = _as_text(n.get(key))
        m = _YEAR.search(v)
        if m:
            return int(m.group(0))
    return None


def _outbound_external(html, site):
    site_host = _host(site)
    site_reg = _reg_domain(site_host)
    hosts = set()
    for a in htmlutil.soup(html).find_all("a", href=True):
        href = a["href"].strip()
        if not href.lower().startswith(("http://", "https://")):
            continue
        h = _host(href)
        if not h or h == site_host:
            continue
        if site_reg and (h == site_reg or h.endswith("." + site_reg)):
            continue
        hosts.add(h)
    return hosts


def _social_links(html):
    found = set()
    for a in htmlutil.soup(html).find_all("a", href=True):
        h = _host(a["href"])
        for sh in SOCIAL_HOSTS:
            if h == sh or h.endswith("." + sh):
                found.add(sh)
    return found


_BYLINE_RE = re.compile(
    r"\b(?:written\s+by|by)\s+([A-Z][A-Za-z.'’\-]+(?:[\s,]+[A-Za-z.'’\-]+){0,6})",
    re.I,
)


def _byline_tokens(text):
    """Normalized name tokens of the visible byline after 'By'/'Written by'.
    Includes any trailing role words (e.g. 'Senior Energy Correspondent') so a
    schema author name can be matched as a run/subset rather than an exact string."""
    m = _BYLINE_RE.search(text or "")
    if not m:
        return []
    return _norm_brand(m.group(1)).split()


def _individual_site(ctx, ok_pages, blocks_by_url):
    """True when the site presents as an individual (a Person is the primary
    entity) with no commercial/business signal — a personal blog legitimately
    anchored by a Person rather than an Organization."""
    person_found = False
    for p in ok_pages:
        for b in blocks_by_url.get(p.url, []):
            if not isinstance(b, dict):
                continue
            if htmlutil.schema_types(b) & COMMERCIAL_TYPES:
                return False
        if not person_found and _has_person_anywhere(blocks_by_url.get(p.url, [])):
            person_found = True
    if not person_found:
        return False
    home = ctx.home if (ctx.home and ctx.home.ok) else ok_pages[0]
    soup_obj = htmlutil.soup(best_html(home))
    for name in (_meta(soup_obj, "og:site_name"), _title_brand(soup_obj)):
        if name and LEGAL_SUFFIX.search(name):
            return False
    return True


# --- main entrypoint --------------------------------------------------------


def run(ctx):
    findings = []
    ok_pages = [p for p in ctx.pages if p.ok]
    if not ok_pages:
        return findings
    M = len(ok_pages)

    # Precompute per-page schema + parsed html once.
    blocks_by_url = {}
    for p in ok_pages:
        try:
            blocks_by_url[p.url] = htmlutil.jsonld_blocks(best_html(p))
        except Exception:
            blocks_by_url[p.url] = []
    all_org_nodes = []
    for p in ok_pages:
        all_org_nodes.extend(_page_org_nodes(blocks_by_url.get(p.url, [])))
    all_sameas = _sameas_urls(all_org_nodes)

    _check_org_anchor(ctx, findings, ok_pages, M, blocks_by_url)
    _check_sameas(ctx, findings, all_org_nodes, all_sameas, M)
    _check_name_consistency(ctx, findings, ok_pages, blocks_by_url, all_sameas)
    _check_freshness(ctx, findings, ok_pages, M, blocks_by_url)
    _check_author_eeat(ctx, findings, ok_pages, blocks_by_url)
    _check_offsite_surface(ctx, findings, ok_pages, blocks_by_url)
    return findings


def _check_org_anchor(ctx, findings, ok_pages, M, blocks_by_url):
    try:
        pages_with_org = 0
        pages_missing_fields = 0
        missing_field_counts = {"name": 0, "url": 0, "logo": 0}
        fragmented_pages = 0
        example_missing = ""
        example_frag = ""
        for p in ok_pages:
            orgs = _page_org_nodes(blocks_by_url.get(p.url, []))
            if not orgs:
                continue
            pages_with_org += 1
            primary = orgs[0]
            miss = [f for f in ("name", "url", "logo") if not primary.get(f)]
            if miss:
                pages_missing_fields += 1
                for f in miss:
                    missing_field_counts[f] += 1
                if not example_missing:
                    example_missing = f"{p.url} Organization missing {', '.join(miss)}"
            # fragmentation: 2+ org nodes on one page with distinct @id or name
            ids = {_as_text(o.get("@id")) for o in orgs if o.get("@id")}
            names = {_norm_brand(_as_text(o.get("name"))) for o in orgs if o.get("name")}
            names.discard("")
            if len(orgs) >= 2 and (len(ids) >= 2 or len(names) >= 2):
                fragmented_pages += 1
                if not example_frag:
                    example_frag = f"{p.url} has {len(orgs)} Organization nodes, @id values={sorted(ids) or 'none'}"

        if pages_with_org == 0 and _individual_site(ctx, ok_pages, blocks_by_url):
            # Personal/individual site anchored by a Person entity — an
            # Organization anchor is not expected here, so do not flag.
            pass
        elif pages_with_org == 0:
            findings.append(make_finding(
                check="org-entity-anchor-idgraph",
                title="No Organization entity anchor in JSON-LD",
                severity="high", half="discoverability",
                evidence=f"No Organization/LocalBusiness/Corporation JSON-LD node on any sampled page (0/{M} pages). Engines have no machine-readable brand node to anchor to.",
                fix="Add one Organization JSON-LD node with a stable @id, plus name, url and logo, on the homepage (and reference it site-wide).",
                mechanism="AI engines resolve the brand string to a knowledge-graph node BEFORE evaluating page content; with no stable anchor, entity consolidation and knowledge-panel eligibility never begin.",
                confidence="high", effort="medium",
                location=f"{ctx.site}::org-anchor-absent",
            ))
        else:
            if pages_missing_fields:
                worst = sorted(missing_field_counts.items(), key=lambda kv: (-kv[1], kv[0]))
                worst = [f"{k} ({v})" for k, v in worst if v]
                findings.append(make_finding(
                    check="org-entity-anchor-idgraph",
                    title="Organization node missing core identity fields",
                    severity="high", half="discoverability",
                    evidence=f"Organization JSON-LD missing name/url/logo on {pages_missing_fields}/{M} pages; missing-field frequency: {', '.join(worst)}. Example: {example_missing}.",
                    fix="Populate name, url and logo on the Organization node; foundingDate is optional.",
                    mechanism="Without name+url+logo the node cannot be matched to a knowledge-graph entity or rendered in a brand panel.",
                    confidence="high", effort="low",
                    location=f"{ctx.site}::org-anchor-missing-fields",
                    evidence_detail={"missing_field_counts": missing_field_counts},
                ))
        if fragmented_pages:
            findings.append(make_finding(
                check="org-entity-anchor-idgraph",
                title="Fragmented Organization graph (conflicting @id/name)",
                severity="high", half="discoverability",
                evidence=f"Duplicate/conflicting Organization nodes with different @id or name on {fragmented_pages}/{M} pages. Example: {example_frag}.",
                fix="Collapse to a single canonical Organization node with one stable @id and reference it (via @id) everywhere instead of redefining it.",
                mechanism="Multiple conflicting anchors fragment the entity graph, so engines cannot decide which node is the canonical brand.",
                confidence="medium", effort="medium",
                location=f"{ctx.site}::org-anchor-fragmented",
            ))
    except Exception:
        pass


def _check_sameas(ctx, findings, all_org_nodes, all_sameas, M):
    try:
        if not all_org_nodes:
            return
        broken = []
        for url in sorted(all_sameas):
            h = _host(url)
            if any(h == b or h.endswith("." + b) for b in BLOCKED_SAMEAS_HOSTS):
                continue  # bot-blocked host: never dead
            res = ctx.fetch_extra(url, "head")
            fc = res.get("fetch_class")
            if fc == "not_found":  # 404 / 410 only
                broken.append(url)
            # ok / blocked / transient / capped / robots -> not counted as dead

        if broken:
            findings.append(make_finding(
                check="sameas-resolvability",
                title="Broken sameAs target(s) on Organization",
                severity="high", half="discoverability",
                evidence=f"{len(broken)}/{len(all_sameas)} Organization sameAs URL(s) return 404/410: {', '.join(sorted(broken)[:5])}.",
                fix="Fix or remove the dead sameAs URLs so every merge target resolves to a live profile.",
                mechanism="sameAs is the merge instruction to Wikidata/Wikipedia/LinkedIn; a dead sameAs actively breaks entity consolidation and is worse than omitting it.",
                confidence="high", effort="low",
                location=f"{ctx.site}::sameas-broken",
                evidence_detail={"broken": sorted(broken)},
            ))

        # Total absence of sameAs is reported by offsite-corroboration-surface;
        # here we flag the narrower case of sameAs present but no wiki anchor.
        has_wiki = any(("wikidata.org" in _host(u)) or ("wikipedia.org" in _host(u))
                       for u in all_sameas)
        if all_sameas and not has_wiki:
            n = len(all_sameas)
            findings.append(make_finding(
                check="sameas-resolvability",
                title="No Wikidata/Wikipedia link in sameAs",
                severity="high", half="discoverability",
                evidence=f"Organization sameAs lists {n} URL(s) but none point to Wikidata or Wikipedia (0/{n}).",
                fix="Add the brand's Wikidata (and/or Wikipedia) URL to Organization.sameAs to anchor the entity to the authoritative knowledge graph.",
                mechanism="Wikidata/Wikipedia are the primary reconciliation targets engines use to identify a brand entity; without them sameAs cannot merge to the canonical node.",
                confidence="medium", effort="medium",
                location=f"{ctx.site}::sameas-no-wikidata",
            ))
    except Exception:
        pass


def _check_name_consistency(ctx, findings, ok_pages, blocks_by_url, all_sameas):
    try:
        home = ctx.home if (ctx.home and ctx.home.ok) else ok_pages[0]
        soup_obj = htmlutil.soup(best_html(home))
        orgs = _page_org_nodes(blocks_by_url.get(home.url, []))
        schema_name = _as_text(orgs[0].get("name")) if orgs else ""
        og_name = _meta(soup_obj, "og:site_name")
        domain_sld = _reg_domain(_host(ctx.site))

        # og:site_name and the JSON-LD publisher/Organization name are the
        # authoritative brand strings. The <title> is NOT — its leading segment is
        # usually the article headline, not the brand — so it is only a last-resort
        # fallback (trailing segment) when neither authoritative source exists.
        declared = {
            "schema.name": _norm_brand(schema_name),
            "og:site_name": _norm_brand(og_name),
        }
        present = {k: v for k, v in declared.items() if v}
        if not present:
            title_brand = _norm_brand(_title_brand(soup_obj))
            if title_brand:
                present = {"title": title_brand}
        distinct = sorted(set(present.values()))

        def _share_token(vals):
            token_sets = [set(v.split()) for v in vals]
            common = set.intersection(*token_sets) if token_sets else set()
            return bool(common)

        if len(distinct) >= 2 and not _share_token(list(present.values())):
            pairs = ", ".join(f"{k}='{v}'" for k, v in sorted(present.items()))
            findings.append(make_finding(
                check="name-consistency-ambiguity",
                title="Brand name inconsistent across declarations",
                severity="low", half="discoverability",
                evidence=f"Brand string differs after normalization across sources on the homepage: {pairs} (1/{len(ok_pages)} home page).",
                fix="Use one canonical brand string in JSON-LD name, og:site_name and <title> (legal suffixes may vary but the core name should match).",
                mechanism="Conflicting brand strings make it harder for engines to collapse the mentions to one entity.",
                confidence="medium", effort="low",
                location=f"{ctx.site}::name-mismatch",
            ))

        # generic single-word name + no external anchoring -> mistaken identity
        brand = present.get("schema.name") or present.get("og:site_name") or _norm_brand(domain_sld)
        has_wiki = any(("wikidata.org" in _host(u)) or ("wikipedia.org" in _host(u))
                       for u in all_sameas)
        if (brand and " " not in brand and brand.isalpha()
                and brand in GENERIC_WORDS and not all_sameas and not has_wiki):
            findings.append(make_finding(
                check="name-consistency-ambiguity",
                title="Generic single-word brand name with no external anchor",
                severity="medium", half="discoverability",
                evidence=f"Brand name '{brand}' is a generic dictionary word and co-occurs with no sameAs and no Wikidata/Wikipedia link, creating mistaken-identity risk.",
                fix="Anchor the entity: add sameAs (Wikidata/Wikipedia/LinkedIn) and a distinctive Organization @id so engines don't confuse the brand with the common noun.",
                mechanism="A generic word with zero external anchoring lets engines attribute facts to the wrong entity (the common noun or a better-anchored namesake).",
                confidence="medium", effort="medium",
                location=f"{ctx.site}::name-generic-ambiguous",
            ))
    except Exception:
        pass


def _check_freshness(ctx, findings, ok_pages, M, blocks_by_url):
    try:
        cur_year = datetime.date.today().year
        copyright_years = []
        mismatch_pages = 0
        stale_pages = 0
        example_mismatch = ""
        for p in ok_pages:
            text = best_text(p)
            blocks = blocks_by_url.get(p.url, [])
            is_content = bool(_article_nodes(blocks)) or \
                any(htmlutil.schema_types(b) & {"webpage", "aboutpage", "collectionpage"} for b in blocks) or \
                htmlutil.word_count(htmlutil.main_text(best_html(p))) > 300

            cy = _copyright_year(text)
            if cy:
                copyright_years.append((p.url, cy))

            if not is_content:
                continue
            years = set()
            sy = _schema_year(blocks, "dateModified")
            if sy:
                years.add(sy)
            uy = _updated_year(text)
            if uy:
                years.add(uy)
            hdr = (p.headers or {}).get("last-modified", "")
            hm = _YEAR.search(hdr or "")
            if hm:
                years.add(int(hm.group(0)))
            if len(years) >= 2 and (max(years) - min(years)) >= 1:
                mismatch_pages += 1
                if not example_mismatch:
                    example_mismatch = f"{p.url} date signals={sorted(years)}"
            if sy and (cur_year - sy) >= 2:
                stale_pages += 1

        if copyright_years:
            max_cy = max(y for _, y in copyright_years)
            if (cur_year - max_cy) >= 2:
                behind = cur_year - max_cy
                findings.append(make_finding(
                    check="freshness-signals",
                    title="Stale footer copyright year",
                    severity="medium", half="both",
                    evidence=f"Newest footer copyright year is {max_cy}, {behind} years behind current year {cur_year} ({len(copyright_years)}/{M} pages carry a copyright year).",
                    fix="Update the footer copyright year (ideally auto-generated) so it reflects the current year.",
                    mechanism="Recency-sensitive engines discount stale pages, and human visitors read an old copyright year as a sign the site is abandoned.",
                    confidence="high", effort="low",
                    location=f"{ctx.site}::freshness-copyright-stale",
                ))

        if mismatch_pages:
            findings.append(make_finding(
                check="freshness-signals",
                title="Conflicting last-updated date signals",
                severity="medium", half="both",
                evidence=f"schema dateModified, visible 'updated' date and/or Last-Modified header disagree on {mismatch_pages}/{M} pages. Example: {example_mismatch}.",
                fix="Make the machine-readable dateModified match the visible last-updated date and the response Last-Modified header.",
                mechanism="Contradictory recency signals confuse freshness ranking and undercut trust in the page's own metadata.",
                confidence="medium", effort="medium",
                location=f"{ctx.site}::freshness-date-mismatch",
            ))
        elif stale_pages:
            findings.append(make_finding(
                check="freshness-signals",
                title="Content dateModified is years stale",
                severity="low", half="both",
                evidence=f"schema dateModified is >=2 years behind current year {datetime.date.today().year} on {stale_pages}/{M} content pages.",
                fix="Review and refresh stale content, updating dateModified when the content genuinely changes.",
                mechanism="Recency-sensitive engines discount pages whose declared modification date is far in the past.",
                confidence="low", effort="medium",
                location=f"{ctx.site}::freshness-schema-stale",
            ))
    except Exception:
        pass


def _check_author_eeat(ctx, findings, ok_pages, blocks_by_url):
    try:
        article_pages = [p for p in ok_pages if _article_nodes(blocks_by_url.get(p.url, []))]
        # author problems + citation gaps only make sense on article pages
        if article_pages:
            A = len(article_pages)
            author_bad = 0
            byline_conflict = 0
            no_citation = 0
            example_author = ""
            for p in article_pages:
                arts = _article_nodes(blocks_by_url.get(p.url, []))
                author_name = ""
                for a in arts:
                    author_name = _as_text(a.get("author"))
                    if author_name:
                        break
                low = author_name.lower()
                if not author_name or low in ("admin", "administrator", "editor", "author"):
                    author_bad += 1
                    if not example_author:
                        example_author = f"{p.url} author='{author_name or 'missing'}'"
                else:
                    # A schema author name that is a subset/run of the visible
                    # byline (e.g. "Priya Chandran" vs "By Priya Chandran, Senior
                    # Energy Correspondent") is a MATCH. Only flag when the two
                    # names genuinely disagree — i.e. share no name tokens.
                    author_tokens = set(_norm_brand(author_name).split())
                    byline = set(_byline_tokens(best_text(p)))
                    if author_tokens and byline and not (author_tokens & byline):
                        byline_conflict += 1
                # long-form with zero outbound external citations
                main = htmlutil.main_text(best_html(p))
                if htmlutil.word_count(main) >= 600 and not _outbound_external(best_html(p), ctx.site):
                    no_citation += 1

            if author_bad:
                findings.append(make_finding(
                    check="author-eeat-contact-citations",
                    title="Article author missing or generic",
                    severity="medium", half="discoverability",
                    evidence=f"Article author is missing or a generic placeholder (admin/editor) on {author_bad}/{A} article pages. Example: {example_author}.",
                    fix="Attribute articles to a named Person author (with a real profile) in JSON-LD and the visible byline.",
                    mechanism="E-E-A-T signals depend on an identifiable, machine-readable author; a generic/absent author weakens the page's authority.",
                    confidence="high", effort="low",
                    location=f"{ctx.site}::author-generic",
                ))
            if byline_conflict:
                findings.append(make_finding(
                    check="author-eeat-contact-citations",
                    title="Schema author disagrees with visible byline",
                    severity="medium", half="discoverability",
                    evidence=f"JSON-LD author differs from the visible 'By ...' byline on {byline_conflict}/{A} article pages.",
                    fix="Make the JSON-LD author name match the visible byline exactly.",
                    mechanism="Conflicting author signals make the authorship claim unverifiable, reducing trust attribution.",
                    confidence="medium", effort="low",
                    location=f"{ctx.site}::author-byline-conflict",
                ))
            if no_citation:
                findings.append(make_finding(
                    check="author-eeat-contact-citations",
                    title="Long-form content with no outbound citations",
                    severity="low", half="discoverability",
                    evidence=f"{no_citation}/{A} long-form (>=600 word) article pages contain zero outbound external links (citations).",
                    fix="Cite authoritative external sources with real outbound links in long-form content.",
                    mechanism="Outbound citations are a corroboration signal; their total absence in long-form content reads as unsourced.",
                    confidence="low", effort="medium",
                    location=f"{ctx.site}::eeat-no-citations",
                ))

        # NAP consistency only for physical/local businesses
        local_nodes = []
        for p in ok_pages:
            for b in blocks_by_url.get(p.url, []):
                if isinstance(b, dict) and (htmlutil.schema_types(b) & LOCAL_TYPES):
                    local_nodes.append(b)
        if local_nodes:
            miss = [f for f in ("name", "address", "telephone")
                    if not any(n.get(f) for n in local_nodes)]
            if miss:
                findings.append(make_finding(
                    check="author-eeat-contact-citations",
                    title="LocalBusiness NAP fields incomplete",
                    severity="medium", half="discoverability",
                    evidence=f"LocalBusiness schema is missing {', '.join(miss)} across {len(local_nodes)} local-business node(s).",
                    fix="Provide complete, consistent Name/Address/Phone (NAP) on the LocalBusiness node.",
                    mechanism="For physical/local brands, consistent NAP is the key entity-matching signal across maps and directories.",
                    confidence="medium", effort="low",
                    location=f"{ctx.site}::nap-incomplete",
                ))
    except Exception:
        pass


def _check_offsite_surface(ctx, findings, ok_pages, blocks_by_url):
    try:
        # sameAs on ANY JSON-LD node (Person, Organization, nested, etc.) across
        # ALL sampled pages counts as an off-site identity surface — not just
        # Organization.sameAs on the homepage.
        sameas_all = set()
        for p in ok_pages:
            for b in blocks_by_url.get(p.url, []):
                _deep_sameas(b, sameas_all)
        has_social = False
        has_wiki_link = any(("wikidata.org" in _host(u)) or ("wikipedia.org" in _host(u))
                            for u in sameas_all)
        for p in ok_pages:
            html = best_html(p)
            if _social_links(html):
                has_social = True
            for a in htmlutil.soup(html).find_all("a", href=True):
                h = _host(a["href"])
                if "wikidata.org" in h or "wikipedia.org" in h:
                    has_wiki_link = True
        if not sameas_all and not has_social and not has_wiki_link:
            findings.append(make_finding(
                check="offsite-corroboration-surface",
                title="No off-site identity surface found",
                severity="medium", half="discoverability",
                evidence=f"No sameAs, no footer/social profile links, and no Wikipedia/Wikidata link on any of the {len(ok_pages)} sampled pages.",
                fix="Establish and link off-site identity surfaces (social profiles, Crunchbase, Wikidata/Wikipedia) and mirror them in Organization.sameAs.",
                mechanism="The large majority of AI brand mentions are sourced from third-party pages; with zero off-site surface there is structurally little for an engine to cite.",
                confidence="low", effort="medium",
                location=f"{ctx.site}::offsite-absent",
            ))
    except Exception:
        pass


if __name__ == '__main__':
    import json
    from common import fetch
    ctx = fetch.build_context(sys.argv[1])
    print(json.dumps(run(ctx), indent=2, default=str))
    ctx.close()
