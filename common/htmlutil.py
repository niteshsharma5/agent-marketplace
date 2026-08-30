"""Shared HTML parsing + text normalization.

All skills use these so raw-vs-rendered comparisons, readability, and text
matching are computed identically everywhere (critical for the render-gap check).
Pure stdlib + BeautifulSoup/lxml — no extruct/trafilatura/textstat dependency.
"""
import json
import re
from bs4 import BeautifulSoup

_WS = re.compile(r"\s+")
_NONWORD = re.compile(r"[^a-z0-9]+")
_SENT_SPLIT = re.compile(r"[.!?]+")
_VOWEL_GROUP = re.compile(r"[aeiouy]+")

_BOILERPLATE_TAGS = ("script", "style", "noscript", "template", "svg", "head")
_CHROME_TAGS = ("nav", "header", "footer", "aside", "form")


def soup(html):
    """Parse with lxml, falling back to the stdlib parser."""
    if not html:
        return BeautifulSoup("", "html.parser")
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def norm_text(s):
    """Lowercase, collapse whitespace — the canonical form for text comparison."""
    return _WS.sub(" ", (s or "").lower()).strip()


def visible_text(html):
    """All human-visible text with script/style stripped."""
    s = soup(html)
    for t in s(list(_BOILERPLATE_TAGS)):
        t.decompose()
    return _WS.sub(" ", s.get_text(" ")).strip()


def main_text(html):
    """Best-effort main-content text: <main>/<article> if present, else the body
    minus obvious site chrome. Deterministic; used for render-gap + readability so
    nav/footer boilerplate doesn't dominate the signal."""
    s = soup(html)
    for t in s(list(_BOILERPLATE_TAGS)):
        t.decompose()
    node = s.find("main") or s.find("article")
    if node is None:
        body = s.find("body") or s
        for t in body(list(_CHROME_TAGS)):
            t.decompose()
        node = body
    return _WS.sub(" ", node.get_text(" ")).strip()


def jsonld_blocks(html):
    """Parsed JSON-LD objects (flattened @graph), tolerant of one bad block."""
    out = []
    for tag in soup(html).find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        raw = tag.string or tag.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict) and "@graph" in item and isinstance(item["@graph"], list):
                out.extend([g for g in item["@graph"] if isinstance(g, dict)])
            elif isinstance(item, dict):
                out.append(item)
    return out


def schema_types(obj):
    """Normalized set of @type values on a JSON-LD node."""
    t = obj.get("@type")
    vals = t if isinstance(t, list) else [t]
    return {str(v).lower() for v in vals if v}


def word_count(text):
    return len(re.findall(r"[a-zA-Z0-9']+", text or ""))


def _syllables(word):
    word = _NONWORD.sub("", word.lower())
    if not word:
        return 0
    groups = _VOWEL_GROUP.findall(word)
    n = len(groups)
    if word.endswith("e") and n > 1 and not word.endswith(("le", "ie", "ee")):
        n -= 1
    return max(1, n)


def flesch_reading_ease(text):
    """Flesch Reading Ease via a heuristic syllable counter (no textstat/cmudict).
    Returns None when there isn't enough text to be meaningful."""
    words = re.findall(r"[a-zA-Z']+", text or "")
    sentences = [x for x in _SENT_SPLIT.split(text or "") if x.strip()]
    if len(words) < 100 or len(sentences) < 3:
        return None
    syl = sum(_syllables(w) for w in words)
    wps = len(words) / len(sentences)
    spw = syl / len(words)
    return round(206.835 - 1.015 * wps - 84.6 * spw, 1)
