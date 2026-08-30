#!/usr/bin/env python3
"""Deterministically audit every blind adversary site and save our findings.

This is the objective, no-model step of the blind evaluation: serve each site in
evaluation/blackbox/sites/<name>/ and run the entrypoint auditor, writing our findings
to evaluation/blackbox/findings/<name>.json. Adjudication (scoring TP/FP/FN against the
sealed ground truth in evaluation/blackbox/truth/) is done separately by independent
blind judges — never by this script or its author.

Run: python3 evaluation/blackbox/run_eval.py
"""
import functools
import importlib.util
import json
import os
import sys
import threading
import warnings
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BB = os.path.join(ROOT, "evaluation", "blackbox")
sys.path.insert(0, ROOT)
warnings.filterwarnings("ignore")  # quiet bs4 XMLParsedAsHTMLWarning on sitemap files


def _entry():
    path = os.path.join(ROOT, "skills", "website-ai-audit", "scripts", "audit.py")
    spec = importlib.util.spec_from_file_location("wai_audit", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def main():
    entry = _entry()
    os.makedirs(os.path.join(BB, "findings"), exist_ok=True)
    sites_dir = os.path.join(BB, "sites")
    if not os.path.isdir(sites_dir):
        print("no blind sites found at", sites_dir); return 1
    print(f"{'site':<22}{'start':<14}{'findings (C/H/M/L)':<22}disc/eng")
    for name in sorted(os.listdir(sites_dir)):
        site_dir = os.path.join(sites_dir, name)
        if not os.path.isdir(site_dir):
            continue
        truth_path = os.path.join(BB, "truth", f"{name}.json")
        start = "/"
        if os.path.isfile(truth_path):
            start = json.load(open(truth_path, encoding="utf-8")).get("start_path", "/")
        handler = functools.partial(_Quiet, directory=os.path.abspath(site_dir))
        srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            rep = entry.run_audit(f"http://127.0.0.1:{srv.server_address[1]}{start}",
                                  max_pages=12, render=False, audited_at="2026-01-01T00:00:00Z")
        finally:
            srv.shutdown()
        with open(os.path.join(BB, "findings", f"{name}.json"), "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=2, ensure_ascii=False)
        s = rep["summary"]
        print(f"{name:<22}{start:<14}"
              + f"{s['total_findings']:>2} ({s['critical']}/{s['high']}/{s['medium']}/{s.get('low',0)})".ljust(22)
              + f"{s.get('discoverability',0)}/{s.get('engagement',0)}")
    print("\nfindings -> evaluation/blackbox/findings/  (adjudicate separately with blind judges)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
