"""Read-only fetch/render spine.

Runs ONE polite, robots-honoring pass over a deterministic sample of pages and
caches a `PageBundle` per URL. Sub-skills read these bundles instead of
re-fetching, which is what keeps the audit polite and under the time budget.
Playwright rendering is optional: any launch failure degrades to raw-HTML-only
with `render_available=False`, and skills fall back to static heuristics.

Everything here is read-only: GET/HEAD only, no auth, no writes to the target.
"""
import time
from dataclasses import dataclass, field, asdict
from urllib.parse import urljoin, urlparse, urldefrag

import httpx
from protego import Protego

from . import htmlutil

AUDIT_UA = ("BrandAIReadinessAudit/1.0 (+https://example.invalid/audit-bot; "
            "read-only website auditor; contact: audit@example.invalid)")
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

MAX_BYTES = 3_000_000
_SKIP_EXT = (".pdf", ".zip", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
             ".mp4", ".mp3", ".css", ".js", ".ico", ".xml", ".json", ".woff",
             ".woff2", ".ttf", ".dmg", ".exe", ".csv", ".txt", ".rss", ".atom")
_SKIP_HINT = ("logout", "signout", "sign-out", "/wp-admin", "/cart", "/checkout")


@dataclass
class PageBundle:
    url: str
    requested_url: str = ""
    final_url: str = ""
    status: object = None            # int or None
    fetch_class: str = "error"       # ok | not_found | blocked | transient | error
    headers: dict = field(default_factory=dict)
    content_type: str = ""
    raw_html: str = ""
    raw_text: str = ""
    raw_main_text: str = ""
    rendered_html: object = None
    rendered_text: object = None
    rendered_main_text: object = None
    render_status: str = "not_attempted"   # ok | skipped | error | not_attempted
    redirect_chain: list = field(default_factory=list)
    elapsed_ms: object = None
    fetch_error: object = None
    is_home: bool = False

    @property
    def ok(self):
        return self.fetch_class == "ok"


@dataclass
class RobotsInfo:
    url: str
    status: object = None
    raw: str = ""
    exists: bool = False
    parser: object = None
    sitemaps: list = field(default_factory=list)


def normalize_url(u):
    u = urldefrag(u)[0]
    if u.endswith("/") and urlparse(u).path not in ("", "/"):
        u = u[:-1]
    return u


def origin_of(u):
    p = urlparse(u)
    return f"{p.scheme}://{p.netloc}"


def _classify(status):
    if status is None:
        return "transient"
    if 200 <= status < 300:
        return "ok"
    if status in (404, 410):
        return "not_found"
    if status in (401, 403, 429, 451, 999):
        return "blocked"
    if status >= 500:
        return "transient"
    return "error"


