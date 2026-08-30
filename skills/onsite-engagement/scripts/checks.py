"""onsite-engagement checks: why arriving visitors don't stay (the engagement half).

Read-only, deterministic. Each check aggregates across the sampled pages and emits
ONE finding per issue-type with 'N/M pages' prevalence. Uses raw_html for what
loads first (page weight, render-blocking, viewport) and rendered_html when it is
available and helpful (overlays, injected media). Never emits a content finding
from a page whose fetch_class != 'ok'.
"""
import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
from common.contract import make_finding
from common import htmlutil

import re
from urllib.parse import urljoin, urlparse

# ---------------------------------------------------------------------------
# Thresholds (see references/engagement-thresholds.md for provenance).
# ---------------------------------------------------------------------------
HTML_BYTES_RISK = 100_000        # uncompressed HTML markup; HTTP Archive median ~30KB compressed
SYNC_SCRIPT_RISK = 3             # render-blocking sync <script> in <head>
STYLESHEET_RISK = 3             # render-blocking <link rel=stylesheet> in <head>
COMPRESSION_TOKENS = ("gzip", "br", "deflate", "zstd")

BIG_INTRINSIC_PX = 1000          # img width/height attr that really wants srcset
LONG_PARAGRAPH_WORDS = 150       # wall-of-text paragraph
READABILITY_MIN_WORDS = 400      # only flag genuinely long main content
FLESCH_HARD = 30.0               # < 30 == very hard (college/graduate) reading level
HIGH_Z_INDEX = 1000              # overlay stacking threshold
SMALL_FONT_PX = 12.0             # dominant body text floor

CONSENT_PAT = re.compile(
    r"cookie|consent|gdpr|ccpa|privacy|age.?(verif|gate|18|21)|"
    r"sign[\s-]?in|log[\s-]?in|newsletter|subscribe",
    re.I)
OVERLAY_CLASS_PAT = re.compile(
    r"modal|overlay|popup|pop-up|interstitial|lightbox|backdrop|dialog", re.I)

_PX = re.compile(r"([\d.]+)\s*(px|pt|rem|em)", re.I)
_NUM = re.compile(r"[\d.]+")

# Minimal CSS named-color table (only the common, unambiguous ones).
NAMED_COLORS = {
    "black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0),
    "green": (0, 128, 0), "blue": (0, 0, 255), "gray": (128, 128, 128),
    "grey": (128, 128, 128), "silver": (192, 192, 192), "maroon": (128, 0, 0),
    "yellow": (255, 255, 0), "olive": (128, 128, 0), "lime": (0, 255, 0),
    "aqua": (0, 255, 255), "cyan": (0, 255, 255), "teal": (0, 128, 128),
    "navy": (0, 0, 128), "fuchsia": (255, 0, 255), "magenta": (255, 0, 255),
    "purple": (128, 0, 128), "orange": (255, 165, 0), "darkgray": (169, 169, 169),
    "darkgrey": (169, 169, 169), "lightgray": (211, 211, 211),
    "lightgrey": (211, 211, 211), "dimgray": (105, 105, 105),
}


def best_html(p):
    """Rendered HTML when render succeeded, else raw. Always a string."""
    if getattr(p, "render_status", None) == "ok" and getattr(p, "rendered_html", None):
        return p.rendered_html
    return p.raw_html or ""


def _pct(n, m):
    return f"{n}/{m} pages"


def _to_px(value):
    """Resolve a CSS length to px for the two things we care about (font-size).
    em/rem assume a 16px root; returns None when not a simple length."""
    if value is None:
        return None
    m = _PX.search(value)
    if not m:
        return None
    num = float(m.group(1))
    unit = m.group(2).lower()
    if unit == "px":
        return num
    if unit == "pt":
        return num * 96.0 / 72.0
    if unit in ("rem", "em"):
        return num * 16.0
    return None


def parse_color(s):
    """Resolve a CSS color to an OPAQUE (r,g,b) tuple, else None.
    Returns None for gradients, urls, transparent, currentColor, and any
    rgba/hsla with alpha < 1 (we only reason about fully opaque backgrounds)."""
    if not s:
        return None
    s = s.strip().lower()
    if s in ("transparent", "currentcolor", "inherit", "initial", "unset", "none", "auto"):
        return None
    if s.startswith(("url(", "linear-gradient", "radial-gradient", "conic-gradient")) or "gradient" in s:
        return None
    if s.startswith("#"):
        h = s[1:]
        if len(h) == 3 and re.fullmatch(r"[0-9a-f]{3}", h):
            return tuple(int(c * 2, 16) for c in h)
        if len(h) == 4 and re.fullmatch(r"[0-9a-f]{4}", h):
            if h[3] != "f":
                return None
            return tuple(int(c * 2, 16) for c in h[:3])
        if len(h) == 6 and re.fullmatch(r"[0-9a-f]{6}", h):
            return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
        if len(h) == 8 and re.fullmatch(r"[0-9a-f]{8}", h):
            if h[6:] != "ff":
                return None
            return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
        return None
    if s.startswith("rgb"):
        nums = _NUM.findall(s)
        if s.startswith("rgba"):
            if len(nums) < 4 or float(nums[3]) < 1.0:
                return None
        if len(nums) < 3:
            return None
        try:
            return tuple(min(255, int(round(float(x)))) for x in nums[:3])
        except ValueError:
            return None
    if s.startswith("hsl"):
        return None  # deliberately not resolved; keep FP low
    return NAMED_COLORS.get(s)


