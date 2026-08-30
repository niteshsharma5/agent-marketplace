#!/usr/bin/env python3
"""Entrypoint runtime for the brand-ai-audit marketplace.

Two modes:

1. Deterministic full report (default) — runs every sub-skill's script checks and
   emits the complete report with no LLM. Used by CI, the eval suite, and anyone
   who wants a fast, reproducible, script-only audit.
       python3 audit.py <URL> --out ./out

2. Hybrid signal mode (--emit-context) — runs the same deterministic checks but,
   instead of finalizing, writes:
       out/signals.json   the deterministic (script) findings
       out/context.json   a per-page evidence pack the invoking AGENT reasons over
       out/scope.json     crawl scope + per-skill errors
   The agent then adds judgment findings (answer-readiness, entity clarity,
   site-specific fixes) to out/agent_findings.json and calls compose.py to merge
   everything into the final schema-valid report. See the entrypoint SKILL.md.

Read-only and recommend-only in both modes: GET/HEAD only, robots honored, no writes to the target.
"""
import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, ROOT)

from common import fetch, report, htmlutil  # noqa: E402

SUBSKILLS = [
    "crawler-access",
    "machine-readability",
    "fact-extractability",
    "entity-trust",
    "onsite-engagement",
]
EXCERPT_CHARS = 1400