class AuditContext:
    def __init__(self, site, start_url, pages, robots, render_available,
                 client, extra_cap=30, offline=False):
        self.site = site
        self.start_url = start_url
        self.pages = pages
        self.robots = robots
        self.render_available = render_available
        self.offline = offline
        self.home = next((p for p in pages if p.is_home), pages[0] if pages else None)
        self._client = client
        self._extra_cap = extra_cap
        self._extra_used = 0
        self._extra_cache = {}

    def to_snapshot(self):
        """Serialize the whole crawl to a plain dict (JSON-safe) for offline replay."""
        return {
            "site": self.site,
            "start_url": self.start_url,
            "render_available": self.render_available,
            "robots": {"url": self.robots.url, "status": self.robots.status,
                       "raw": self.robots.raw, "exists": self.robots.exists,
                       "sitemaps": list(self.robots.sitemaps)},
            "pages": [asdict(p) for p in self.pages],
        }

    def allowed(self, url):
        """Robots verdict for our own polite UA (same-origin only)."""
        if self.robots.parser is None:
            return True
        try:
            return self.robots.parser.can_fetch(url, AUDIT_UA)
        except Exception:
            return True

    def close(self):
        try:
            self._client.close()
        except Exception:
            pass

    def fetch_as(self, url, user_agent):
        """One capped GET under a specific User-Agent — used to probe WAF/UA gating
        (bot UA vs browser UA from the same client/IP). Returns {status, fetch_class,
        final_url, error}."""
        if self.offline:
            return {"status": None, "fetch_class": "inconclusive", "final_url": url, "error": "offline replay"}
        if self._extra_used >= self._extra_cap:
            return {"status": None, "fetch_class": "capped", "final_url": url, "error": "extra-fetch cap reached"}
        self._extra_used += 1
        try:
            r = self._client.get(url, headers={"User-Agent": user_agent}, timeout=10.0)
            return {"status": r.status_code, "fetch_class": _classify(r.status_code),
                    "final_url": str(r.url), "error": None}
        except Exception as e:
            return {"status": None, "fetch_class": "transient", "final_url": url,
                    "error": f"{type(e).__name__}: {e}"}

    def fetch_extra(self, url, method="head"):
        """Bounded, network-dependent single request for checks that must touch a
        URL not in the sampled set (sameAs resolvability, broken internal links).
        Same-origin requests honor robots; external hosts get one lightweight HEAD.
        Returns a dict {status, fetch_class, final_url, error} or a cap/blocked marker."""
        if self.offline:
            return {"status": None, "fetch_class": "inconclusive", "final_url": url, "error": "offline replay"}
        key = (method, url)
        if key in self._extra_cache:
            return self._extra_cache[key]
        if self._extra_used >= self._extra_cap:
            return {"status": None, "fetch_class": "capped", "final_url": url, "error": "extra-fetch cap reached"}
        same_origin = origin_of(url) == self.site
        if same_origin and not self.allowed(url):
            res = {"status": None, "fetch_class": "robots_disallowed", "final_url": url, "error": "robots disallowed"}
            self._extra_cache[key] = res
            return res
        self._extra_used += 1
        try:
            fn = self._client.head if method == "head" else self._client.get
            r = fn(url, timeout=8.0)
            if method == "head" and r.status_code in (403, 405, 501):
                r = self._client.get(url, timeout=8.0)  # some servers reject HEAD
            res = {"status": r.status_code, "fetch_class": _classify(r.status_code),
                   "final_url": str(r.url), "error": None}
        except Exception as e:
            res = {"status": None, "fetch_class": "transient", "final_url": url,
                   "error": f"{type(e).__name__}: {e}"}
        self._extra_cache[key] = res
        return res


def _fetch_robots(client, site):
    url = site + "/robots.txt"
    info = RobotsInfo(url=url)
    try:
        r = client.get(url, timeout=10.0)
        info.status = r.status_code
        if 200 <= r.status_code < 300 and "text" in r.headers.get("content-type", "text/plain"):
            info.raw = r.text[:200_000]
            info.exists = True
            info.parser = Protego.parse(info.raw)
            try:
                info.sitemaps = [normalize_url(s) for s in info.parser.sitemaps]
            except Exception:
                info.sitemaps = []
    except Exception:
        pass
    return info


def _sitemap_urls(client, sitemap_urls, site, limit=40):
    out = []
    seen = set()
    for sm in list(sitemap_urls)[:3]:
        try:
            r = client.get(sm, timeout=10.0)
            if r.status_code >= 300:
                continue
            s = htmlutil.soup(r.text)
            # one level of sitemapindex expansion
            child_maps = [loc.get_text(strip=True) for loc in s.select("sitemap > loc")]
            if child_maps:
                for cm in child_maps[:2]:
                    try:
                        rr = client.get(cm, timeout=10.0)
                        ss = htmlutil.soup(rr.text)
                        for loc in ss.select("url > loc"):
                            u = normalize_url(loc.get_text(strip=True))
                            if u and u not in seen and origin_of(u) == site:
                                seen.add(u); out.append(u)
                    except Exception:
                        continue
            for loc in s.select("url > loc"):
                u = normalize_url(loc.get_text(strip=True))
                if u and u not in seen and origin_of(u) == site:
                    seen.add(u); out.append(u)
        except Exception:
            continue
        if len(out) >= limit:
            break
    return out


def _internal_links(html, base, site):
    out = []
    seen = set()
    for a in htmlutil.soup(html).find_all("a", href=True):
        href = a["href"].strip()
        low = href.lower()
        if not href or low.startswith(("mailto:", "tel:", "javascript:", "#", "data:")):
            continue
        u = normalize_url(urljoin(base, href))
        if origin_of(u) != site:
            continue
        path = urlparse(u).path.lower()
        if any(path.endswith(e) for e in _SKIP_EXT) or any(h in u.lower() for h in _SKIP_HINT):
            continue
        if u not in seen:
            seen.add(u); out.append(u)
    return out


