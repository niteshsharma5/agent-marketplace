#!/usr/bin/env python3
"""Capture a website crawl to an offline snapshot, or replay a snapshot through the audit.

Capture (run OUTSIDE the sandbox, where the site is reachable):
    python3 evaluation/capture.py <URL> evaluation/snapshots/<name>.json [--max-pages N] [--no-render]

Replay (runs anywhere, incl. the sandbox — deterministic):
    python3 evaluation/capture.py --replay evaluation/snapshots/<name>.json [--out DIR]
    python3 evaluation/capture.py --replay-all evaluation/snapshots [--out DIR]

Snapshots freeze every sampled page (raw + rendered HTML + headers) and robots.txt,
so the field suite is reproducible and needs no network at replay time. Network-only
checks (sameAs resolvability, broken links) report 'inconclusive' in replay.
"""
import argparse
import glob
import importlib.util
import json
import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from common import fetch  # noqa: E402


def _entry():
    path = os.path.join(ROOT, "skills", "website-ai-audit", "scripts", "audit.py")
    spec = importlib.util.spec_from_file_location("wai_audit", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def capture(url, out, max_pages, render):
    ctx = fetch.build_context(url, max_pages=max_pages, render=render)
    snap = ctx.to_snapshot()
    ctx.close()
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(snap, f)
    ok = sum(1 for p in snap["pages"] if p.get("fetch_class") == "ok")
    print(f"captured {url} -> {out}  ({len(snap['pages'])} pages, {ok} readable, "
          f"render_available={snap['render_available']})")


def replay_one(entry, path, audited_at="2026-01-01T00:00:00Z"):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    t0 = time.perf_counter()
    rep = entry.run_audit_snapshot(data, audited_at=audited_at)
    dt = time.perf_counter() - t0
    return rep, dt


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", nargs="?", help="URL to capture")
    ap.add_argument("out", nargs="?", help="snapshot output path")
    ap.add_argument("--max-pages", type=int, default=12)
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--replay", metavar="SNAPSHOT", help="replay one snapshot through the audit")
    ap.add_argument("--replay-all", metavar="DIR", help="replay every *.json snapshot in DIR")
    ap.add_argument("--out-dir", help="write report.json per replayed snapshot")
    a = ap.parse_args(argv)

    if a.replay or a.replay_all:
        entry = _entry()
        paths = [a.replay] if a.replay else sorted(glob.glob(os.path.join(a.replay_all, "*.json")))
        if not paths:
            print("no snapshots found"); return 1
        failures = 0
        print(f"{'snapshot':<28} {'time':>6}  {'findings (C/H/M/L)':<20} status")
        for p in paths:
            name = os.path.basename(p)
            try:
                rep, dt = replay_one(entry, p)
                s = rep["summary"]
                tag = "OK" if dt < 300 else "SLOW>5min"
                print(f"{name:<28} {dt:5.1f}s  "
                      f"{s['total_findings']:>2} ({s['critical']}/{s['high']}/{s['medium']}/{s.get('low',0)})".ljust(50)
                      + tag)
                if a.out_dir:
                    os.makedirs(a.out_dir, exist_ok=True)
                    with open(os.path.join(a.out_dir, name.replace(".json", ".report.json")), "w", encoding="utf-8") as f:
                        json.dump(rep, f, indent=2, ensure_ascii=False)
            except Exception as e:
                failures += 1
                print(f"{name:<28}   ---   FAIL: {type(e).__name__}: {e}")
        print(f"\n{len(paths)-failures}/{len(paths)} snapshots replayed cleanly.")
        return 1 if failures else 0

    if not a.url or not a.out:
        ap.print_help(); return 2
    capture(a.url, a.out, a.max_pages, not a.no_render)
    return 0


if __name__ == "__main__":
    sys.exit(main())