def _load_run(skill):
    path = os.path.join(ROOT, "skills", skill, "scripts", "checks.py")
    spec = importlib.util.spec_from_file_location(f"{skill.replace('-', '_')}_checks", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.run


def _best_html(p):
    if p.render_status == "ok" and p.rendered_html:
        return p.rendered_html
    return p.raw_html


def gather_signals(ctx):
    """Run every sub-skill's deterministic checks over the shared context."""
    findings, errors = [], []
    for skill in SUBSKILLS:
        try:
            findings.extend(_load_run(skill)(ctx) or [])
        except Exception as e:
            errors.append(f"{skill}: {type(e).__name__}: {e}")
    scope = {
        "pages_sampled": len(ctx.pages),
        "pages_readable": sum(1 for p in ctx.pages if p.ok),
        "urls": [p.url for p in ctx.pages],
        "render_available": ctx.render_available,
        "robots_txt_found": ctx.robots.exists,
        "offline_replay": getattr(ctx, "offline", False),
        "skills_run": SUBSKILLS,
        "skill_errors": errors,
    }
    return findings, scope


def build_context_pack(ctx):
    """A compact, already-fetched evidence pack the agent reasons over — no re-fetch.

    Gives the agent the machine-readable facts (title/meta/headings/JSON-LD/alt/
    viewport) plus a bounded main-text excerpt per readable page, so it can judge
    answer-readiness, entity clarity, and value-prop quality without touching the site."""
    pages = []
    for p in ctx.pages:
        if not p.ok:
            pages.append({"url": p.url, "fetch_class": p.fetch_class, "status": p.status})
            continue
        html = _best_html(p)
        s = htmlutil.soup(html)
        title = (s.title.get_text(strip=True) if s.title else "")
        md = s.find("meta", attrs={"name": "description"})
        meta_desc = md.get("content", "").strip() if md else ""
        htmltag = s.find("html")
        lang = htmltag.get("lang", "") if htmltag else ""
        canon = s.find("link", attrs={"rel": lambda v: v and "canonical" in (v if isinstance(v, str) else " ".join(v)).lower()})
        canonical = canon.get("href", "") if canon else ""
        h1s = [h.get_text(" ", strip=True) for h in s.find_all("h1")][:5]
        headings = []
        for tag in s.find_all(["h2", "h3"]):
            t = tag.get_text(" ", strip=True)
            if t:
                headings.append(f"{tag.name}: {t}")
            if len(headings) >= 15:
                break
        jsonld = []
        for node in htmlutil.jsonld_blocks(html)[:12]:
            entry = {"types": sorted(htmlutil.schema_types(node))}
            for k in ("name", "headline"):
                if isinstance(node.get(k), str):
                    entry[k] = node[k][:120]
            jsonld.append(entry)
        imgs = s.find_all("img")
        missing_alt = sum(1 for i in imgs if i.get("alt") is None)
        vp = s.find("meta", attrs={"name": "viewport"})
        main_excerpt = (p.rendered_main_text or p.raw_main_text or "")[:EXCERPT_CHARS]
        pages.append({
            "url": p.url,
            "fetch_class": p.fetch_class,
            "render_status": p.render_status,
            "title": title,
            "meta_description": meta_desc,
            "lang": lang,
            "canonical": canonical,
            "h1": h1s,
            "headings": headings,
            "jsonld": jsonld,
            "images_total": len(imgs),
            "images_missing_alt": missing_alt,
            "has_viewport": vp is not None,
            "main_text_excerpt": main_excerpt,
        })
    return {
        "site": ctx.site,
        "render_available": ctx.render_available,
        "robots_txt_found": ctx.robots.exists,
        "sitemaps": list(ctx.robots.sitemaps),
        "pages": pages,
    }


def run_over_context(ctx, *, audited_at=None):
    try:
        findings, scope = gather_signals(ctx)
    finally:
        ctx.close()
    at = audited_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rep = report.assemble_report(ctx.site, findings, at, scope=scope)
    report.validate(rep)
    return rep


def run_audit(url, *, max_pages=12, render=True, audited_at=None):
    ctx = fetch.build_context(url, max_pages=max_pages, render=render)
    return run_over_context(ctx, audited_at=audited_at)


def run_audit_snapshot(data, *, audited_at=None):
    ctx = fetch.build_context_from_snapshot(data)
    return run_over_context(ctx, audited_at=audited_at)


def _write(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Audit a website for AI discoverability + on-site engagement.")
    ap.add_argument("url")
    ap.add_argument("--max-pages", type=int, default=12)
    ap.add_argument("--no-render", action="store_true", help="skip Playwright render (static-only)")
    ap.add_argument("--out", help="output directory (default: stdout JSON)")
    ap.add_argument("--format", choices=["json", "md", "both"], default="both")
    ap.add_argument("--audited-at", help="override timestamp (for deterministic tests)")
    ap.add_argument("--emit-context", action="store_true",
                    help="hybrid mode: write signals.json + context.json + scope.json for the agent to reason over (no final report)")
    a = ap.parse_args(argv)

    if a.emit_context:
        out = a.out or "./out"
        os.makedirs(out, exist_ok=True)
        ctx = fetch.build_context(a.url, max_pages=a.max_pages, render=not a.no_render)
        try:
            findings, scope = gather_signals(ctx)
            pack = build_context_pack(ctx)
        finally:
            ctx.close()
        _write(os.path.join(out, "signals.json"), findings)
        _write(os.path.join(out, "context.json"), pack)
        _write(os.path.join(out, "scope.json"), scope)
        print(f"emitted signals.json ({len(findings)} script findings), context.json "
              f"({len(pack['pages'])} pages), scope.json -> {out}\n"
              f"Next: reason over context.json, write {out}/agent_findings.json, then run compose.py.")
        return 0

    rep = run_audit(a.url, max_pages=a.max_pages, render=not a.no_render, audited_at=a.audited_at)
    js = json.dumps(rep, indent=2, ensure_ascii=False)
    md = report.to_markdown(rep)
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        if a.format in ("json", "both"):
            _write(os.path.join(a.out, "report.json"), rep)
        if a.format in ("md", "both"):
            with open(os.path.join(a.out, "report.md"), "w", encoding="utf-8") as f:
                f.write(md)
        s = rep["summary"]
        print(f"Audited {rep['site']} -> {a.out}  ({s['total_findings']} findings: "
              f"{s['critical']}C/{s['high']}H/{s['medium']}M/{s['low']}L)")
    else:
        print(js if a.format != "md" else md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