def _do_fetch(client, url, is_home=False):
    b = PageBundle(url=url, requested_url=url, is_home=is_home)
    t0 = time.perf_counter()
    try:
        r = client.get(url, timeout=httpx.Timeout(20.0, connect=8.0))
        b.elapsed_ms = int(r.elapsed.total_seconds() * 1000)
        b.status = r.status_code
        b.final_url = str(r.url)
        b.redirect_chain = [str(h.url) for h in r.history] + [str(r.url)]
        b.headers = {k.lower(): v for k, v in r.headers.items()}
        b.content_type = b.headers.get("content-type", "")
        b.fetch_class = _classify(r.status_code)
        if "html" in b.content_type or (not b.content_type and b.fetch_class == "ok"):
            b.raw_html = r.text[:MAX_BYTES]
            b.raw_text = htmlutil.visible_text(b.raw_html)
            b.raw_main_text = htmlutil.main_text(b.raw_html)
        # A successful fetch of a non-HTML resource (robots.txt, feeds, JSON) is not an
        # auditable page: mark it non_html so content checks (which filter on .ok) skip it.
        if b.fetch_class == "ok" and not b.raw_html:
            b.fetch_class = "non_html"
    except Exception as e:
        b.elapsed_ms = int((time.perf_counter() - t0) * 1000)
        b.fetch_class = "transient"
        b.fetch_error = f"{type(e).__name__}: {e}"
    return b


def _render_pages(pages):
    """Optionally render each ok page with Playwright. Any launch error -> skip all."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        for p in pages:
            p.render_status = "skipped"
        return False
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=[
                "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"])
            try:
                for p in pages:
                    if not p.ok:
                        p.render_status = "skipped"
                        continue
                    try:
                        page = browser.new_page(user_agent=BROWSER_UA)
                        page.goto(p.final_url or p.url, wait_until="networkidle", timeout=20000)
                        p.rendered_html = page.content()
                        p.rendered_text = htmlutil.visible_text(p.rendered_html)
                        p.rendered_main_text = htmlutil.main_text(p.rendered_html)
                        p.render_status = "ok"
                        page.close()
                    except Exception:
                        p.render_status = "error"
            finally:
                browser.close()
        return True
    except Exception:
        for p in pages:
            if p.render_status == "not_attempted":
                p.render_status = "skipped"
        return False


def build_context(start_url, max_pages=12, render=True):
    """Fetch a deterministic sample of pages and return an AuditContext."""
    if "://" not in start_url:
        start_url = "https://" + start_url
    start_url = normalize_url(start_url)
    site = origin_of(start_url)

    client = httpx.Client(headers={"User-Agent": AUDIT_UA, "Accept": "text/html,*/*"},
                          follow_redirects=True, http2=False)
    robots = _fetch_robots(client, site)

    # Deterministic scope: homepage, then a sorted union of nav links + sitemap sample.
    home = _do_fetch(client, start_url, is_home=True)
    candidates = []
    if home.ok:
        candidates += _internal_links(home.raw_html, home.final_url or start_url, site)
    candidates += _sitemap_urls(client, robots.sitemaps or [site + "/sitemap.xml"], site)
    pool = sorted({normalize_url(u) for u in candidates} - {start_url})
    chosen = []
    for u in pool:
        if len(chosen) >= max_pages - 1:
            break
        if robots.parser is not None:
            try:
                if not robots.parser.can_fetch(u, AUDIT_UA):
                    continue
            except Exception:
                pass
        chosen.append(u)

    pages = [home] + [_do_fetch(client, u) for u in chosen]
    if render:
        render_available = _render_pages(pages)
    else:
        render_available = False
        for p in pages:
            p.render_status = "not_attempted"
    return AuditContext(site, start_url, pages, robots, render_available, client)


def build_context_from_snapshot(data):
    """Rebuild an AuditContext from a to_snapshot() dict for offline, deterministic
    replay. Network-dependent extra fetches return 'inconclusive' in this mode."""
    rb = data.get("robots", {})
    raw = rb.get("raw", "")
    robots = RobotsInfo(url=rb.get("url", ""), status=rb.get("status"), raw=raw,
                        exists=rb.get("exists", False),
                        parser=Protego.parse(raw) if raw else None,
                        sitemaps=list(rb.get("sitemaps", [])))
    pages = [PageBundle(**pd) for pd in data.get("pages", [])]
    return AuditContext(data["site"], data.get("start_url", data["site"]),
                        pages, robots, data.get("render_available", False),
                        client=None, offline=True)