def _rel_lum(rgb):
    def chan(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast_ratio(fg, bg):
    l1, l2 = _rel_lum(fg), _rel_lum(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def _parse_decls(block):
    """Turn a CSS declaration block into a lowercased property->value dict."""
    out = {}
    for part in block.split(";"):
        if ":" not in part:
            continue
        prop, _, val = part.partition(":")
        prop = prop.strip().lower()
        val = val.strip()
        if prop and val:
            out[prop] = val
    return out


_RULE_RE = re.compile(r"([^{}]+)\{([^{}]+)\}")
_FONTFACE_RE = re.compile(r"@font-face\s*\{([^{}]+)\}", re.I)


def _style_blocks(soup_obj):
    return [t.get_text() or "" for t in soup_obj.find_all("style")]


# ---------------------------------------------------------------------------
# Check 1: page weight / render-blocking / transfer
# ---------------------------------------------------------------------------
def _check_page_weight(ctx, ok_pages):
    m = len(ok_pages)
    heavy, many_scripts, many_css, no_compress = [], [], [], []
    max_bytes = 0
    max_bytes_url = ""
    script_counts, css_counts = [], []
    for p in ok_pages:
        html = p.raw_html or ""
        nbytes = len(html.encode("utf-8"))
        if nbytes > max_bytes:
            max_bytes, max_bytes_url = nbytes, p.url
        s = htmlutil.soup(html)
        head = s.find("head") or s
        sync = 0
        for sc in head.find_all("script"):
            if sc.has_attr("async") or sc.has_attr("defer"):
                continue
            if (sc.get("type") or "").strip().lower() == "module":
                continue
            sync += 1
        css = sum(1 for lk in head.find_all("link")
                  if "stylesheet" in " ".join(lk.get("rel") or []).lower())
        script_counts.append(sync)
        css_counts.append(css)
        if nbytes > HTML_BYTES_RISK:
            heavy.append(p.url)
        if sync >= SYNC_SCRIPT_RISK:
            many_scripts.append(p.url)
        if css >= STYLESHEET_RISK:
            many_css.append(p.url)
        enc = (p.headers.get("content-encoding") or "").lower()
        is_html = "html" in (p.content_type or "")
        if is_html and not any(tok in enc for tok in COMPRESSION_TOKENS):
            no_compress.append(p.url)
    # Require at least one SUBSTANTIVE factor. Missing compression alone (often a
    # server/harness artifact, immaterial on a small page) must not emit.
    if not (heavy or many_scripts or many_css):
        return []
    parts = []
    factors = []
    if many_scripts:
        parts.append(f"{_pct(len(many_scripts), m)} have >={SYNC_SCRIPT_RISK} sync <script> in <head> "
                     f"(max {max(script_counts)})")
        factors.append("render-blocking scripts")
    if many_css:
        parts.append(f"{_pct(len(many_css), m)} have >={STYLESHEET_RISK} <link rel=stylesheet> in <head> "
                     f"(max {max(css_counts)})")
        factors.append("render-blocking stylesheets")
    if heavy:
        parts.append(f"{_pct(len(heavy), m)} ship >{HTML_BYTES_RISK // 1000}KB of HTML "
                     f"(largest {max_bytes // 1000}KB at {max_bytes_url})")
        factors.append("heavy HTML payload")
        # Missing compression is only a contributing detail once the HTML is large.
        if no_compress:
            parts.append(f"{_pct(len(no_compress), m)} served without gzip/br compression")
    # Title names ONLY the factors actually present.
    if len(factors) == 1:
        title = f"Slow first paint from {factors[0]}"
    else:
        title = "Slow first paint from " + ", ".join(factors[:-1]) + f" and {factors[-1]}"
    strong = sum(1 for f in (heavy, many_scripts, many_css) if f)
    sev = "high" if (heavy or strong >= 2) else "medium"
    evidence = ("Render-blocking / transfer risk factors vs HTTP Archive medians "
                f"(~3 blocking scripts, ~30KB compressed HTML): " + "; ".join(parts) + ".")
    return [make_finding(
        "page-weight-render-blocking-transfer",
        title,
        sev, "engagement", evidence,
        "Defer/async non-critical scripts, inline critical CSS and load the rest "
        "non-blocking, and enable gzip/br on text responses to cut time-to-first-paint.",
        mechanism="Sync scripts and stylesheets in <head> block parsing and rendering; "
                  "uncompressed HTML inflates transfer time. Slow first paint drives bounce.",
        confidence="medium", effort="medium",
        location="onsite-engagement::page-weight",
        evidence_detail={"heavy_html_pages": sorted(heavy),
                         "many_sync_scripts_pages": sorted(many_scripts),
                         "many_stylesheets_pages": sorted(many_css),
                         "uncompressed_pages": sorted(no_compress),
                         "max_html_bytes": max_bytes})]


# ---------------------------------------------------------------------------
# Check 2: image optimization / lazy-load
# ---------------------------------------------------------------------------
def _is_svg_or_data(src):
    src = (src or "").strip().lower()
    return src.startswith("data:") or src.endswith(".svg")


def _check_images(ctx, ok_pages):
    m = len(ok_pages)
    unresp_pages, nonlazy_pages = [], []
    unresp_total, nonlazy_total = 0, 0
    for p in ok_pages:
        s = htmlutil.soup(best_html(p))
        imgs = s.find_all("img")
        page_unresp = 0
        page_nonlazy = 0
        for idx, img in enumerate(imgs):
            src = img.get("src") or img.get("data-src") or ""
            if _is_svg_or_data(src):
                continue
            in_picture = img.find_parent("picture") is not None
            has_srcset = img.has_attr("srcset") or in_picture
            w = _int_attr(img.get("width"))
            h = _int_attr(img.get("height"))
            if not has_srcset and ((w and w >= BIG_INTRINSIC_PX) or (h and h >= BIG_INTRINSIC_PX)):
                page_unresp += 1
            # lazy-load: skip the FIRST image (hero/LCP), only below-fold content imgs
            if idx == 0:
                continue
            loading = (img.get("loading") or "").strip().lower()
            if loading != "lazy":
                page_nonlazy += 1
        if page_unresp:
            unresp_pages.append(p.url)
            unresp_total += page_unresp
        if page_nonlazy:
            nonlazy_pages.append(p.url)
            nonlazy_total += page_nonlazy
    if not (unresp_pages or nonlazy_pages):
        return []
    parts = []
    if unresp_total:
        parts.append(f"{unresp_total} large <img> (>= {BIG_INTRINSIC_PX}px intrinsic) with no "
                     f"srcset/<picture> across {_pct(len(unresp_pages), m)}")
    if nonlazy_total:
        parts.append(f"{nonlazy_total} below-fold content images missing loading=lazy across "
                     f"{_pct(len(nonlazy_pages), m)}")
    evidence = "; ".join(parts) + ". (Hero/first image intentionally excluded.)"
    return [make_finding(
        "image-optimization-lazyload",
        "Images ship at one size and load eagerly below the fold",
        "medium", "engagement", evidence,
        "Add srcset/<picture> responsive variants to large images and loading=lazy to "
        "below-fold content images; leave the hero/LCP image eager.",
        mechanism="Oversized single-resolution images waste bandwidth and delay paint; "
                  "eager below-fold images compete with above-fold content for the network.",
        confidence="medium", effort="low",
        location="onsite-engagement::image-optimization",
        evidence_detail={"unresponsive_pages": sorted(unresp_pages),
                         "nonlazy_pages": sorted(nonlazy_pages),
                         "unresponsive_count": unresp_total,
                         "nonlazy_count": nonlazy_total})]


def _int_attr(v):
    if v is None:
        return None
    m = _NUM.search(str(v))
    if not m:
        return None
    try:
        return int(float(m.group(0)))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Check 3: CLS / layout stability
# ---------------------------------------------------------------------------
def _has_inline_dimension(style):
    style = (style or "").lower()
    return ("aspect-ratio" in style or
            re.search(r"\bwidth\s*:", style) is not None or
            re.search(r"\bheight\s*:", style) is not None)


def _check_cls(ctx, ok_pages):
    m = len(ok_pages)
    dimless_pages, ff_pages = [], []
    dimless_total, ff_total = 0, 0
    for p in ok_pages:
        s = htmlutil.soup(best_html(p))
        page_dimless = 0
        for tag in s.find_all(["img", "video", "iframe"]):
            if tag.name == "img" and _is_svg_or_data(tag.get("src")):
                continue
            has_attr_dim = tag.has_attr("width") and tag.has_attr("height")
            if has_attr_dim:
                continue
            if _has_inline_dimension(tag.get("style")):
                continue
            page_dimless += 1
        if page_dimless:
            dimless_pages.append(p.url)
            dimless_total += page_dimless
        ff = 0
        for block in _style_blocks(s):
            for face in _FONTFACE_RE.findall(block):
                if "font-display" not in face.lower():
                    ff += 1
        if ff:
            ff_pages.append(p.url)
            ff_total += ff
    if not (dimless_pages or ff_pages):
        return []
    parts = []
    if dimless_total:
        parts.append(f"{dimless_total} <img>/<video>/<iframe> with no width/height attrs and no "
                     f"inline size/aspect-ratio across {_pct(len(dimless_pages), m)}")
    if ff_total:
        parts.append(f"{ff_total} @font-face rules omit font-display across {_pct(len(ff_pages), m)}")
    evidence = "; ".join(parts) + "."
    return [make_finding(
        "cls-layout-stability",
        "Media without reserved space and fonts without font-display cause layout shift",
        "medium", "engagement", evidence,
        "Set width/height (or CSS aspect-ratio) on media so space is reserved before load, "
        "and add font-display: swap to @font-face rules.",
        mechanism="Media that loads without reserved dimensions and late-swapping fonts reflow "
                  "the page (Cumulative Layout Shift), which frustrates readers and mis-taps.",
        confidence="medium", effort="low",
        location="onsite-engagement::cls",
        evidence_detail={"dimensionless_media_pages": sorted(dimless_pages),
                         "fontface_no_display_pages": sorted(ff_pages),
                         "dimensionless_count": dimless_total,
                         "fontface_count": ff_total})]


# ---------------------------------------------------------------------------
# Check 4: mobile viewport / zoom
# ---------------------------------------------------------------------------
def _check_viewport(ctx, ok_pages):
    m = len(ok_pages)
    missing, zoom_blocked = [], []
    detail_zoom = {}
    for p in ok_pages:
        s = htmlutil.soup(p.raw_html or "")
        meta = s.find("meta", attrs={"name": re.compile(r"^viewport$", re.I)})
        if meta is None:
            missing.append(p.url)
            continue
        content = (meta.get("content") or "").lower()
        blocked_reason = None
        if re.search(r"user-scalable\s*=\s*(no|0)", content):
            blocked_reason = "user-scalable=no"
        mm = re.search(r"maximum-scale\s*=\s*([\d.]+)", content)
        if mm:
            try:
                if float(mm.group(1)) < 2.0:
                    blocked_reason = (blocked_reason + "; " if blocked_reason else "") + \
                        f"maximum-scale={mm.group(1)}"
            except ValueError:
                pass
        if blocked_reason:
            zoom_blocked.append(p.url)
            detail_zoom[p.url] = blocked_reason
    out = []
    if missing:
        out.append(make_finding(
            "mobile-viewport-zoom",
            "Missing mobile viewport meta tag",
            "high", "engagement",
            f"No <meta name=viewport> on {_pct(len(missing), m)}; mobile browsers render at a "
            "desktop width and zoom out, leaving text tiny.",
            "Add <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"> to the head.",
            mechanism="Without a viewport tag, mobile devices assume ~980px width and shrink the "
                      "page, making content unreadable without manual zoom and driving bounce.",
            confidence="high", effort="low",
            location="onsite-engagement::viewport-missing",
            evidence_detail={"pages": sorted(missing)}))
    if zoom_blocked:
        out.append(make_finding(
            "mobile-viewport-zoom",
            "Viewport disables pinch-zoom (WCAG 1.4.4)",
            "high", "engagement",
            f"Viewport blocks zoom on {_pct(len(zoom_blocked), m)} "
            f"({', '.join(sorted(set(detail_zoom.values())))}).",
            "Remove user-scalable=no and any maximum-scale below 2 so users can pinch-zoom.",
            mechanism="Disabling zoom violates WCAG 1.4.4 (Resize Text) and blocks low-vision "
                      "users from enlarging content, hurting accessibility and engagement.",
            confidence="high", effort="low",
            location="onsite-engagement::viewport-zoom",
            evidence_detail={"pages": detail_zoom}))
    return out


# ---------------------------------------------------------------------------
# Check 5: contrast / legibility (conservative)
# ---------------------------------------------------------------------------
def _large_text(decls):
    size = _to_px(decls.get("font-size"))
    weight = (decls.get("font-weight") or "").lower()
    bold = weight in ("bold", "bolder") or (weight.isdigit() and int(weight) >= 700)
    if size is None:
        return False
    return size >= 24.0 or (size >= 18.66 and bold)


def _pair_from_decls(decls):
    fg = parse_color(decls.get("color"))
    bg = parse_color(decls.get("background-color") or decls.get("background"))
    if fg is None or bg is None:
        return None
    return fg, bg, _large_text(decls)


def _check_contrast(ctx, ok_pages):
    m = len(ok_pages)
    low_pages, small_pages = [], []
    low_total, small_total = 0, 0
    worst = None
    for p in ok_pages:
        s = htmlutil.soup(best_html(p))
        page_low = 0
        # inline styles
        for tag in s.find_all(style=True):
            pair = _pair_from_decls(_parse_decls(tag.get("style")))
            if not pair:
                continue
            fg, bg, large = pair
            ratio = contrast_ratio(fg, bg)
            threshold = 3.0 if large else 4.5
            if ratio < threshold:
                page_low += 1
                if worst is None or ratio < worst[0]:
                    worst = (round(ratio, 2), fg, bg, p.url)
        # <style> rule blocks
        page_small = 0
        for block in _style_blocks(s):
            for selector, body in _RULE_RE.findall(block):
                decls = _parse_decls(body)
                pair = _pair_from_decls(decls)
                if pair:
                    fg, bg, large = pair
                    ratio = contrast_ratio(fg, bg)
                    threshold = 3.0 if large else 4.5
                    if ratio < threshold:
                        page_low += 1
                        if worst is None or ratio < worst[0]:
                            worst = (round(ratio, 2), fg, bg, p.url)
                if re.search(r"\b(body|html)\b", selector, re.I):
                    fs = _to_px(decls.get("font-size"))
                    if fs is not None and fs < SMALL_FONT_PX:
                        page_small += 1
        if page_low:
            low_pages.append(p.url)
            low_total += page_low
        if page_small:
            small_pages.append(p.url)
            small_total += page_small
    out = []
    if low_pages and worst:
        ratio, fg, bg, url = worst
        out.append(make_finding(
            "contrast-legibility-taptargets",
            "Text/background color pairs fall below WCAG contrast minimums",
            "high", "engagement",
            f"{low_total} opaque text/background pairs below WCAG AA across {_pct(len(low_pages), m)}; "
            f"worst {ratio}:1 (rgb{fg} on rgb{bg}) at {url}. AA needs 4.5:1 body / 3:1 large.",
            "Darken text or lighten the background so body text meets 4.5:1 (large text 3:1).",
            mechanism="Low contrast makes copy hard to read, especially on mobile and for "
                      "low-vision users; unreadable text drives immediate bounce.",
            confidence="medium", effort="low",
            location="onsite-engagement::contrast",
            evidence_detail={"pages": sorted(low_pages), "low_pairs": low_total,
                             "worst_ratio": ratio}))
    if small_pages:
        out.append(make_finding(
            "contrast-legibility-taptargets",
            "Body text declared below ~12px",
            "medium", "engagement",
            f"body/html font-size < {int(SMALL_FONT_PX)}px declared on {_pct(len(small_pages), m)}.",
            "Set body copy to at least 16px (12px absolute floor) for comfortable reading.",
            mechanism="Sub-12px body text is hard to read on mobile without zooming, increasing "
                      "cognitive load and abandonment.",
            confidence="low", effort="low",
            location="onsite-engagement::small-font",
            evidence_detail={"pages": sorted(small_pages)}))
    return out


# ---------------------------------------------------------------------------
# Check 6: intrusive interstitial / autoplay
# ---------------------------------------------------------------------------
def _looks_like_overlay(tag):
    style = (tag.get("style") or "").lower()
    classes = " ".join(tag.get("class") or [])
    pos_fixed = "position:fixed" in style.replace(" ", "") or "position:absolute" in style.replace(" ", "")
    zmatch = re.search(r"z-index\s*:\s*(\d+)", style)
    high_z = bool(zmatch and int(zmatch.group(1)) >= HIGH_Z_INDEX)
    large = bool(re.search(r"(width|height)\s*:\s*(100%|100v[wh])", style)) or \
        "backdrop" in style or OVERLAY_CLASS_PAT.search(classes) is not None
    return pos_fixed and (high_z or "backdrop" in style) and large


def _check_interstitial(ctx, ok_pages):
    m = len(ok_pages)
    overlay_pages, autoplay_pages = [], []
    overlay_total, autoplay_total = 0, 0
    for p in ok_pages:
        s = htmlutil.soup(best_html(p))
        page_overlay = 0
        for tag in s.find_all(style=True):
            if not _looks_like_overlay(tag):
                continue
            text = htmlutil.norm_text(tag.get_text(" "))[:400]
            classes = " ".join(tag.get("class") or [])
            if CONSENT_PAT.search(text) or CONSENT_PAT.search(classes):
                continue  # Google-permitted consent/login/age overlays
            page_overlay += 1
        page_autoplay = 0
        for v in s.find_all("video"):
            if v.has_attr("autoplay") and not v.has_attr("muted"):
                page_autoplay += 1
        if page_overlay:
            overlay_pages.append(p.url)
            overlay_total += page_overlay
        if page_autoplay:
            autoplay_pages.append(p.url)
            autoplay_total += page_autoplay
    out = []
    if overlay_pages:
        out.append(make_finding(
            "intrusive-interstitial-autoplay",
            "On-load overlay covers main content",
            "high", "engagement",
            f"{overlay_total} fixed/absolute high-z overlay element(s) covering content on "
            f"{_pct(len(overlay_pages), m)} (consent/cookie/login/age overlays excluded).",
            "Replace full-screen on-load interstitials with inline or easily dismissible banners "
            "that do not obscure content on arrival.",
            mechanism="Interstitials that hide content on arrival are penalized by Google and make "
                      "visitors bounce before they see anything of value.",
            confidence="medium", effort="medium",
            location="onsite-engagement::overlay",
            evidence_detail={"pages": sorted(overlay_pages), "count": overlay_total}))
    if autoplay_pages:
        out.append(make_finding(
            "intrusive-interstitial-autoplay",
            "Video autoplays with sound",
            "high", "engagement",
            f"{autoplay_total} <video autoplay> without muted across {_pct(len(autoplay_pages), m)}.",
            "Add the muted attribute to autoplaying video, or require a user gesture to start playback.",
            mechanism="Unmuted autoplay startles visitors and is blocked by most browsers, so the "
                      "video often fails while still disrupting the experience.",
            confidence="high", effort="low",
            location="onsite-engagement::autoplay",
            evidence_detail={"pages": sorted(autoplay_pages), "count": autoplay_total}))
    return out


# ---------------------------------------------------------------------------
# Check 7: mixed content / HTTPS
# ---------------------------------------------------------------------------
_RESOURCE_ATTRS = {"script": "src", "link": "href", "iframe": "src",
                   "img": "src", "video": "src", "source": "src", "audio": "src"}
_ACTIVE_TAGS = {"script", "link", "iframe"}


def _site_declares_https(ctx, ok_pages):
    """True when the deployed site itself declares HTTPS, even if we fetched over
    http (staging/localhost/pre-redirect origins are common in audits). Any of a
    successful https fetch, an https rel=canonical, an https og:url, or an https
    sitemap entry proves the site is HTTPS and suppresses the plain-HTTP finding."""
    for p in ok_pages:
        if (p.final_url or p.url or "").lower().startswith("https://"):
            return True
        s = htmlutil.soup(best_html(p))
        for lk in s.find_all("link"):
            if "canonical" in " ".join(lk.get("rel") or []).lower():
                if (lk.get("href") or "").strip().lower().startswith("https://"):
                    return True
        og = s.find("meta", attrs={"property": re.compile(r"^og:url$", re.I)})
        if og and (og.get("content") or "").strip().lower().startswith("https://"):
            return True
    for sm in (getattr(ctx.robots, "sitemaps", None) or []):
        if str(sm).lower().startswith("https://"):
            return True
    return False


def _check_mixed_content(ctx, ok_pages):
    out = []
    # Only flag "no HTTPS" when the SITE ITSELF declares http (or has no https
    # self-reference anywhere) — not merely because the fetched scheme is http.
    if not _site_declares_https(ctx, ok_pages):
        out.append(make_finding(
            "mixed-content-https",
            "Site is served over plain HTTP",
            "high", "both",
            f"Origin {ctx.site} declares no HTTPS (no https canonical, og:url, or sitemap); "
            "traffic is unencrypted and browsers mark it 'Not secure'.",
            "Obtain a TLS certificate and redirect all HTTP traffic to HTTPS.",
            mechanism="Non-HTTPS pages are flagged insecure, blocked from modern APIs, and ranked "
                      "down; visitors distrust and abandon them.",
            confidence="high", effort="medium",
            location="onsite-engagement::no-https"))
    https_pages = [p for p in ok_pages if (p.final_url or p.url).lower().startswith("https://")]
    m = len(https_pages)
    if m:
        active_pages, passive_pages = [], []
        active_total, passive_total = 0, 0
        for p in https_pages:
            s = htmlutil.soup(best_html(p))
            a_cnt = pv_cnt = 0
            for tag, attr in _RESOURCE_ATTRS.items():
                for el in s.find_all(tag):
                    val = (el.get(attr) or "").strip()
                    if val.lower().startswith("http://"):
                        if tag in _ACTIVE_TAGS:
                            a_cnt += 1
                        else:
                            pv_cnt += 1
            if a_cnt:
                active_pages.append(p.url)
                active_total += a_cnt
            if pv_cnt:
                passive_pages.append(p.url)
                passive_total += pv_cnt
        if active_pages or passive_pages:
            parts = []
            if active_total:
                parts.append(f"{active_total} ACTIVE (script/link/iframe) across {_pct(len(active_pages), m)}")
            if passive_total:
                parts.append(f"{passive_total} passive (img/video) across {_pct(len(passive_pages), m)}")
            sev = "high" if active_total else "medium"
            out.append(make_finding(
                "mixed-content-https",
                "HTTPS pages load subresources over http://",
                sev, "both",
                "Mixed content: " + "; ".join(parts) + ". Protocol-relative and data: URIs ignored.",
                "Change http:// subresource URLs to https:// (or protocol-relative) so nothing is "
                "blocked or downgraded.",
                mechanism="Active mixed content is blocked by browsers (breaking the page); passive "
                          "mixed content is downgraded and triggers 'Not fully secure' warnings.",
                confidence="high", effort="low",
                location="onsite-engagement::mixed-content",
                evidence_detail={"active_pages": sorted(active_pages),
                                 "passive_pages": sorted(passive_pages),
                                 "active_count": active_total,
                                 "passive_count": passive_total}))
    return out


# ---------------------------------------------------------------------------
# Check 8: broken internal links (network-dependent)
# ---------------------------------------------------------------------------
_SKIP_LINK_PREFIX = ("mailto:", "tel:", "javascript:", "#", "data:")


def _check_broken_links(ctx, ok_pages):
    seen = set()
    candidates = []
    sampled = {p.url for p in ctx.pages}
    for p in ok_pages:
        base = p.final_url or p.url
        for a in htmlutil.soup(best_html(p)).find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.lower().startswith(_SKIP_LINK_PREFIX):
                continue
            u = urljoin(base, href).split("#")[0]
            if u.endswith("/") and urlparse(u).path not in ("", "/"):
                u = u[:-1]
            pu = urlparse(u)
            if f"{pu.scheme}://{pu.netloc}" != ctx.site:
                continue
            if u in seen or u in sampled:
                continue
            seen.add(u)
            candidates.append(u)
    candidates = sorted(candidates)[:15]
    if not candidates:
        return []
    broken, tested = {}, 0
    for u in candidates:
        res = ctx.fetch_extra(u, "head")
        fc = res.get("fetch_class")
        if fc in ("capped", "robots_disallowed"):
            continue
        tested += 1
        if fc == "not_found":
            broken[u] = res.get("status")
    if not broken or tested == 0:
        return []
    listed = ", ".join(f"{u} ({st})" for u, st in sorted(broken.items())[:5])
    return [make_finding(
        "broken-internal-links",
        "Internal links point to missing pages",
        "medium", "engagement",
        f"{len(broken)}/{tested} sampled internal links returned 404/410: {listed}"
        f"{'...' if len(broken) > 5 else ''}. Network-dependent HEAD probe; gated/rate-limited "
        "links were treated as inconclusive.",
        "Fix or redirect the broken internal links so visitors don't hit dead ends.",
        mechanism="Dead internal links strand visitors on error pages and waste crawl budget, "
                  "eroding trust and engagement.",
        confidence="high", effort="low",
        location="onsite-engagement::broken-links",
        evidence_detail={"broken": {u: st for u, st in sorted(broken.items())},
                         "tested": tested})]


# ---------------------------------------------------------------------------
# Check 9: readability / scannability
# ---------------------------------------------------------------------------
def _check_readability(ctx, ok_pages):
    m = len(ok_pages)
    scored = []
    dense_pages = []
    wall_pages = []
    for p in ok_pages:
        html = best_html(p)
        text = htmlutil.main_text(html)
        # Be conservative: only assess pages whose main content is genuinely long.
        # Short pages and moderately dense expert copy must not trip this check.
        if htmlutil.word_count(text) < READABILITY_MIN_WORDS:
            continue
        score = htmlutil.flesch_reading_ease(text)
        if score is None or score >= FLESCH_HARD:
            continue
        scored.append((p.url, score))
        dense_pages.append(p.url)
        # wall-of-text: a very long paragraph with no lists/subheadings in main content
        s = htmlutil.soup(html)
        node = s.find("main") or s.find("article") or s.find("body") or s
        long_p = any(htmlutil.word_count(pp.get_text(" ")) > LONG_PARAGRAPH_WORDS
                     for pp in node.find_all("p"))
        has_structure = bool(node.find_all(["ul", "ol", "h2", "h3", "h4"]))
        if long_p and not has_structure:
            wall_pages.append(p.url)
    if not dense_pages:
        return []
    parts = []
    if dense_pages:
        avg = round(sum(sc for _, sc in scored) / len(scored), 1) if scored else None
        parts.append(f"Flesch reading ease < {int(FLESCH_HARD)} (very hard) on {_pct(len(dense_pages), m)} "
                     f"(avg {avg} across {len(scored)} scored, {READABILITY_MIN_WORDS}+ words each)")
    if wall_pages:
        parts.append(f"wall-of-text (>{LONG_PARAGRAPH_WORDS}-word paragraphs, no lists/subheadings) "
                     f"on {_pct(len(wall_pages), m)}")
    evidence = "; ".join(parts) + ". English Flesch heuristic; legal/technical copy is legitimately dense."
    return [make_finding(
        "readability-scannability",
        "Content is dense and hard to scan",
        "low", "engagement", evidence,
        "Shorten sentences, break long paragraphs, and add subheadings/lists so pages are "
        "scannable (unless the domain is inherently technical/legal).",
        mechanism="Dense, unstructured prose is hard to skim; visitors who can't scan for their "
                  "answer leave. Caveat: dense reading level can be appropriate for the domain.",
        confidence="low", effort="medium",
        location="onsite-engagement::readability",
        evidence_detail={"dense_pages": sorted(dense_pages),
                         "wall_of_text_pages": sorted(wall_pages),
                         "scores": {u: sc for u, sc in scored}})]


# ---------------------------------------------------------------------------
# Check 10: landmarks / skip-link / value proposition
# ---------------------------------------------------------------------------
def _check_landmarks(ctx, ok_pages):
    m = len(ok_pages)
    no_main, no_skip, no_valueprop = [], [], []
    for p in ok_pages:
        s = htmlutil.soup(best_html(p))
        has_main = s.find("main") is not None or \
            s.find(attrs={"role": re.compile(r"^main$", re.I)}) is not None
        if not has_main:
            no_main.append(p.url)
        skip = False
        for a in s.find_all("a", href=True):
            if a["href"].startswith("#") and "skip" in htmlutil.norm_text(a.get_text(" ")):
                skip = True
                break
        if not skip:
            no_skip.append(p.url)
        h1 = s.find("h1")
        near_text = False
        if h1 is not None:
            for pp in list(h1.find_all_next("p"))[:3]:
                if htmlutil.word_count(pp.get_text(" ")) >= 10:
                    near_text = True
                    break
        if not (h1 is not None and near_text):
            no_valueprop.append(p.url)
    parts = []
    if no_main:
        parts.append(f"no <main>/role=main on {_pct(len(no_main), m)}")
    if no_skip:
        parts.append(f"no skip-to-content link on {_pct(len(no_skip), m)}")
    if no_valueprop:
        parts.append(f"no clear above-fold value prop (H1 + descriptive paragraph) on "
                     f"{_pct(len(no_valueprop), m)}")
    if not parts:
        return []
    evidence = "; ".join(parts) + ". Heuristic; value-prop baked into a hero image is not detected."
    return [make_finding(
        "landmarks-skiplink-valueprop",
        "Missing landmarks, skip link, or a clear above-fold value proposition",
        "low", "engagement", evidence,
        "Wrap primary content in <main>, add a skip-to-content link, and lead with an H1 plus a "
        "one-line description of what the page offers.",
        mechanism="Landmarks and skip links aid keyboard/screen-reader navigation; a clear "
                  "above-fold value prop tells arrivals they're in the right place, reducing bounce.",
        confidence="low", effort="low",
        location="onsite-engagement::landmarks",
        evidence_detail={"no_main_pages": sorted(no_main),
                         "no_skiplink_pages": sorted(no_skip),
                         "no_valueprop_pages": sorted(no_valueprop)})]


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
_CHECKS = [
    _check_page_weight,
    _check_images,
    _check_cls,
    _check_viewport,
    _check_contrast,
    _check_interstitial,
    _check_mixed_content,
    _check_broken_links,
    _check_readability,
    _check_landmarks,
]


def run(ctx):
    """Run every engagement check over the readable page sample and return findings."""
    ok_pages = [p for p in ctx.pages if p.ok]
    if not ok_pages:
        return []
    findings = []
    for check in _CHECKS:
        try:
            findings.extend(check(ctx, ok_pages) or [])
        except Exception:
            continue
    return findings


if __name__ == '__main__':
    import json
    from common import fetch
    ctx = fetch.build_context(sys.argv[1])
    print(json.dumps(run(ctx), indent=2, default=str))
    ctx.close()
