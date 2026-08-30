#!/usr/bin/env python3
"""Robustness harnesses: determinism, robots politeness, and runtime/size budget.

- determinism: run the entrypoint twice on a static fixture with a fixed timestamp;
  assert byte-identical JSON.
- robots politeness: serve a site with Disallow:/private/ and record every path the
  auditor requests; assert /private/ is never fetched and never appears in a finding,
  and only GET/HEAD are used.
- budget: time a fixture run and assert the packaged size is < 50 MB with no weights.

Run: python3 evaluation/run_harness.py
"""
import functools
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FIX = os.path.join(ROOT, "evaluation", "fixtures")
sys.path.insert(0, ROOT)

fails = []


def _entry():
    path = os.path.join(ROOT, "skills", "website-ai-audit", "scripts", "audit.py")
    spec = importlib.util.spec_from_file_location("wai_audit", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_recording_handler(sink, directory):
    class H(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=directory, **k)

        def _rec(self):
            sink.append((self.command, self.path))

        def do_GET(self):
            self._rec(); super().do_GET()

        def do_HEAD(self):
            self._rec(); super().do_HEAD()

        def do_POST(self):
            self._rec()
            self.send_error(405)

        def log_message(self, *a):
            pass
    return H


def _serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def _pick_fixture():
    """Any defect fixture dir works for determinism/budget timing."""
    man = json.load(open(os.path.join(ROOT, "evaluation", "manifest.json"), encoding="utf-8"))
    for c in man["cases"]:
        d = os.path.join(FIX, c["dir"])
        if os.path.isdir(d):
            return d, c.get("start", "/")
    return None, "/"


def test_determinism(entry):
    d, start = _pick_fixture()
    if not d:
        fails.append("determinism: no fixtures found"); return
    handler = functools.partial(SimpleHTTPRequestHandler, directory=d)
    srv, port = _serve(handler)
    try:
        url = f"http://127.0.0.1:{port}{start}"
        r1 = json.dumps(entry.run_audit(url, render=False, audited_at="2026-01-01T00:00:00Z"), sort_keys=False)
        r2 = json.dumps(entry.run_audit(url, render=False, audited_at="2026-01-01T00:00:00Z"), sort_keys=False)
    finally:
        srv.shutdown()
    print("determinism:", "PASS (byte-identical)" if r1 == r2 else "FAIL (differs)")
    if r1 != r2:
        fails.append("determinism")


def test_politeness(entry):
    site = os.path.join(FIX, "_harness", "robots-politeness")
    if not os.path.isdir(site):
        print("politeness: SKIP (fixture evaluation/fixtures/_harness/robots-politeness missing)")
        return
    sink = []
    handler = _make_recording_handler(sink, site)
    srv, port = _serve(handler)
    try:
        rep = entry.run_audit(f"http://127.0.0.1:{port}/", render=False,
                              audited_at="2026-01-01T00:00:00Z")
    finally:
        srv.shutdown()
    private = [p for _, p in sink if p.startswith("/private/")]
    methods = {m for m, _ in sink}
    cited = [f["id"] for f in rep["findings"] if "/private/" in json.dumps(f)]
    ok = not private and methods <= {"GET", "HEAD"} and not cited
    print(f"politeness: {'PASS' if ok else 'FAIL'} "
          f"(private-fetches={len(private)}, methods={sorted(methods)}, private-in-findings={len(cited)})")
    if not ok:
        fails.append("politeness")


def test_budget(entry):
    d, start = _pick_fixture()
    if d:
        handler = functools.partial(SimpleHTTPRequestHandler, directory=d)
        srv, port = _serve(handler)
        try:
            t0 = time.perf_counter()
            entry.run_audit(f"http://127.0.0.1:{port}{start}", render=False, audited_at="2026-01-01T00:00:00Z")
            dt = time.perf_counter() - t0
        finally:
            srv.shutdown()
        print(f"budget/runtime: {'PASS' if dt < 300 else 'FAIL'} (one fixture audit took {dt:.2f}s, limit 300s)")
        if dt >= 300:
            fails.append("runtime")

    weights = subprocess.run(
        ["bash", "-lc", f"find {ROOT} -type f \\( -name '*.bin' -o -name '*.safetensors' "
         f"-o -name '*.gguf' -o -name '*.pt' -o -name '*.onnx' \\) | head"],
        capture_output=True, text=True).stdout.strip()
    du = subprocess.run(["bash", "-lc", f"du -sm {ROOT} | cut -f1"], capture_output=True, text=True).stdout.strip()
    size_mb = int(du) if du.isdigit() else 999
    ok = size_mb < 50 and not weights
    print(f"budget/size: {'PASS' if ok else 'FAIL'} (tree {size_mb} MB, weight-files={'none' if not weights else weights})")
    if not ok:
        fails.append("size")


def main():
    entry = _entry()
    test_determinism(entry)
    test_politeness(entry)
    test_budget(entry)
    print("\n" + ("ALL HARNESSES PASS" if not fails else f"HARNESS FAILURES: {fails}"))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
